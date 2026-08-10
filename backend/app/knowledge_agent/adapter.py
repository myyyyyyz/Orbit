"""OpenAI-compatible Knowledge Agent adapter with per-file failure isolation."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from time import perf_counter
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .catalog import STRATEGY_CATALOG
from .models import AgentAttempt, CorpusProfile


DEFAULT_BASE_URL = "https://api.openai.com/v1/chat/completions"
SYSTEM_PROMPT = """你是 Knowledge Agent，只负责为单份知识文档选择 RAG 入库策略。
你必须从提供的 strategy_catalog 中选择一个 strategy_id，并只返回 JSON 对象：
strategy_id、confidence（0 到 1）、reason、requires_review（布尔值）。
不得建议目录以外的策略；格式混乱、信息不足或需要 OCR 时应升级人工复核。"""


class OpenAICompatibleKnowledgeAgent:
    """Recommend one catalog strategy through a Chat Completions-compatible API."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        model: str = "gpt-4o-mini",
        timeout_seconds: float = 20,
        opener: Callable[..., Any] | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.timeout_seconds = timeout_seconds
        self._opener = opener or urlopen

    @classmethod
    def from_env(cls) -> "OpenAICompatibleKnowledgeAgent":
        return cls(
            api_key=os.getenv("LLM_API_KEY", ""),
            base_url=os.getenv("LLM_BASE_URL", DEFAULT_BASE_URL),
            model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
            timeout_seconds=float(os.getenv("KNOWLEDGE_AGENT_TIMEOUT_SECONDS", "20")),
        )

    def _attempt(
        self,
        started_at: float,
        *,
        status: str,
        suggestion: dict[str, Any] | None = None,
        error_category: str | None = None,
    ) -> AgentAttempt:
        return AgentAttempt(
            status=status,
            model=self.model,
            duration_ms=max(0, round((perf_counter() - started_at) * 1000)),
            suggestion=suggestion,
            error_category=error_category,
        )

    def recommend(self, profile: CorpusProfile, evidence: str) -> AgentAttempt:
        """Return a sanitized attempt instead of raising transport/model errors."""

        started_at = perf_counter()
        if not self.api_key:
            return self._attempt(
                started_at, status="unavailable", error_category="missing_api_key"
            )

        catalog = {
            strategy_id: {
                "supported_file_types": sorted(definition.supported_file_types),
                "requires_review": definition.requires_review,
            }
            for strategy_id, definition in STRATEGY_CATALOG.items()
        }
        agent_input = {
            "profile": profile.model_dump(),
            "content_sample": evidence,
            "strategy_catalog": catalog,
        }
        payload = json.dumps(
            {
                "model": self.model,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": json.dumps(agent_input, ensure_ascii=False),
                    },
                ],
            }
        ).encode("utf-8")
        request = Request(
            self.base_url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )

        try:
            with self._opener(request, timeout=self.timeout_seconds) as response:
                result = json.loads(response.read())
            content = result["choices"][0]["message"]["content"]
            suggestion = json.loads(content)
            if not isinstance(suggestion, dict):
                raise TypeError("Agent suggestion must be an object")
            return self._attempt(
                started_at, status="success", suggestion=suggestion
            )
        except TimeoutError:
            return self._attempt(
                started_at, status="error", error_category="timeout"
            )
        except HTTPError:
            return self._attempt(
                started_at, status="error", error_category="http_error"
            )
        except URLError as exc:
            category = "timeout" if isinstance(exc.reason, TimeoutError) else "transport_error"
            return self._attempt(started_at, status="error", error_category=category)
        except (json.JSONDecodeError, KeyError, IndexError, TypeError, UnicodeDecodeError):
            return self._attempt(
                started_at, status="error", error_category="invalid_response"
            )
        except OSError:
            return self._attempt(
                started_at, status="error", error_category="transport_error"
            )
