"""安全门控：路径 Denylist 与命令白名单的机械执行。

每次 Builder 落盘前和 loop 启动时执行机械检查，不依赖 LLM（双重防护）。
gate.yaml 是机器可读配置，loop 运行时自动加载。

设计要点:
- LoopGate 是单例，一次加载后缓存整个 loop 生命周期。
- check_path() 支持 glob 模式匹配（fnmatch）。
- check_build() 批量检查 BuildOutput 的所有 changed_files。
- check_command() 验证命令是否在 allowed_commands 白名单内。
"""

import logging
import os
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

# 内嵌默认 gate 配置（gate.yaml 缺失时回退）
DEFAULT_GATE_YAML = """
# gate.yaml — 机器可读，机械执行
# Agent loop 每次运行前必须读取并遵守
denylist:
  - .env
  - .env.*
  - .env.local
  - .env.production
  - "**/secrets/**"
  - "**/credentials/**"
  - "**/certs/**"
  - "**/*.pem"
  - "**/*-key.json"
  - "**/serviceAccount.json"
  - "**/payments/**"
  - "**/billing/**"
  - "**/terraform/**"
  - "**/*.tfstate"
  - "**/infrastructure/**"
  - ".github/workflows/*-deploy*"
  - "**/deploy.yml"
  - "**/migrations/**"

enforcement: reject

on_hit:
  action: abort_immediately
  notify: true
  escalate_after: 24h

allowed_commands:
  - "python -m pytest"
  - "python3 -m pytest"
  - "npm test"
  - "npm run test"
  - "npm run lint"
  - "go test"
  - "cargo test"
  - "make test"
  - "pytest"
  - "eslint"
  - "mypy"
  - "ruff check"
  - "black --check"
  - "prettier --check"
  - "python -h"
  - "python3 -h"
  - "python -c"
  - "python3 -c"
  - "node -e"
  - "node --version"
  - "npm --version"
  - "echo"
  - "cat"
  - "ls"
  - "grep"
  - "find"
  - "wc"
  - "head"
  - "tail"
  - "diff"
  - "git status"
  - "git diff"
  - "git log"
  - "date"
  - "pwd"

auto_merge_allowlist:
  only_if:
    - change_type_is: ["typo", "lint_fix", "import_sort", "comment_fix", "doc_update"]
    - not_in_denylist: true
    - all_tests_pass: true

test_levels:
  skip:
    require_verification: false
    require_test: false
    allowed_prefixes: []
  smoke:
    require_verification: true
    require_test: false
    allowed_prefixes:
      - "python3 -m pytest"
      - "python -m pytest"
      - "pytest"
      - "npm run lint"
      - "npm run test"
      - "eslint"
      - "mypy"
      - "ruff check"
      - "black --check"
      - "prettier --check"
  full:
    require_verification: true
    require_test: true
    allowed_prefixes:
      - "python3 -m pytest"
      - "python -m pytest"
      - "pytest"
      - "npm test"
      - "npm run test"
      - "go test"
      - "cargo test"
      - "make test"
"""


@dataclass
class GateResult:
    """单次门控检查结果。"""

    passed: bool
    hits: list[dict] = field(default_factory=list)  # [{path, pattern, rule}]
    warnings: list[str] = field(default_factory=list)
    abort: bool = False


class LoopGate:
    """安全门控。"""

    def __init__(self, project_dir: str):
        self.project_dir = os.path.realpath(project_dir) if project_dir else ""
        self.denylist: list[str] = []
        self.allowed_commands: list[str] = []
        self.enforcement: str = "reject"
        self.on_hit: dict = {}
        self._loaded = False

    def load(self):
        """加载 gate.yaml（项目级优先，全局默认兜底）。"""
        if self._loaded:
            return

        yaml_path = None
        if self.project_dir:
            candidate = os.path.join(self.project_dir, "gate.yaml")
            if os.path.exists(candidate):
                yaml_path = candidate

        if yaml_path:
            try:
                with open(yaml_path, "r", encoding="utf-8") as f:
                    config = yaml.safe_load(f) or {}
                logger.info("Gate 配置加载: %s", yaml_path)
            except Exception as e:
                logger.warning("gate.yaml 解析失败 (%s)，回退默认配置: %s", yaml_path, e)
                config = yaml.safe_load(DEFAULT_GATE_YAML) or {}
        else:
            config = yaml.safe_load(DEFAULT_GATE_YAML) or {}
            logger.info("Gate 使用内嵌默认配置（未找到 gate.yaml）")

        self.denylist = config.get("denylist", [])
        self.allowed_commands = config.get("allowed_commands", [])
        self.enforcement = config.get("enforcement", "reject")
        self.on_hit = config.get("on_hit", {})
        self.test_levels = config.get("test_levels", {}) or {}
        self._loaded = True

    def check_path(self, file_path: str) -> GateResult:
        """检查单个文件路径是否命中 denylist。

        返回 GateResult，passed=True 表示安全。
        """
        self.load()
        hits = []
        for pattern in self.denylist:
            # 支持 **/xxx 模式
            if fnmatch(file_path, pattern):
                hits.append({"path": file_path, "pattern": pattern, "rule": "denylist"})
            # 也检查完整路径匹配（处理 **/secrets/** 这类带目录的模式）
            elif "**" in pattern:
                clean = pattern.replace("**/", "").replace("**", "")
                if clean and clean in file_path:
                    hits.append({"path": file_path, "pattern": pattern, "rule": "denylist"})

        result = GateResult(
            passed=len(hits) == 0,
            hits=hits,
            abort=self.enforcement == "reject" and len(hits) > 0,
        )

        if not result.passed:
            logger.warning("Gate 命中 denylist: %s matched %s", file_path, [h["pattern"] for h in hits])

        return result

    def check_build(self, changed_files: list[dict]) -> GateResult:
        """批量检查 Builder 输出的所有 changed_files。

        返回 GateResult，passed=True 表示全部安全。
        """
        all_hits = []
        for f in changed_files:
            path = f.get("path", "")
            if path:
                r = self.check_path(path)
                all_hits.extend(r.hits)

        abort = self.enforcement == "reject" and len(all_hits) > 0
        action = self.on_hit.get("action", "abort_immediately") if all_hits else "pass"

        return GateResult(
            passed=len(all_hits) == 0,
            hits=all_hits,
            abort=abort,
            warnings=[f"on_hit action={action}"] if abort else [],
        )

    def check_command(self, command: str) -> bool:
        """检查命令是否在允许列表内（前缀匹配）。"""
        self.load()
        cmd = command.strip()
        if not cmd:
            return True
        for allowed in self.allowed_commands:
            if cmd.startswith(allowed):
                return True
        return False

    # ── P3: 测试分层校验 ──────────────────────────────────────────

    _TEST_CMD_PREFIXES = (
        "pytest", "go test", "cargo test", "npm test", "npm run test",
        "make test", "python3 -m pytest", "python -m pytest",
    )

    def check_verification(self, commands: list[str], test_level: str) -> GateResult:
        """按 test_level 校验 Builder 验证命令的充分性（不阻止执行，只产出证据）。

        test_level 定义（gate.yaml test_levels）:
        - skip:  免测，不要求验证命令
        - smoke: 至少 1 条验证命令（lint/单测均可）
        - full:  至少 1 条测试命令（pytest/go test/npm test 等）

        返回 GateResult：
        - passed=False 表示验证深度不足（供 Reviewer 作为证据，不 abort）
        - warnings 携带具体缺失原因
        """
        self.load()
        if not commands:
            commands = []

        level_cfg = self.test_levels.get(test_level, {}) if test_level else {}
        require_verification = level_cfg.get("require_verification", test_level in ("smoke", "full"))
        require_test = level_cfg.get("require_test", test_level == "full")
        allowed_prefixes = level_cfg.get("allowed_prefixes", []) or []

        warnings: list[str] = []
        has_any = len(commands) > 0
        has_test = any(
            c.strip().startswith(p) for c in commands for p in self._TEST_CMD_PREFIXES
        )

        if require_verification and not has_any:
            warnings.append(f"test_level={test_level} 要求至少 1 条验证命令，但 Builder 未提供")
        if require_test and not has_test:
            warnings.append(f"test_level={test_level} 要求测试命令（{'/'.join(self._TEST_CMD_PREFIXES)}），但 Builder 未提供")
        if allowed_prefixes and commands:
            for c in commands:
                if not any(c.strip().startswith(p) for p in allowed_prefixes):
                    warnings.append(
                        f"验证命令 '{c.strip()}' 超出 test_level={test_level} 允许范围 "
                        f"(allowed: {' | '.join(allowed_prefixes[:5])}...)"
                    )

        return GateResult(passed=len(warnings) == 0, hits=[], warnings=warnings, abort=False)


def load_gate(project_dir: str) -> LoopGate:
    """工厂函数：创建并加载 gate。"""
    gate = LoopGate(project_dir)
    gate.load()
    return gate


def check_build_against_gate(build_files: list[dict], project_dir: str) -> GateResult:
    """便捷函数：一键检查 Builder 输出。"""
    gate = LoopGate(project_dir)
    return gate.check_build(build_files)
