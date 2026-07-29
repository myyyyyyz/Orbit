#!/usr/bin/env python3
"""
Logos 记忆写入器

时间由系统硬控，AI 只需传内容。
用法:
  内容从 stdin 传入:
    echo "markdown 内容..." | python scripts/write.py

  可选参数:
    --start-time HH:MM      对话开始时间（AI 从上下文提取，不可得则用当前时间）
    --project-root PATH     项目根目录，默认当前目录
"""

import sys
import os
import re
import argparse
from datetime import datetime
from pathlib import Path


def get_current_time() -> tuple[str, str, str]:
    """返回 (HH:MM, YYYY-MM-DD, YYYY年MM月DD日)"""
    now = datetime.now()
    time_str = now.strftime("%H:%M")
    date_dash = now.strftime("%Y-%m-%d")
    date_cn = now.strftime("%Y年%m月%d日")
    return time_str, date_dash, date_cn


def build_file_header(date_cn: str, gen_time: str) -> str:
    """生成当日文件头"""
    return f"""# {date_cn}

> 自动生成于 {gen_time} | 由 Logos 驱动

"""


def get_next_n(filepath: Path) -> int:
    """从已有文件读取最大 N，返回 N+1"""
    if not filepath.exists():
        return 1
    content = filepath.read_text(encoding="utf-8")
    matches = re.findall(r"第\s*(\d+)\s*次对话", content)
    if not matches:
        return 1
    return max(int(m) for m in matches) + 1


def write_entry(
    content: str,
    start_time: str,
    project_root: Path,
) -> Path:
    """
    将对话摘要写入当日文件。
    content: 对话摘要的 markdown 正文（不含时间头）
    start_time: 对话开始时间 HH:MM
    """
    end_time, date_dash, date_cn = get_current_time()
    memory_dir = project_root / "logos" / "your-memory"
    memory_dir.mkdir(parents=True, exist_ok=True)

    filepath = memory_dir / f"{date_dash}.md"

    if not filepath.exists():
        header = build_file_header(date_cn, end_time)
        filepath.write_text(header, encoding="utf-8")

    n = get_next_n(filepath)

    # 当开始时间不可知时，用记录时间并标注
    if not start_time:
        start_time = end_time
        time_note = "（开始时间未知，此处为记录时间）"
    else:
        time_note = ""

    entry_header = f"\n---\n\n### {start_time} ~ {end_time} | 第 {n} 次对话\n"
    if time_note:
        entry_header = f"\n---\n\n### {start_time} ~ {end_time} | 第 {n} 次对话 {time_note}\n"

    with open(filepath, "a", encoding="utf-8") as f:
        f.write(entry_header)
        f.write(content)
        if not content.endswith("\n"):
            f.write("\n")

    return filepath


def main():
    parser = argparse.ArgumentParser(
        description="Logos 记忆写入器 - 时间由系统硬控",
    )
    parser.add_argument(
        "--start-time",
        type=str,
        default="",
        help="对话开始时间，格式 HH:MM（AI 从上下文提取；不可得则用当前时间）",
    )
    parser.add_argument(
        "--project-root",
        type=str,
        default=str(Path.cwd()),
        help="项目根目录，默认当前目录",
    )
    args = parser.parse_args()

    # 从 stdin 读取内容
    content = sys.stdin.read().strip()
    if not content:
        print("错误: stdin 内容为空，请传入对话摘要", file=sys.stderr)
        sys.exit(1)

    # 校验 start_time 格式
    start_time = args.start_time
    if start_time and not re.match(r"^\d{2}:\d{2}$", start_time):
        print(f"错误: --start-time 格式错误，应为 HH:MM，收到: {start_time}", file=sys.stderr)
        sys.exit(1)

    project_root = Path(args.project_root)
    if not project_root.exists():
        print(f"错误: 项目根目录不存在: {project_root}", file=sys.stderr)
        sys.exit(1)

    filepath = write_entry(content=content, start_time=start_time, project_root=project_root)
    print(f"已写入: {filepath}")


if __name__ == "__main__":
    main()
