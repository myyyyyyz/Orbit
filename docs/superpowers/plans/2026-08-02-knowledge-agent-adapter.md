# Knowledge Agent Adapter 第二阶段实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为七份多格式测试文档补齐期望标签，并在第一阶段 dry-run 流水线上接入首个 OpenAI-compatible Knowledge Agent Adapter。

**Architecture:** 新增独立的文档证据读取器与逐文件 Agent Adapter，继续复用 `CorpusProfile`、`STRATEGY_CATALOG`、`select_strategy()` 和 `FolderPlan`。显式建议优先于 Adapter；任何 Agent 失败均按文件进入现有规则兜底，所有路径保持 `vector_store_writes=0`。

**Tech Stack:** Python 3.12、Pydantic 2、urllib、python-docx、openpyxl、PyPDF2、FastAPI、SQLite、pytest

---

## 📁 文件职责

| 文件 | 职责 |
| --- | --- |
| `knowledge/evals/expected-strategies.jsonl` | 保存七份测试文档的期望策略标签 |
| `backend/app/knowledge_agent/evidence.py` | 从多格式文件提取不超过 6,000 字符的内存样本 |
| `backend/app/knowledge_agent/adapter.py` | 调用 OpenAI-compatible 接口并返回带类型的调用结果 |
| `backend/app/knowledge_agent/models.py` | 增加 Agent 调用追踪与计划字段 |
| `backend/app/knowledge_agent/selector.py` | 支持 Agent 升级人工复核，禁止降级强制复核 |
| `backend/app/knowledge_agent/pipeline.py` | 将证据、Adapter、显式建议和规则兜底串成单一流水线 |
| `backend/app/knowledge_agent/repository.py` | 以增量列保存 Agent 追踪，不保存内容样本 |
| `backend/app/api/knowledge_plan.py` | 暴露 `use_agent` 开关并构造真实 Adapter |
| `backend/test/test_knowledge_expected_labels.py` | 校验期望标签完整性和策略合法性 |
| `backend/test/test_knowledge_agent_evidence.py` | 校验多格式证据与长度上限 |
| `backend/test/test_knowledge_agent_adapter.py` | 校验真实协议解析及失败分类 |
| `backend/test/test_knowledge_agent_pipeline.py` | 校验逐文件 Agent 调用、优先级与兜底 |
| `backend/test/test_knowledge_agent_selector.py` | 校验人工复核只能升级 |
| `backend/test/test_knowledge_plan_api.py` | 校验 API 开关和零向量写入保证 |

## 🧪 Task 1：期望策略标签

**Files:**

- Create: `knowledge/evals/expected-strategies.jsonl`
- Create: `backend/test/test_knowledge_expected_labels.py`

- [ ] **Step 1：先写失败测试**

```python
import json
from pathlib import Path

from app.knowledge_agent.catalog import STRATEGY_CATALOG


ROOT = Path(__file__).resolve().parents[2]


def test_expected_strategy_labels_cover_every_fixture():
    labels = [json.loads(line) for line in (ROOT / "knowledge/evals/expected-strategies.jsonl").read_text(encoding="utf-8").splitlines()]
    fixture_names = {path.name for path in (ROOT / "knowledge/fixtures").iterdir() if path.is_file()}
    assert {label["source"] for label in labels} == fixture_names
    assert all(label["expected_strategy_id"] in STRATEGY_CATALOG for label in labels)
    assert all(isinstance(label["requires_review"], bool) for label in labels)
```

- [ ] **Step 2：运行测试并确认 RED**

Run:

```powershell
$env:PYTHONPATH='C:\Users\sz\Desktop\创业\Orbit-dev-knowledge\backend\.pydeps'
python -m pytest test/test_knowledge_expected_labels.py -q --noconftest
```

Expected: FAIL，提示 `expected-strategies.jsonl` 不存在。

- [ ] **Step 3：新增七条真实标签**

```jsonl
{"source":"clean-policy.md","expected_strategy_id":"markdown_hierarchical_v1","requires_review":false,"rationale":"Markdown 标题结构稳定","expected_signals":["heading_count"]}
{"source":"clean-handbook.docx","expected_strategy_id":"docx_layout_aware_v1","requires_review":false,"rationale":"标题、表格与图片结构完整","expected_signals":["heading_count","table_count","image_count"]}
{"source":"messy-notes.docx","expected_strategy_id":"docx_layout_aware_v1","requires_review":true,"rationale":"重复段落和混乱留白需要人工抽查","expected_signals":["image_count"]}
{"source":"text-report.pdf","expected_strategy_id":"pdf_text_hierarchical_v1","requires_review":false,"rationale":"文本提取率达到可用阈值","expected_signals":["page_count","text_extraction_ratio"]}
{"source":"scanned-notice.pdf","expected_strategy_id":"pdf_ocr_review_v1","requires_review":true,"rationale":"文本提取率过低，需要 OCR 与人工复核","expected_signals":["text_extraction_ratio","image_count"]}
{"source":"clean-projects.xlsx","expected_strategy_id":"spreadsheet_structured_v1","requires_review":false,"rationale":"单表头和稳定行结构适合结构化切分","expected_signals":["sheet_count","table_quality"]}
{"source":"messy-operations.xlsx","expected_strategy_id":"spreadsheet_structured_v1","requires_review":true,"rationale":"多工作表、合并单元格与空行需要人工抽查","expected_signals":["sheet_count","merged_cell_count","blank_row_count"]}
```

- [ ] **Step 4：运行测试并确认 GREEN**

Expected: `1 passed`。

- [ ] **Step 5：提交标签增量**

```powershell
git add knowledge/evals/expected-strategies.jsonl backend/test/test_knowledge_expected_labels.py
git commit -m "test: label knowledge fixture strategies"
```

## 🔎 Task 2：多格式文档证据读取器

**Files:**

- Create: `backend/app/knowledge_agent/evidence.py`
- Create: `backend/test/test_knowledge_agent_evidence.py`

- [ ] **Step 1：先写支持全部格式和长度限制的失败测试**

```python
from pathlib import Path

from app.knowledge_agent.evidence import read_evidence


FIXTURES = Path(__file__).resolve().parents[2] / "knowledge/fixtures"


def test_read_evidence_supports_every_fixture_type():
    samples = {path.name: read_evidence(path, max_chars=6000) for path in FIXTURES.iterdir()}
    assert "Support levels" in samples["clean-policy.md"]
    assert "Employee" in samples["clean-handbook.docx"]
    assert "ORB-2407" in samples["text-report.pdf"]
    assert "Projects" in samples["clean-projects.xlsx"]
    assert samples["scanned-notice.pdf"] == ""


def test_read_evidence_never_exceeds_limit():
    assert len(read_evidence(FIXTURES / "clean-policy.md", max_chars=40)) <= 40
```

- [ ] **Step 2：运行测试并确认 RED**

Expected: FAIL，提示 `app.knowledge_agent.evidence` 不存在。

- [ ] **Step 3：实现最小证据读取器**

```python
def read_evidence(path: Path, *, max_chars: int = 6000) -> str:
    readers = {
        ".md": _read_text,
        ".txt": _read_text,
        ".docx": _read_docx,
        ".xlsx": _read_xlsx,
        ".pdf": _read_pdf,
    }
    reader = readers.get(path.suffix.lower())
    if reader is None:
        return ""
    return reader(path)[:max_chars]
```

私有读取函数分别使用 `Document`、`load_workbook(..., data_only=True)` 和 `PdfReader`，XLSX 输出工作表名称及非空单元格值，任何读取结果只返回字符串，不执行持久化。

- [ ] **Step 4：运行证据测试并确认 GREEN**

Expected: `2 passed`。

- [ ] **Step 5：提交证据读取器**

```powershell
git add backend/app/knowledge_agent/evidence.py backend/test/test_knowledge_agent_evidence.py
git commit -m "feat: extract bounded knowledge evidence"
```

## 🤖 Task 3：OpenAI-compatible Adapter

**Files:**

- Create: `backend/app/knowledge_agent/adapter.py`
- Modify: `backend/app/knowledge_agent/models.py`
- Create: `backend/test/test_knowledge_agent_adapter.py`

- [ ] **Step 1：先写合法响应和缺少密钥的失败测试**

```python
import json

from app.knowledge_agent.adapter import OpenAICompatibleKnowledgeAgent
from app.knowledge_agent.models import CorpusProfile


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return None
    def read(self):
        return json.dumps(self.payload).encode()


def test_adapter_returns_typed_suggestion():
    def opener(request, timeout):
        content = json.dumps({"strategy_id":"pdf_text_hierarchical_v1","confidence":0.91,"reason":"文本可靠","requires_review":False})
        return FakeResponse({"choices":[{"message":{"content":content}}]})
    agent = OpenAICompatibleKnowledgeAgent(api_key="secret", model="test-model", opener=opener)
    attempt = agent.recommend(CorpusProfile(source_path="a.pdf", source_hash="a" * 64, file_type="pdf"), "sample")
    assert attempt.status == "success"
    assert attempt.suggestion["strategy_id"] == "pdf_text_hierarchical_v1"


def test_adapter_without_api_key_is_unavailable():
    attempt = OpenAICompatibleKnowledgeAgent(api_key="").recommend(
        CorpusProfile(source_path="a.pdf", source_hash="a" * 64, file_type="pdf"), "sample"
    )
    assert attempt.status == "unavailable"
    assert attempt.suggestion is None
```

- [ ] **Step 2：运行测试并确认 RED**

Expected: FAIL，提示 Adapter 尚不存在。

- [ ] **Step 3：增加 Agent 调用模型**

```python
class AgentAttempt(BaseModel):
    model_config = ConfigDict(frozen=True)
    status: Literal["success", "unavailable", "error"]
    model: str
    duration_ms: int = Field(ge=0)
    suggestion: dict[str, Any] | None = None
    error_category: str | None = None
```

- [ ] **Step 4：实现 Adapter 与环境变量工厂**

`OpenAICompatibleKnowledgeAgent.from_env()` 读取 `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL` 和 `KNOWLEDGE_AGENT_TIMEOUT_SECONDS`。`recommend()` 使用 `urllib.request.Request` 发送 Chat Completions JSON，提示词只包含 `profile.model_dump()`、有限内容样本和策略目录；捕获超时、HTTP、JSON 和响应结构错误，返回脱敏 `AgentAttempt`。

```python
payload = {
    "model": self.model,
    "temperature": 0,
    "response_format": {"type": "json_object"},
    "messages": [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(agent_input, ensure_ascii=False)},
    ],
}
```

- [ ] **Step 5：补充超时、非法 JSON 和不泄露密钥的测试**

测试 opener 分别抛出 `TimeoutError` 和返回非 JSON 内容；断言状态为 `error`、`suggestion is None`，且 `error_category` 不包含 API Key。

- [ ] **Step 6：运行 Adapter 测试并确认 GREEN**

Expected: 所有 Adapter 测试通过。

- [ ] **Step 7：提交 Adapter**

```powershell
git add backend/app/knowledge_agent/adapter.py backend/app/knowledge_agent/models.py backend/test/test_knowledge_agent_adapter.py
git commit -m "feat: add openai compatible knowledge agent"
```

## 🛡️ Task 4：校验、流水线与审计衔接

**Files:**

- Modify: `backend/app/knowledge_agent/models.py`
- Modify: `backend/app/knowledge_agent/selector.py`
- Modify: `backend/app/knowledge_agent/pipeline.py`
- Modify: `backend/app/knowledge_agent/repository.py`
- Modify: `backend/test/test_knowledge_agent_selector.py`
- Modify: `backend/test/test_knowledge_agent_pipeline.py`

- [ ] **Step 1：先写人工复核只能升级的失败测试**

```python
def test_agent_can_escalate_review_for_messy_spreadsheet():
    decision = select_strategy(
        make_profile(file_type="xlsx"),
        {"strategy_id":"spreadsheet_structured_v1","confidence":0.9,"reason":"结构混乱","requires_review":True},
    )
    assert decision.requires_review is True


def test_agent_cannot_suppress_catalog_required_review():
    decision = select_strategy(
        make_profile(text_extraction_ratio=0.01),
        {"strategy_id":"pdf_ocr_review_v1","confidence":0.9,"reason":"扫描件","requires_review":False},
    )
    assert decision.requires_review is True
```

- [ ] **Step 2：运行选择器测试并确认 RED**

Expected: 升级复核测试失败。

- [ ] **Step 3：最小修改选择器**

```python
requested_review = suggestion.get("requires_review", False)
if not isinstance(requested_review, bool):
    return None
requires_review = strategy.requires_review or requested_review
```

- [ ] **Step 4：先写流水线逐文件调用与显式建议优先测试**

使用记录调用路径的 Fake Agent。断言未提供显式建议时调用 Adapter；存在 `agent_suggestions[source_path]` 时不调用 Adapter；单文件返回 `error` 时该文件决策来源为 `fallback`，其他文件继续处理。

- [ ] **Step 5：扩展计划模型和流水线**

```python
class PlannedDocument(BaseModel):
    model_config = ConfigDict(frozen=True)
    profile: CorpusProfile
    decision: StrategyDecision
    agent_attempt: AgentAttempt | None = None
```

`plan_folder()` 增加 `agent` 可选参数。处理每份画像时先检查显式建议；否则读取证据并调用 Adapter。最终仍调用 `select_strategy()`，Adapter 的异常结果转换为空建议后走现有兜底。

- [ ] **Step 6：增量保存 Agent 追踪**

在 `knowledge_agent_documents` 增加可空 `agent_attempt_json`。初始化时先读取 `PRAGMA table_info(knowledge_agent_documents)`，旧数据库缺少该列时执行：

```sql
ALTER TABLE knowledge_agent_documents ADD COLUMN agent_attempt_json TEXT;
```

插入时保存 `document.agent_attempt.model_dump_json()`；内容样本不得进入数据库。

- [ ] **Step 7：运行选择器与流水线测试并确认 GREEN**

Expected: 两个测试文件全部通过，第一阶段断言不变。

- [ ] **Step 8：提交衔接增量**

```powershell
git add backend/app/knowledge_agent/models.py backend/app/knowledge_agent/selector.py backend/app/knowledge_agent/pipeline.py backend/app/knowledge_agent/repository.py backend/test/test_knowledge_agent_selector.py backend/test/test_knowledge_agent_pipeline.py
git commit -m "feat: integrate knowledge agent planning"
```

## 🌐 Task 5：API 开关与端到端回归

**Files:**

- Modify: `backend/app/api/knowledge_plan.py`
- Modify: `backend/test/test_knowledge_plan_api.py`
- Modify: `README.md`

- [ ] **Step 1：先写 API 开关失败测试**

```python
def test_plan_folder_can_disable_agent(tmp_path, monkeypatch):
    class ForbiddenAgent:
        def recommend(self, profile, evidence):
            raise AssertionError("agent must not run")
    monkeypatch.setattr(knowledge_plan.OpenAICompatibleKnowledgeAgent, "from_env", lambda: ForbiddenAgent())
    response = client.post("/api/knowledge/plan-folder", json={"path":"fixtures","use_agent":False})
    assert response.status_code == 200
    assert response.json()["vector_store_writes"] == 0
```

- [ ] **Step 2：运行 API 测试并确认 RED**

Expected: FAIL，因为请求模型尚无 `use_agent`。

- [ ] **Step 3：接入真实 Adapter**

```python
class PlanFolderRequest(BaseModel):
    path: str = Field(min_length=1)
    use_agent: bool = True
    agent_suggestions: dict[str, dict[str, Any]] = Field(default_factory=dict)
```

路由仅在 `use_agent` 为 `true` 时调用 `OpenAICompatibleKnowledgeAgent.from_env()`，并将结果传给 `plan_folder()`。缺少密钥时返回正常 dry-run 计划及 `unavailable` 追踪，不返回 500。

- [ ] **Step 4：补充配置文档**

在 `README.md` 的后端配置区域增加 `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`、`KNOWLEDGE_AGENT_TIMEOUT_SECONDS`，并给出 `use_agent=false` 的离线调用示例。

- [ ] **Step 5：运行完整新增测试集**

```powershell
$env:PYTHONPATH='C:\Users\sz\Desktop\创业\Orbit-dev-knowledge\backend\.pydeps'
python -m pytest test/test_knowledge_fixtures.py test/test_knowledge_expected_labels.py test/test_knowledge_agent_evidence.py test/test_knowledge_agent_adapter.py test/test_knowledge_agent_selector.py test/test_knowledge_agent_profiler.py test/test_knowledge_agent_pipeline.py test/test_knowledge_plan_api.py -q --noconftest
```

Expected: 全部通过，且输出中没有异常或失败。

- [ ] **Step 6：检查零向量写入边界和提交范围**

```powershell
git diff --check
git status --short
```

确认 Adapter、证据读取器和流水线没有导入 `app.store`、`chromadb`、`app.embed` 或调用 `add_documents`；确认未暂存 `.pydeps` 及已有无关文档变更。

- [ ] **Step 7：提交 API 与文档**

```powershell
git add backend/app/api/knowledge_plan.py backend/test/test_knowledge_plan_api.py README.md
git commit -m "feat: expose knowledge agent dry run"
```

- [ ] **Step 8：推送现有功能分支**

```powershell
git push susz347 dev/knowledge
```

Expected: 现有草稿 PR 自动包含第二阶段提交。
