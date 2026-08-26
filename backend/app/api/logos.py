"""Logos 对话总结路由: /api/knowledge/logos

职责:
1. 对话结束后触发 LLM 压缩总结，写入 data/memory/YYYY-MM-DD.md（人机双读）
2. 同时产出结构化 key_points，落库 conversation_summary（供上下文恢复注入 LLM）
"""
import os
import json
import re
import urllib.request
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Body, Depends, HTTPException

from ..config import settings
from ..middleware.auth import get_optional_user
from ..memory import save_conversation_summary

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/knowledge", tags=["logos"])

KEY_POINTS_MAX = 10  # key_points 上限


def _extract_key_points(text: str) -> list:
    """从 LLM 输出中提取 KEY_POINTS: [...] 行，解析为字符串列表。

    容错设计:
    - 找不到标记 / JSON 解析失败 → 返回 []（不影响主功能，写入 md 的内容保持原样）
    - 只取前 KEY_POINTS_MAX 条，防止 LLM 输出超长列表
    """
    if not text:
        return []
    m = re.search(r"KEY_POINTS:\s*(\[[^\]]*\])", text, re.IGNORECASE)
    if not m:
        return []
    try:
        pts = json.loads(m.group(1))
        cleaned = [str(p).strip() for p in pts if str(p).strip()]
        return cleaned[:KEY_POINTS_MAX]
    except Exception:
        return []


@router.post("/logos")
def api_logos_summarize(body: dict = Body(...), current_user: Optional[dict] = Depends(get_optional_user)):
    """对话结束后触发 Logos 总结，写入 data/memory/YYYY-MM-DD.md + 落库 conversation_summary"""
    conversation = body.get("conversation", "").strip()
    if not conversation:
        raise HTTPException(400, "对话内容不能为空")

    start_time = body.get("start_time", datetime.now().strftime("%H:%M"))

    # 如果有 LLM API Key，用 LLM 生成总结
    api_key = os.getenv("LLM_API_KEY", "")
    if api_key:
        from ..llm import get_llm_config
        _, base_url, model = get_llm_config()
        system_prompt = (
            "你是 Logos 记忆管家。请将以下对话总结为结构化笔记，重点记录："
            "1. 做了什么 2. 关键决策 3. 遇到的问题 4. 灵感收获 5. 待办事项。"
            "用 Markdown 输出。\n"
            "输出末尾单独加一行，把最重要的要点提炼为 JSON 数组，格式："
            'KEY_POINTS: ["要点1", "要点2", "要点3"]（不要放在代码块里）'
        )
        payload = json.dumps({
            "model": model,
            "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": conversation}],
            "temperature": 0.3,
            "max_tokens": 800,
        }).encode()
        req = urllib.request.Request(
            base_url, data=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
                summary = result["choices"][0]["message"]["content"]
        except Exception:
            summary = f"### 对话总结（LLM 不可用）\n\n{conversation[:500]}"
    else:
        summary = f"### 对话总结（无 LLM）\n\n{conversation[:500]}"

    # 产出结构化 key_points（降级路径：无 LLM / 解析失败 → 空列表）
    key_points = _extract_key_points(summary)

    # 落库 conversation_summary（有登录用户时；匿名会话只写文件）
    user_id = current_user["user_id"] if current_user else None
    if user_id:
        try:
            save_conversation_summary(user_id, summary, key_points)
        except Exception as e:
            logger.warning("conversation_summary 落库失败: %s", e)

    # 写入 data/memory/YYYY-MM-DD.md
    memory_dir = Path(settings.UPLOAD_DIR).parent / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    now = datetime.now().strftime("%H:%M:%S")
    memory_file = memory_dir / f"{today}.md"

    header = f"### {start_time} ~ {now[:5]} | 第 1 次对话\n\n"

    if memory_file.exists():
        existing = memory_file.read_text(encoding="utf-8")
        count = len(re.findall(r"第 \d+ 次对话", existing)) + 1
        header = f"### {start_time} ~ {now[:5]} | 第 {count} 次对话\n\n"
        with open(memory_file, "a", encoding="utf-8") as f:
            f.write("\n---\n\n" + header + summary + "\n")
    else:
        with open(memory_file, "w", encoding="utf-8") as f:
            f.write(f"# 知识库对话记录 — {today}\n\n" + header + summary + "\n")

    return {
        "status": "ok",
        "file": str(memory_file),
        "summary_length": len(summary),
        "key_points": key_points,
        "key_points_count": len(key_points),
        "saved_to_memory_db": user_id is not None,
        "message": f"已写入 {memory_file.name}",
    }
