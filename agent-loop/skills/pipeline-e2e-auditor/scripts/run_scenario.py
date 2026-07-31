"""Run a single evaluation scenario with --limit and collect results."""
import subprocess
import sys
import time
import json
from pathlib import Path


def run_scenario(script_path: str, limit: int = 3, timeout: int = 600) -> dict:
    """Run a scenario script and return structured result."""
    cmd = [sys.executable, script_path, "--limit", str(limit)]
    start = time.time()

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {
            "script": script_path,
            "status": "timeout",
            "returncode": None,
            "duration_seconds": timeout,
            "stdout_tail": "",
            "stderr_tail": "",
        }

    stdout_tail = "\n".join(result.stdout.split("\n")[-20:])
    stderr_tail = "\n".join(result.stderr.split("\n")[-20:])

    return {
        "script": script_path,
        "status": "ok" if result.returncode == 0 else "failed",
        "returncode": result.returncode,
        "duration_seconds": round(time.time() - start, 2),
        "stdout_tail": stdout_tail,
        "stderr_tail": stderr_tail,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run_scenario.py <script_path> [--limit N] [--timeout S]", file=sys.stderr)
        sys.exit(1)

    script_path = sys.argv[1]
    limit = 3
    timeout = 600

    i = 2
    while i < len(sys.argv):
        if sys.argv[i] == "--limit" and i + 1 < len(sys.argv):
            limit = int(sys.argv[i + 1])
            i += 2
        elif sys.argv[i] == "--timeout" and i + 1 < len(sys.argv):
            timeout = int(sys.argv[i + 1])
            i += 2
        else:
            i += 1

    result = run_scenario(script_path, limit=limit, timeout=timeout)
    print(json.dumps(result, ensure_ascii=False, indent=2))
