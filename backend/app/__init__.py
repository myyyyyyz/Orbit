"""Orbit 后端应用包。

在包导入的最早期加载 `.env`：本包内多个模块（config / llm.retry / middleware.auth）
在 **导入时** 就读取环境变量，晚于此处的加载不会有任何效果。
"""

from .env_loader import load_env

load_env()
