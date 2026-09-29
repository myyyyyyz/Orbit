"""回归测试：默认模型名只能有一个事实源（app.llm.client.DEFAULT_LLM_MODEL）。

背景
----
线上端点是 DeepSeek，但代码里曾有 **6 处**把 OpenAI 的模型名当兜底字面量写死
（router/rules.py、router/llm.py、router/security.py、retrieval/planner.py、
knowledge_agent/executors/vision_utils.py）。而 stream/service.py 的模型优先级是
「前端指定 > 路由选择 > 环境变量」，一旦路由给出建议，就会把 "gpt-4o-mini"
发给 DeepSeek → HTTP 400。

用户侧看到的现象正是：路由阶段卡片显示 `gpt-4o-mini`，随后答案生成失败。

这类"配置来源分叉"靠代码评审很难发现（每个字面量单看都合理），因此：
1. 所有模型名解析统一走 app.llm.client.resolve_model；
2. 用源码扫描锁死"不得再出现第三方模型名字面量"。
"""
import io
import tokenize
from pathlib import Path

import pytest

import app
from app.llm.client import DEFAULT_LLM_MODEL, default_base_url_for, resolve_model
from app.router import MODEL_PRESETS, build_model_presets, local_model_name
from app.router.rules import build_model_presets as _build_presets_direct

# "别家厂商"的模型名。绝大多数情况下不该出现在 app/ 源码里。
_FOREIGN_MODEL_LITERAL = (
    "gpt-4o",
    "gpt-4.1",
    "gpt-5",
    "gpt-3.5",
    "claude-",
    "text-embedding-3",
    "text-davinci",
)

# 允许出现的例外：不是"兜底默认值"，而是按模型名索引的数据表
_ALLOWED_OCCURRENCES = {
    # 模型价格表：dict key 本就是模型名，需要覆盖多家厂商才能估算成本
    "api/usage.py": 4,
}

_MODEL_ENV_KEYS = (
    "LLM_MODEL",
    "LLM_MODEL_FAST",
    "LLM_MODEL_BALANCED",
    "LLM_MODEL_STRONG",
    "LLM_MODEL_LOCAL",
    "LLM_MODEL_VISION",
)


@pytest.fixture
def _clean_model_env(monkeypatch):
    for key in _MODEL_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _code_string_literals(source: str):
    """产出源码中**可执行代码**里的字符串字面量 token（跳过注释与 docstring）。

    跳过 docstring 是必要的 —— 本次修复的说明性注释里就会提到 "gpt-4o-mini"。
    """
    statement_start = (
        tokenize.NEWLINE,
        tokenize.NL,
        tokenize.INDENT,
        tokenize.DEDENT,
    )
    prev_type = tokenize.NEWLINE
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.COMMENT:
            continue
        if tok.type in statement_start:
            prev_type = tok.type
            continue
        if tok.type == tokenize.STRING:
            if prev_type in statement_start:  # 语句起始处的字符串 = docstring
                prev_type = tok.type
                continue
            yield tok
        prev_type = tok.type


# ── 唯一事实源本身 ────────────────────────────────────────────

def test_default_llm_model_matches_deployment_provider():
    """唯一事实源必须与 .env.example / compose 的默认端点同厂商"""
    assert DEFAULT_LLM_MODEL == "deepseek-chat"
    assert "deepseek" in default_base_url_for(DEFAULT_LLM_MODEL)


def test_resolve_model_falls_back_to_default(_clean_model_env):
    assert resolve_model("LLM_MODEL_FAST") == DEFAULT_LLM_MODEL
    assert resolve_model("LLM_MODEL_VISION", "LLM_MODEL_FAST") == DEFAULT_LLM_MODEL
    assert resolve_model() == DEFAULT_LLM_MODEL


def test_resolve_model_prefers_first_non_empty_key(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "deepseek-chat")
    monkeypatch.setenv("LLM_MODEL_FAST", "deepseek-chat")
    monkeypatch.setenv("LLM_MODEL_VISION", "deepseek-vl")
    assert resolve_model("LLM_MODEL_VISION", "LLM_MODEL_FAST") == "deepseek-vl"
    assert resolve_model("LLM_MODEL_FAST") == "deepseek-chat"
    # 空字符串视同未配置（compose 会把未设置的变量传成空串）
    monkeypatch.setenv("LLM_MODEL_VISION", "")
    assert resolve_model("LLM_MODEL_VISION", "LLM_MODEL_FAST") == "deepseek-chat"


def test_resolve_model_falls_back_to_main_model(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "deepseek-reasoner")
    assert resolve_model("LLM_MODEL_VISION") == "deepseek-reasoner"


# ── 调用方：各处的兜底值 ──────────────────────────────────────

def test_model_presets_fall_back_to_default_llm_model(_clean_model_env):
    """未配置 LLM_MODEL_* 时，所有档位必须等于 DEFAULT_LLM_MODEL"""
    presets = build_model_presets()
    for tier in ("fast", "balanced", "strong", "unknown", "out_of_scope"):
        assert presets[tier]["model"] == DEFAULT_LLM_MODEL, tier


def test_model_presets_honour_explicit_overrides(monkeypatch):
    """显式配置 LLM_MODEL_* 时按配置分档（保留成本分级能力）"""
    monkeypatch.setenv("LLM_MODEL_FAST", "deepseek-chat")
    monkeypatch.setenv("LLM_MODEL_STRONG", "deepseek-reasoner")
    presets = build_model_presets()
    assert presets["fast"]["model"] == "deepseek-chat"
    assert presets["strong"]["model"] == "deepseek-reasoner"
    assert presets["unknown"]["model"] == "deepseek-chat"  # 沿用 fast
    assert presets["out_of_scope"]["model"] == "deepseek-chat"


def test_module_level_presets_are_consistent():
    """模块级表格与工厂函数结果一致（/api/v1/knowledge/performance 直接返回它）"""
    assert MODEL_PRESETS == _build_presets_direct()


def test_local_model_name_falls_back_to_default(_clean_model_env):
    """PII 锁定用的模型名同样不能写死第三方模型"""
    assert local_model_name() == DEFAULT_LLM_MODEL


def test_local_model_name_priority(monkeypatch):
    monkeypatch.setenv("LLM_MODEL_LOCAL", "deepseek-chat")
    monkeypatch.setenv("LLM_MODEL_FAST", "deepseek-reasoner")
    assert local_model_name() == "deepseek-chat"
    monkeypatch.delenv("LLM_MODEL_LOCAL")
    assert local_model_name() == "deepseek-reasoner"


def test_route_model_never_suggests_foreign_model(_clean_model_env, monkeypatch):
    """端到端：路由对任意输入给出的模型名都必须与端点同厂商。

    语义/LLM 两层打桩，避免为了跑路由而加载 embedding 模型。
    """
    from app.router import route_model
    from app.router import service as router_service

    monkeypatch.setattr(router_service, "_semantic_classify", lambda q: (None, 0.0, ""))
    monkeypatch.setattr(
        router_service, "_llm_classify", lambda q: ("balanced", 0.5, "balanced")
    )
    monkeypatch.setattr(
        router_service, "_hybrid_confidence", lambda q, intent, conf: (conf, False)
    )

    for query in ("你好", "什么是向量数据库", "帮我写一个 Dockerfile", "今天天气怎么样"):
        decision = route_model(query, [])
        assert decision.model == DEFAULT_LLM_MODEL, (query, decision.model)


# ── 静态扫描：防止字面量回流 ──────────────────────────────────

def test_no_hardcoded_foreign_model_names_in_app_source():
    """源码扫描：app/ 下不得再出现别家厂商模型名作为兜底值。

    这是本次线上 400 的根因（6 处字面量），用静态扫描锁死，避免再次回流。
    """
    app_root = Path(app.__file__).parent
    found: dict[str, list[str]] = {}
    for path in sorted(app_root.rglob("*.py")):
        rel = str(path.relative_to(app_root))
        occurrences = [
            f"{rel}:{tok.start[0]} {tok.string}"
            for tok in _code_string_literals(path.read_text(encoding="utf-8"))
            if any(name in tok.string for name in _FOREIGN_MODEL_LITERAL)
        ]
        if occurrences:
            found[rel] = occurrences

    unexpected = {
        rel: occ
        for rel, occ in found.items()
        if len(occ) != _ALLOWED_OCCURRENCES.get(rel, 0)
    }
    assert not unexpected, (
        "发现硬编码的境外模型名，请改用 app.llm.client.resolve_model：\n  "
        + "\n  ".join(f"{rel}: {occ}" for rel, occ in unexpected.items())
    )
