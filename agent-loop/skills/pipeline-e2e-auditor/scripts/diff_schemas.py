"""Compare frontend request/response shapes with backend interface definitions."""
import json
import sys
from typing import Any


def flatten_keys(obj: Any, prefix: str = "") -> set[str]:
    """Flatten a JSON-like object into a set of dot-notation keys."""
    keys: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            full_key = f"{prefix}.{k}" if prefix else k
            keys.add(full_key)
            keys.update(flatten_keys(v, full_key))
    elif isinstance(obj, list) and obj:
        keys.update(flatten_keys(obj[0], f"{prefix}[]"))
    return keys


def diff(frontend_schema: dict, backend_schema: dict) -> dict:
    """Compare two schemas and report differences."""
    fe_keys = flatten_keys(frontend_schema)
    be_keys = flatten_keys(backend_schema)

    return {
        "frontend_only_keys": sorted(fe_keys - be_keys),
        "backend_only_keys": sorted(be_keys - fe_keys),
        "shared_keys": sorted(fe_keys & be_keys),
        "summary": {
            "frontend_total": len(fe_keys),
            "backend_total": len(be_keys),
            "shared": len(fe_keys & be_keys),
            "frontend_extra": len(fe_keys - be_keys),
            "backend_extra": len(be_keys - fe_keys),
        },
    }


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(
            "Usage: python diff_schemas.py <frontend_sample.json> <backend_definition.json>",
            file=sys.stderr,
        )
        sys.exit(1)

    with open(sys.argv[1], encoding="utf-8") as f:
        fe = json.load(f)
    with open(sys.argv[2], encoding="utf-8") as f:
        be = json.load(f)

    result = diff(fe, be)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if result["summary"]["frontend_extra"] > 0:
        print(f"\n[WARN] 前端多发 {result['summary']['frontend_extra']} 个字段", file=sys.stderr)
    if result["summary"]["backend_extra"] > 0:
        print(f"\n[WARN] 后端多返 {result['summary']['backend_extra']} 个字段（前端未使用）", file=sys.stderr)
