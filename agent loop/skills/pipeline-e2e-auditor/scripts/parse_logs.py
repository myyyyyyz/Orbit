"""Scan reports directory and extract error/warning timeline per task."""
import sys
import json
import re
from pathlib import Path
from datetime import datetime


PATTERNS = {
    "error": re.compile(r"(ERROR|CRITICAL|FATAL|Traceback)", re.IGNORECASE),
    "warning": re.compile(r"WARNING|WARN", re.IGNORECASE),
    "success": re.compile(r"(done|finished|completed|通过数|成功)", re.IGNORECASE),
}


def parse_log_file(filepath: Path) -> dict:
    """Extract key lines from a single log file."""
    errors: list[str] = []
    warnings: list[str] = []
    last_success: str = ""
    line_count = 0

    try:
        with open(filepath, encoding="utf-8", errors="ignore") as f:
            for line in f:
                line_count += 1
                line = line.rstrip()
                if PATTERNS["error"].search(line):
                    errors.append(line)
                elif PATTERNS["warning"].search(line):
                    warnings.append(line)
                if PATTERNS["success"].search(line):
                    last_success = line
    except OSError:
        return {"file": str(filepath), "error": "cannot_read"}

    return {
        "file": str(filepath),
        "total_lines": line_count,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors[-20:],  # tail 20
        "warnings": warnings[-10:],
        "last_success_marker": last_success,
        "has_ending": any(
            "done" in line.lower() or "finished" in line.lower()
            for line in errors[-5:] + [last_success]
        ),
    }


def scan_reports(reports_dir: str) -> list[dict]:
    """Scan all log files under reports directory, organized by task_id."""
    results: list[dict] = []
    base = Path(reports_dir)

    if not base.exists():
        return [{"error": f"reports directory not found: {reports_dir}"}]

    for log_file in sorted(base.rglob("*.log")):
        task_id = log_file.parent.name if log_file.parent != base else "root"
        parsed = parse_log_file(log_file)
        parsed["task_id"] = task_id
        results.append(parsed)

    return results


if __name__ == "__main__":
    reports_dir = sys.argv[1] if len(sys.argv) > 1 else "reports"
    results = scan_reports(reports_dir)
    print(json.dumps(results, ensure_ascii=False, indent=2))

    total_errors = sum(r.get("error_count", 0) for r in results)
    total_warnings = sum(r.get("warning_count", 0) for r in results)
    if total_errors > 0:
        print(f"\n[FAIL] 共发现 {total_errors} 条 ERROR，{total_warnings} 条 WARNING", file=sys.stderr)
    else:
        print(f"\n[OK] 无 ERROR，{total_warnings} 条 WARNING", file=sys.stderr)
