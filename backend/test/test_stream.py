"""stream/ — SSE 流式问答模块测试（检索规划/路由/LLM 全部 mock）"""
import json

import pytest

import app.stream.service as stream_mod  # patch 目标：stream_ask 定义所在模块
from app.stream import stream_ask, _sse, MIN_RELEVANCE_SCORE  # 验证 __init__ 再导出兼容
from app.retrieval import RetrievalPlan
from app.router import RouteDecision


@pytest.fixture(autouse=True)
def _stable_cache_namespace(monkeypatch):
    """缓存命名空间依赖活跃索引版本；测试里固定住，避免触库/触向量库。"""
    class _V:
        collection_name = "test_collection"
    monkeypatch.setattr(stream_mod, "resolve_active_version", lambda uid: _V())


def _parse_sse(raw_events):
    """把生成器输出的 SSE 字符串解析为 [(event, data), ...]"""
    parsed = []
    for raw in raw_events:
        lines = raw.strip().split("\n")
        event = lines[0].replace("event: ", "")
        data = json.loads(lines[1].replace("data: ", ""))
        parsed.append((event, data))
    return parsed


def _fake_route(model="gpt-4o-mini"):
    return RouteDecision(tier="fast", model=model, max_tokens=500, temperature=0.3, confidence=0.85)


def _mock_pipeline(monkeypatch, chunks, retrieve=True):
    """mock 检索规划与执行，cache 不命中。

    阈值过滤现在发生在检索执行层（retrieval planner），因此这里直接把
    「已过滤后的 chunk 列表」交给 execute_retrieval_plan 的返回值。
    """
    monkeypatch.setattr(stream_mod, "cache_get", lambda q, **kw: None)
    monkeypatch.setattr(stream_mod, "cache_put", lambda *a, **k: None)
    monkeypatch.setattr(
        stream_mod, "plan_retrieval",
        lambda q, user_id=None, api_key=None: RetrievalPlan(
            retrieve=retrieve, strategy="vector", top_k=5, threshold=MIN_RELEVANCE_SCORE,
        ),
    )
    monkeypatch.setattr(stream_mod, "execute_retrieval_plan", lambda q, user_id=None, plan=None, api_key=None: chunks)
    monkeypatch.setattr(stream_mod, "route_model", lambda q, s: _fake_route())


GOOD_CHUNK = {"text": "Orbit 是 AI Agent 端到端系统", "metadata": {"source": "intro.md"}, "score": 0.85}
NOISE_CHUNK = {"text": "完全无关的文档内容", "metadata": {"source": "noise.md"}, "score": 0.10}


# ── _sse ──

def test_sse_format():
    raw = _sse("token", {"text": "你好"})
    assert raw.startswith("event: token\n")
    assert raw.endswith("\n\n")
    assert json.loads(raw.split("data: ", 1)[1]) == {"text": "你好"}


def test_sse_chinese_not_escaped():
    raw = _sse("answer", {"text": "中文内容"})
    assert "中文内容" in raw  # ensure_ascii=False


# ── 缓存分支 ──

def test_cache_hit_short_circuits(monkeypatch):
    monkeypatch.setattr(stream_mod, "cache_get", lambda q, **kw: {
        "answer": "缓存答案", "sources": [{"source": "a.md"}], "cache_hit_score": 0.99,
    })
    events = _parse_sse(list(stream_ask("已缓存的问题")))
    stages = [e for e, _ in events]
    assert "cache_hit" in [d.get("stage") for e, d in events if e == "status"]
    answer = next(d for e, d in events if e == "answer")
    assert answer["text"] == "缓存答案"
    assert answer["model"] == "cache"
    done = next(d for e, d in events if e == "done")
    assert done["cached"] is True


def test_cache_lookup_uses_tenant_namespace(monkeypatch, mock_llm):
    """P0 回归：缓存读写必须带租户命名空间，否则跨用户串味。"""
    seen = {}

    def fake_get(q, **kw):
        seen["get_ns"] = kw.get("namespace")
        return None

    def fake_put(q, answer, sources, model, **kw):
        seen["put_ns"] = kw.get("namespace")

    monkeypatch.setattr(stream_mod, "cache_get", fake_get)
    monkeypatch.setattr(stream_mod, "cache_put", fake_put)
    monkeypatch.setattr(
        stream_mod, "plan_retrieval",
        lambda q, user_id=None, api_key=None: RetrievalPlan(retrieve=False),
    )
    monkeypatch.setattr(stream_mod, "route_model", lambda q, s: _fake_route())

    list(stream_ask("问题", user_id=42, api_key="k"))
    assert seen["get_ns"] is not None and seen["get_ns"].startswith("42:")
    assert seen["put_ns"] == seen["get_ns"]


# ── 相关度阈值过滤（现由检索执行层负责，此处验证下游表现）──

def test_low_score_chunks_filtered_out(monkeypatch):
    """检索层把低分结果过滤掉（返回空）→ 无 key 时走'与知识库无关'文案"""
    _mock_pipeline(monkeypatch, [])
    events = _parse_sse(list(stream_ask("hello")))
    answer = next(d for e, d in events if e == "answer")
    assert "与知识库无关" in answer["text"]
    assert answer["sources"] == []
    done = next(d for e, d in events if e == "done")
    assert done["retrieval_count"] == 0


def test_high_score_chunks_pass_filter(monkeypatch):
    _mock_pipeline(monkeypatch, [GOOD_CHUNK])
    events = _parse_sse(list(stream_ask("Orbit 是什么")))
    retrieved = next(d for e, d in events if e == "status" and d.get("stage") == "retrieved")
    assert retrieved["count"] == 1
    answer = next(d for e, d in events if e == "answer")
    assert "intro.md" in answer["text"]  # 无 key fallback 引用高分来源
    assert "noise.md" not in str(answer)


def test_empty_search_no_key_fallback(monkeypatch):
    _mock_pipeline(monkeypatch, [])
    events = _parse_sse(list(stream_ask("问题")))
    answer = next(d for e, d in events if e == "answer")
    assert "未配置 LLM_API_KEY" in answer["text"]
    assert answer["model"] == "fallback"


# ── LLM 调用分支 ──

def test_llm_stream_rag_mode(monkeypatch, mock_llm):
    """有相关检索结果 → RAG prompt → 流式 token"""
    _mock_pipeline(monkeypatch, [GOOD_CHUNK])
    events = _parse_sse(list(stream_ask("Orbit 是什么", api_key="sk-test", model="deepseek-chat")))
    tokens = [d["text"] for e, d in events if e == "token"]
    assert tokens == ["你好", "，世界"]
    done = next(d for e, d in events if e == "done")
    assert done["model"] == "deepseek-chat"
    assert done["retrieval_count"] == 1
    # 验证发给 LLM 的请求
    req = mock_llm["requests"][0]
    assert "api.deepseek.com" in req["url"]
    assert req["body"]["model"] == "deepseek-chat"
    assert req["body"]["stream"] is True
    assert "Orbit 是 AI Agent 端到端系统" in req["body"]["messages"][1]["content"]
    assert req["headers"]["Authorization"] == "Bearer sk-test"


def test_llm_stream_chat_mode_when_no_relevant(monkeypatch, mock_llm):
    """无相关检索结果但有 key → 纯对话模式（不带检索上下文）"""
    _mock_pipeline(monkeypatch, [])
    events = _parse_sse(list(stream_ask("hello", api_key="sk-test", model="gpt-4o-mini")))
    tokens = [d["text"] for e, d in events if e == "token"]
    assert tokens == ["你好", "，世界"]
    req = mock_llm["requests"][0]
    user_msg = req["body"]["messages"][1]["content"]
    assert user_msg == "hello"  # 纯对话模式直接传问题
    assert "检索结果" not in user_msg
    assert "友好" in req["body"]["messages"][0]["content"]


def test_model_param_priority_over_route(monkeypatch, mock_llm):
    """model 参数优先于路由器默认模型"""
    _mock_pipeline(monkeypatch, [GOOD_CHUNK])
    list(stream_ask("问题", api_key="k", model="claude-sonnet-4"))
    req = mock_llm["requests"][0]
    assert req["body"]["model"] == "claude-sonnet-4"
    assert "api.anthropic.com" in req["url"]


def test_llm_error_yields_error_event(monkeypatch):
    _mock_pipeline(monkeypatch, [GOOD_CHUNK])

    def boom(req, timeout=None, **kw):
        raise RuntimeError("HTTP Error 401: Authorization Required")
    monkeypatch.setattr("urllib.request.urlopen", boom)

    events = _parse_sse(list(stream_ask("问题", api_key="bad-key", model="deepseek-chat")))
    error = next(d for e, d in events if e == "error")
    assert "401" in error["message"]
    done = next(d for e, d in events if e == "done")
    assert done["error"] is True
    assert done["model"] == "deepseek-chat"


def test_api_key_empty_string_falls_back_to_env(monkeypatch):
    """api_key 传空字符串也应回退环境变量（Bug 修复点：原判断仅 is None）"""
    _mock_pipeline(monkeypatch, [GOOD_CHUNK])
    monkeypatch.setenv("LLM_API_KEY", "")  # 环境变量也为空 → fallback
    events = _parse_sse(list(stream_ask("问题", api_key="")))
    answer = next(d for e, d in events if e == "answer")
    assert "未配置 LLM_API_KEY" in answer["text"]


def test_status_event_sequence(monkeypatch, mock_llm):
    """完整事件序列：start → cache_miss → retrieving → retrieved → routing → tokens → sources → done"""
    _mock_pipeline(monkeypatch, [GOOD_CHUNK])
    events = _parse_sse(list(stream_ask("问题", api_key="k", model="gpt-4o-mini")))
    stages = [d.get("stage") for e, d in events if e == "status"]
    assert stages[0] == "start"
    assert "cache_miss" in stages
    assert "retrieving" in stages
    assert "retrieved" in stages
    assert "routing" in stages
    assert events[-1][0] == "done"
