"""可逆副作用（P1）：Builder 落盘的结构化 effect 记录与精确回滚。

借鉴 deepseek-harness 的"可逆副作用"设计：每次落盘不仅写文件，还记录
"改了什么、原文是什么"，使 checkpoint 的"回退"决策可以做到文件级精确回滚，
而不是只能整体丢弃 worktree / git stash。

安全设计（安全规则 #6 路径穿越防护）:
- 所有路径必须位于 target 目录内（commonpath 校验）。
- original_content 在写入前从磁盘读取，作为回滚依据。
- revert_effects 只恢复本模块记录过的文件，绝不触碰其他文件。
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class EffectRecord:
    """单个文件的副作用记录（可逆单元）。"""

    path: str            # 相对 target 的路径
    action: str          # create | modify | delete
    original_content: str = ""  # 落盘前磁盘原文（delete 场景也保存，用于恢复）
    content: str = ""    # 新内容（delete 场景为空）
    applied: bool = False

    def to_dict(self) -> dict:
        return {
            "path": self.path, "action": self.action,
            "original_content": self.original_content, "content": self.content,
            "applied": self.applied,
        }


def _safe_join(target: str, rel_path: str) -> Optional[str]:
    """路径穿越防护：返回 target 内的绝对路径，越界返回 None。"""
    if not rel_path or ".." in rel_path.split("/") or rel_path.startswith("/"):
        return None
    abs_path = os.path.realpath(os.path.join(target, rel_path))
    if os.path.commonpath([target, abs_path]) != target:
        return None
    return abs_path


def apply_build_files(build_files: list[dict], target: str) -> dict:
    """把 Builder 的 changed_files 落盘，同时记录 effects。

    返回: {effects: [EffectRecord.to_dict()], applied: int, skipped: int}
    安全：路径穿越的文件跳过；落盘失败的文件 marked applied=False。
    """
    os.makedirs(target, exist_ok=True)
    effects: list[EffectRecord] = []
    applied, skipped = 0, 0

    for f in build_files or []:
        path = f.get("path", "")
        action = f.get("action", "modify")
        content = f.get("content", "")

        abs_path = _safe_join(target, path)
        if abs_path is None:
            skipped += 1
            continue

        # 记录原文（回滚依据）
        original = ""
        if os.path.exists(abs_path):
            try:
                with open(abs_path, "r", encoding="utf-8", errors="replace") as fp:
                    original = fp.read()
            except OSError as e:
                logger.warning("读取原文失败 %s: %s", path, e)

        eff = EffectRecord(
            path=path, action=action,
            original_content=original, content=content, applied=False,
        )
        try:
            if action == "delete":
                if os.path.exists(abs_path):
                    os.remove(abs_path)
            else:
                os.makedirs(os.path.dirname(abs_path), exist_ok=True)
                with open(abs_path, "w", encoding="utf-8") as fp:
                    fp.write(content)
            eff.applied = True
            applied += 1
        except OSError as e:
            logger.warning("落盘失败 %s: %s", path, e)
            skipped += 1

        effects.append(eff)

    return {"effects": [e.to_dict() for e in effects], "applied": applied, "skipped": skipped}


def revert_effects(effects: list[dict], target: str) -> dict:
    """按 effect 记录精确回滚（只恢复本模块记录过的文件）。

    - create  → 删除该文件
    - modify  → 恢复 original_content
    - delete  → 恢复 original_content（重新创建）

    返回: {reverted: int, failed: list[dict]}
    """
    reverted, failed = 0, []
    for eff in effects or []:
        path = eff.get("path", "")
        action = eff.get("action", "modify")
        original = eff.get("original_content", "")

        abs_path = _safe_join(target, path)
        if abs_path is None:
            failed.append({"path": path, "reason": "路径越界，拒绝回滚"})
            continue

        try:
            if action == "create":
                # 新创建的文件：删除
                if os.path.exists(abs_path):
                    os.remove(abs_path)
            else:
                # modify / delete：恢复原文（重新创建或覆写）
                if original == "" and not os.path.exists(abs_path):
                    # 原文件本不存在（空原文 + 不存在）→ 视为 create，删除
                    if os.path.exists(abs_path):
                        os.remove(abs_path)
                else:
                    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
                    with open(abs_path, "w", encoding="utf-8") as fp:
                        fp.write(original)
            reverted += 1
        except OSError as e:
            logger.warning("回滚失败 %s: %s", path, e)
            failed.append({"path": path, "reason": str(e)})

    return {"reverted": reverted, "failed": failed}
