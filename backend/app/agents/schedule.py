"""Loop 定时触发器（Schedule）。

支持 cron 表达式（标准 5 段 m h dom mon dow 子集），模式：
- L1 report：只读分析 + 更新 STATE，不修改代码。
- L2 action：需要用户确认后 Builder 才会落盘。

提供轻量级内存调度器（每分钟检查一次），不引入 APScheduler 等重依赖。

上线加固两点：
1) next_run 计算不再是"逐分钟扫描最多 4 年"（实测最坏 581ms 同步阻塞事件循环），
   改为按天推进 + 在命中日内取最早时刻，复杂度从 O(210 万) 降到 O(1461)。
2) 多副本部署时，每个副本都会起自己的调度器。触发前通过**数据库原子抢占**
   （CAS on next_run_at）决定归属，确保同一次到期只被一个副本执行。
"""

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from . import db

logger = logging.getLogger(__name__)

_SCHEDULER_TASK: Optional[asyncio.Task] = None

# 最多向前搜索 4 年（闰年 + 2/29 等极端表达式）
_MAX_SEARCH_DAYS = 366 * 4


@dataclass(frozen=True)
class CronExpr:
    minute: set
    hour: set
    day_of_month: set
    month: set
    day_of_week: set
    dom_restricted: bool = False
    dow_restricted: bool = False

    @classmethod
    def parse(cls, expr: str) -> "CronExpr":
        """解析 cron：m h dom mon dow（0=周日）。"""
        parts = (expr or "").strip().split()
        if len(parts) != 5:
            raise ValueError(f"不支持的 cron 表达式: {expr}（需要 5 段 m h dom mon dow）")
        return cls(
            minute=_parse_field(parts[0], 0, 59),
            hour=_parse_field(parts[1], 0, 23),
            day_of_month=_parse_field(parts[2], 1, 31),
            month=_parse_field(parts[3], 1, 12),
            day_of_week=_parse_field(parts[4], 0, 7),
            dom_restricted=parts[2].strip() != "*",
            dow_restricted=parts[4].strip() != "*",
        )


def _parse_field(field: str, min_v: int, max_v: int) -> set:
    """解析 cron 字段：支持 *、数字、逗号列表、区间、/step（含 */n）。"""
    field = (field or "").strip()
    if not field:
        raise ValueError("cron 字段为空")
    if field == "*":
        return set(range(min_v, max_v + 1))

    out: set = set()
    for part in field.split(","):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^(?P<start>\d+|\*)(?:-(?P<end>\d+))?(?:/(?P<step>\d+))?$", part)
        if not m:
            raise ValueError(f"无效 cron 字段: {part}")
        step = int(m.group("step") or 1)
        if step <= 0:
            raise ValueError(f"无效 cron 步长: {part}")
        if m.group("start") == "*":
            start, end = min_v, max_v
        else:
            start = int(m.group("start"))
            end = int(m.group("end") or start)
        for v in range(start, end + 1, step):
            if min_v <= v <= max_v:
                out.add(v)
            elif v == 7 and min_v == 0 and max_v == 7:
                out.add(0)  # 周日 7 归一为 0
    if not out:
        raise ValueError(f"cron 字段无有效取值: {field}")
    return out


def _day_matches(cron: CronExpr, dt: datetime) -> bool:
    """判定某一天是否命中（dom/dow 均受限时取 OR，与 Vixie cron 一致）。"""
    if dt.month not in cron.month:
        return False
    # 标准 cron 的 day_of_week：0=周日；Python weekday() 是 0=周一
    dow = (dt.weekday() + 1) % 7
    dom_ok = dt.day in cron.day_of_month
    dow_ok = dow in cron.day_of_week

    if cron.dom_restricted and cron.dow_restricted:
        return dom_ok or dow_ok
    return dom_ok and dow_ok


def compute_next_run(cron_expr: str, after: Optional[datetime] = None) -> Optional[str]:
    """计算下一次触发时间（ISO 字符串）。

    算法：从候选时刻所在日开始按天推进（最多 4 年 = 1461 次迭代），
    命中日内取第一个不早于候选时刻的 (hour, minute)；不再逐分钟扫描。
    """
    try:
        cron = CronExpr.parse(cron_expr)
    except ValueError as e:
        logger.warning("计算 next_run 失败: %s", e)
        return None

    now = after or datetime.now()
    base = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
    hours = sorted(cron.hour)
    minutes = sorted(cron.minute)

    for day_offset in range(_MAX_SEARCH_DAYS + 1):
        day = (base + timedelta(days=day_offset)).replace(hour=0, minute=0)
        if not _day_matches(cron, day):
            continue
        for h in hours:
            for m in minutes:
                candidate = day.replace(hour=h, minute=m)
                if candidate >= base:
                    return candidate.isoformat()
        # 当天没有更晚的匹配时刻 → 继续下一天
    return None


def validate_cron(expr: str) -> bool:
    try:
        CronExpr.parse(expr)
        return True
    except ValueError:
        return False


def scheduler_enabled() -> bool:
    """是否在本进程启用调度器（多副本部署可只在 1 个副本开启）。"""
    return os.getenv("ENABLE_SCHEDULER", "1").lower() in ("1", "true", "yes")


async def _scheduler_loop(trigger_fn):
    """后台调度循环：每分钟检查一次待触发 schedule。"""
    while True:
        try:
            now_dt = datetime.now()
            now = now_dt.isoformat()
            due = db.get_due_schedules(now)
            for sch in due:
                next_run = compute_next_run(sch["cron_expr"], after=now_dt)
                # 原子抢占：只有当 DB 里的 next_run_at 仍是我们看到的那个值时才归属本进程，
                # 避免多副本重复触发同一个 schedule。
                claimed = db.claim_schedule(sch["id"], sch["next_run_at"], next_run, now)
                if not claimed:
                    logger.info("Schedule %s 已被其它副本抢占，跳过", sch["id"])
                    continue
                try:
                    logger.info("Schedule %s triggered", sch["id"])
                    trigger_fn(sch)
                except Exception as e:
                    # next_run_at 已前移，避免失败后每分钟无限重试打爆下游
                    logger.exception("Schedule %s 触发失败（已跳过本次）: %s", sch["id"], e)
        except Exception as e:
            logger.exception("调度循环异常: %s", e)
        await asyncio.sleep(60)


def start_scheduler(trigger_fn):
    """启动后台调度器（幂等）。"""
    global _SCHEDULER_TASK
    if not scheduler_enabled():
        logger.info("Loop schedule scheduler disabled by ENABLE_SCHEDULER")
        return
    if _SCHEDULER_TASK is not None and not _SCHEDULER_TASK.done():
        return
    _SCHEDULER_TASK = asyncio.create_task(_scheduler_loop(trigger_fn))
    logger.info("Loop schedule scheduler started")


def stop_scheduler():
    global _SCHEDULER_TASK
    if _SCHEDULER_TASK and not _SCHEDULER_TASK.done():
        _SCHEDULER_TASK.cancel()
        _SCHEDULER_TASK = None
