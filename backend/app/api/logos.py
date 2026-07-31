"""Logos 对话总结路由: /api/knowledge/logos"""
import os
import json
import re
import urllib.request
import logging
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, Body, HTTPException

from ..config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/knowledge", tags=["logos"])


@router.post("/logos")
def api_logos_summarize(body: dict = Body(...)):
    """对话结束后触发 Logos 总结，写入 data/memory/YYYY-MM-DD.md"""
    conversation = body.get("conversation", "").strip()
    if not conversation:
        raise HTTPException(400, "对话内容不能为空")

    start_time = body.get("start_time", datetime.now().strftime("%H:%M"))

    # 如果有 LLM API Key，用 LLM 生成总结
    api_key = os.getenv("LLM_API_KEY", "")
    if api_key:
        from ..generate import _get_llm_config
        _, base_url, model = _get_llm_config()
        system_prompt = "你是 Logos 记忆管家。请将以下对话总结为结构化笔记，重点记录：1. 做了什么 2. 关键决策 3. 遇到的问题 4. 灵感收获 5. 待办事项。用 Markdown 输出。"
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

    return {"status": "ok", "file": str(memory_file), "summary_length": len(summary), "message": f"已写入 {memory_file.name}"}
