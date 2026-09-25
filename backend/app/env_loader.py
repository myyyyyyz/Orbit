"""环境变量加载：让本地 `python -m uvicorn` 也能读到项目根目录的 `.env`。

历史缺陷：全仓没有任何 dotenv 加载，只有 docker-compose 会消费 `.env`。
而 `.env.example` 明确写着"复制为 .env 后填入真实值 / 服务启动会校验 LLM_API_KEY"，
照做的人一本地启动就必然失败（强校验拿不到 key，直接 sys.exit(1)）。

设计要点：
- 幂等：重复调用只生效一次。
- 不覆盖已存在的真实环境变量（容器编排 / K8s 注入的优先级高于 .env 文件）。
- 优雅降级：未安装 python-dotenv 时用内置的最小解析器，保证 `.env` 始终生效。
"""

import logging
import os
import sys
from typing import Optional

logger = logging.getLogger(__name__)

_loaded = False

# `.env` 查找顺序（只读，绝不写回）
# 1) 显式 ENV_FILE  2) 当前工作目录  3) backend/  4) 项目根目录
def _candidate_paths() -> list[str]:
    here = os.path.dirname(os.path.abspath(__file__))          # backend/app
    backend_dir = os.path.dirname(here)                        # backend
    project_root = os.path.dirname(backend_dir)                # repo root
    paths = []
    explicit = os.getenv("ENV_FILE")
    if explicit:
        paths.append(explicit)
    paths += [
        os.path.join(os.getcwd(), ".env"),
        os.path.join(backend_dir, ".env"),
        os.path.join(project_root, ".env"),
    ]
    return paths


def _parse_dotenv_minimal(path: str) -> dict:
    """最小 .env 解析：KEY=VALUE，忽略注释与空行，去除成对引号。

    不支持变量插值——这是刻意的，避免与真实 dotenv 行为产生细微差异。
    """
    values: dict = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                if line.startswith("export "):
                    line = line[len("export "):]
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                    value = value[1:-1]
                if key:
                    values[key] = value
    except OSError:
        pass
    return values


def load_env(force: bool = False) -> Optional[str]:
    """加载 `.env`。返回实际加载的文件路径，未找到返回 None。"""
    global _loaded
    if _loaded and not force:
        return None

    for path in _candidate_paths():
        if not path or not os.path.isfile(path):
            continue

        loaded_via = "dotenv"
        try:
            from dotenv import load_dotenv

            load_dotenv(path, override=False)
        except ImportError:
            loaded_via = "builtin"
            for key, value in _parse_dotenv_minimal(path).items():
                os.environ.setdefault(key, value)
        except Exception as e:  # 文件不可读等
            logger.warning("dotenv 加载失败 %s: %s", path, e)
            continue

        _loaded = True
        print(f"[env] 已加载环境变量文件: {path} (via {loaded_via})", file=sys.stderr)
        return path

    _loaded = True
    return None
