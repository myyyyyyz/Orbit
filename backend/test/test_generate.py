"""generate/ — LLM 生成模块测试（LLM 调用全部 mock）"""
import json

from app.generate import _get_llm_config, generate_answer


def _chunks():
    return [
        {"text": "Orbit 是 AI Agent 端到端系统", "metadata": {"source": "intro.md"}, "score": 0.82},
        {"text": "支持文档上传与语义检索", "metadata": {"source": "feat.md"}, "score": 0.61},
    ]


# ── _get_llm_config ──

def test_llm_config_deepseek_url(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "k")
    _, url, model = _get_llm_config(model="deepseek-chat")
    assert url == "https://api.deepseek.com/v1/chat/completions"
    assert model == "deepseek-chat"


def test_llm_config_claude_url(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "k")
    _, url, _ = _get_llm_config(model="claude-sonnet-4")
    assert url == "https://api.anthropic.com/v1/messages"


def test_llm_config_default_openai_url(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "k")
    _, url, _ = _get_llm_config(model="gpt-4o-mini")
    assert url == "https://api.openai.com/v1/chat/completions"


def test_llm_config_base_url_override(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_BASE_URL", "https://proxy.example.com/v1/chat")
    _, url, _ = _get_llm_config(model="deepseek-chat")
    assert url == "https://proxy.example.com/v1/chat"


def test_llm_config_env_model_default(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "env-key")
    monkeypatch.setenv("LLM_MODEL", "deepseek-chat")
    api_key, url, model = _get_llm_config()
    assert api_key == "env-key"
    assert model == "deepseek-chat"
    assert "deepseek" in url


# ── generate_answer fallback ──

def test_generate_no_api_key_fallback():
    result = generate_answer("Orbit 是什么", _chunks(), api_key=None)
    assert "未配置 LLM_API_KEY" in result["answer"]
    assert "intro.md" in result["answer"]
    assert result["model"] == "fallback (no LLM)"
    assert result["context_count"] == 2
    assert len(result["sources"]) == 2
    assert result["sources"][0]["source"] == "intro.md"


def test_generate_no_key_empty_chunks():
    result = generate_answer("问题", [], api_key=None)
    assert "无结果" in result["answer"]
    assert result["context_count"] == 0


# ── generate_answer LLM 调用 ──

def test_generate_success_with_mock_llm(mock_llm):
    result = generate_answer("Orbit 是什么", _chunks(), model="deepseek-chat", api_key="sk-test")
    assert result["answer"] == "这是 Mock LLM 的回答"
    assert result["model"] == "deepseek-chat"
    assert result["context_count"] == 2
    # 验证请求内容
    req = mock_llm["requests"][0]
    assert "api.deepseek.com" in req["url"]
    assert req["headers"]["Authorization"] == "Bearer sk-test"
    assert req["body"]["model"] == "deepseek-chat"
    assert "stream" not in req["body"]  # 非流式请求不带 stream 字段
    # system prompt 要求引用来源
    assert "来源" in req["body"]["messages"][0]["content"]


def test_generate_api_key_param_overrides_env(mock_llm, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "env-key")
    generate_answer("问题", _chunks(), model="gpt-4o-mini", api_key="param-key")
    assert mock_llm["requests"][0]["headers"]["Authorization"] == "Bearer param-key"


def test_generate_history_truncated_to_last_4(mock_llm):
    history = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"第{i}条"} for i in range(6)]
    generate_answer("问题", _chunks(), model="gpt-4o-mini", api_key="k", history=history)
    messages = mock_llm["requests"][0]["body"]["messages"]
    # system + 最近4条 history + 当前 user = 6
    assert len(messages) == 6
    assert messages[0]["role"] == "system"
    assert messages[1]["content"] == "第2条"  # 最早的第0/1条被截掉
    assert messages[-1]["role"] == "user"


def test_generate_llm_exception_returns_error(monkeypatch):
    def boom(req, timeout=None, **kw):
        raise RuntimeError("连接超时")
    monkeypatch.setattr("urllib.request.urlopen", boom)
    result = generate_answer("问题", _chunks(), model="gpt-4o-mini", api_key="k")
    assert "LLM 调用失败" in result["answer"]
    assert "连接超时" in result["answer"]
    assert result["model"] == "error: gpt-4o-mini"


def test_generate_sources_preview_truncated():
    long_text = "长" * 200
    chunks = [{"text": long_text, "metadata": {"source": "long.md"}, "score": 0.5}]
    result = generate_answer("问题", chunks, api_key=None)
    assert len(result["sources"][0]["preview"]) == 80
