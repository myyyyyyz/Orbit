import json

from app.knowledge_agent.adapter import OpenAICompatibleKnowledgeAgent
from app.knowledge_agent.models import CorpusProfile


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def make_profile():
    return CorpusProfile(
        source_path="text-report.pdf",
        source_hash="a" * 64,
        file_type="pdf",
        text_extraction_ratio=0.9,
    )


def test_adapter_returns_typed_suggestion_and_sends_catalog_context():
    captured = {}

    def opener(request, timeout):
        captured["payload"] = json.loads(request.data)
        captured["timeout"] = timeout
        content = json.dumps(
            {
                "strategy_id": "pdf_text_hierarchical_v1",
                "confidence": 0.91,
                "reason": "文本可靠",
                "requires_review": False,
            }
        )
        return FakeResponse(
            {
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "choices": [
                    {"index": 0, "message": {"role": "assistant", "content": content}}
                ],
            }
        )

    agent = OpenAICompatibleKnowledgeAgent(
        api_key="secret",
        model="test-model",
        timeout_seconds=7,
        opener=opener,
    )
    attempt = agent.recommend(make_profile(), "Project ORB-2407")

    assert attempt.status == "success"
    assert attempt.suggestion["strategy_id"] == "pdf_text_hierarchical_v1"
    assert captured["timeout"] == 7
    assert captured["payload"]["response_format"] == {"type": "json_object"}
    assert "pdf_text_hierarchical_v1" in captured["payload"]["messages"][1]["content"]


def test_adapter_without_api_key_is_unavailable_without_http_call():
    def forbidden_opener(request, timeout):
        raise AssertionError("HTTP must not run without an API key")

    attempt = OpenAICompatibleKnowledgeAgent(
        api_key="", opener=forbidden_opener
    ).recommend(make_profile(), "sample")

    assert attempt.status == "unavailable"
    assert attempt.suggestion is None
    assert attempt.error_category == "missing_api_key"


def test_adapter_classifies_timeout_without_leaking_api_key():
    def timeout_opener(request, timeout):
        raise TimeoutError("request timed out for secret-key")

    attempt = OpenAICompatibleKnowledgeAgent(
        api_key="secret-key", opener=timeout_opener
    ).recommend(make_profile(), "sample")

    assert attempt.status == "error"
    assert attempt.suggestion is None
    assert attempt.error_category == "timeout"
    assert "secret-key" not in attempt.model_dump_json()


def test_adapter_rejects_malformed_json_response():
    def opener(request, timeout):
        return FakeResponse(
            {
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "choices": [
                    {"index": 0, "message": {"role": "assistant", "content": "not-json"}}
                ],
            }
        )

    attempt = OpenAICompatibleKnowledgeAgent(
        api_key="secret", opener=opener
    ).recommend(make_profile(), "sample")

    assert attempt.status == "error"
    assert attempt.suggestion is None
    assert attempt.error_category == "invalid_response"
