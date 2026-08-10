# Knowledge Agent 3.2 策略执行与隔离索引实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将已批准的 `KnowledgeRun` 按策略转换为可定位、可重试的确定性 `KnowledgeChunk`，并只写入按 `run_id` 隔离的 ChromaDB staging collection，为 3.3 离线评测提供输入。

**Architecture:** 现有 `FolderPlan` 和策略决策仍是唯一执行来源。格式专用 Executor 只负责“源文件 → KnowledgeChunk”，`StagingStore` 只负责确定性向量写入，`execute_run()` 负责编排状态转换、执行前文件哈希复核、全运行失败清理和审计；旧 `/api/knowledge/upload` 保持兼容，但不被新流水线调用。

**Tech Stack:** Python 3.12、Pydantic 2、FastAPI、SQLite、ChromaDB 0.5、python-docx、openpyxl、PyPDF2、pytest

---

## 范围与边界

3.2 包含：

- 统一 `KnowledgeChunk` 模型和稳定 Chunk ID
- Markdown/Text、DOCX、XLSX、文本 PDF、扫描 PDF Executor
- 可注入 OCR Adapter；默认不可用时明确阻塞执行
- 按运行隔离的 staging collection
- 确定性 `upsert`，保证同一运行重试不重复写入
- 执行前再次校验源文件清单和哈希
- 失败时删除整个 staging collection，不影响活动索引
- `POST /api/knowledge/runs/{run_id}/execute`

3.2 不包含：

- staging 索引的检索质量评测
- 活动索引发布、版本指针和回滚
- OCR 厂商绑定或本地 OCR 二进制安装
- Knowledge Workbench 前端
- 改写旧 `/api/knowledge/upload`

扫描 PDF Executor 是真实的适配层：提供 OCR Adapter 时生成带页码 Chunk；未配置 OCR 时抛出脱敏的 `ExecutionBlocked("ocr_unavailable")`，整个 staging 写入回滚。不得把扫描 PDF 作为空文档成功处理。

## 文件职责

| 文件 | 职责 |
| --- | --- |
| `backend/app/knowledge_agent/models.py` | 定义 `KnowledgeChunk` 和执行结果字段 |
| `backend/app/knowledge_agent/chunk_ids.py` | 生成稳定、可复现的 Chunk ID |
| `backend/app/knowledge_agent/executors/base.py` | Executor、OCR 协议、异常与公共 Chunk 构造器 |
| `backend/app/knowledge_agent/executors/markdown.py` | 按标题路径执行 Markdown/Text 策略 |
| `backend/app/knowledge_agent/executors/docx.py` | 按段落、标题和表格顺序执行 DOCX 策略 |
| `backend/app/knowledge_agent/executors/xlsx.py` | 按工作表和行记录执行 XLSX 策略 |
| `backend/app/knowledge_agent/executors/pdf.py` | 按页执行文本 PDF，并通过 OCR Adapter 执行扫描 PDF |
| `backend/app/knowledge_agent/executors/registry.py` | 策略 ID 到 Executor 的唯一注册表 |
| `backend/app/knowledge_agent/staging_store.py` | staging collection 命名、upsert、计数和整库清理 |
| `backend/app/knowledge_agent/execution.py` | 编排批准校验、状态转换、执行、写入和失败清理 |
| `backend/app/knowledge_agent/repository.py` | 读取计划文档并保存 staging 审计字段 |
| `backend/app/api/knowledge_plan.py` | 暴露执行端点 |

## Task 1：统一 Chunk 模型与稳定 ID

**Files:**

- Modify: `backend/app/knowledge_agent/models.py`
- Create: `backend/app/knowledge_agent/chunk_ids.py`
- Create: `backend/test/test_knowledge_chunk_model.py`

- [ ] **Step 1：先写失败测试**

```python
import pytest
from pydantic import ValidationError

from app.knowledge_agent.chunk_ids import make_chunk_id
from app.knowledge_agent.models import KnowledgeChunk


def test_chunk_id_is_stable_and_changes_with_locator():
    first = make_chunk_id(
        run_id="run-1", source_hash="a" * 64,
        strategy_id="markdown_hierarchical_v1", chunk_index=0,
        locator="heading:Support",
    )
    assert first == make_chunk_id(
        run_id="run-1", source_hash="a" * 64,
        strategy_id="markdown_hierarchical_v1", chunk_index=0,
        locator="heading:Support",
    )
    assert first != make_chunk_id(
        run_id="run-1", source_hash="a" * 64,
        strategy_id="markdown_hierarchical_v1", chunk_index=0,
        locator="heading:Deletion",
    )


def test_knowledge_chunk_rejects_empty_text():
    with pytest.raises(ValidationError):
        KnowledgeChunk(
            chunk_id="kc_123", text="", run_id="run-1",
            source_path="policy.md", source_hash="a" * 64,
            strategy_id="markdown_hierarchical_v1", chunk_index=0,
        )
```

- [ ] **Step 2：运行测试并确认 RED**

Run:

```powershell
python -m pytest test/test_knowledge_chunk_model.py -q --noconftest
```

Expected: FAIL，提示 `KnowledgeChunk` 和 `chunk_ids` 不存在。

- [ ] **Step 3：实现模型和 ID**

```python
class KnowledgeChunk(BaseModel):
    model_config = ConfigDict(frozen=True)
    chunk_id: str = Field(min_length=4)
    text: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    source_hash: str = Field(min_length=64, max_length=64)
    strategy_id: str = Field(min_length=1)
    chunk_index: int = Field(ge=0)
    page: int | None = Field(default=None, ge=1)
    sheet: str | None = None
    heading_path: tuple[str, ...] = ()
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)
```

```python
def make_chunk_id(*, run_id, source_hash, strategy_id, chunk_index, locator):
    payload = "\0".join(
        [run_id, source_hash, strategy_id, str(chunk_index), locator]
    ).encode("utf-8")
    return "kc_" + hashlib.sha256(payload).hexdigest()[:40]
```

- [ ] **Step 4：运行测试并确认 GREEN**

Expected: Chunk 模型与稳定性测试全部通过。

- [ ] **Step 5：提交**

```powershell
git add backend/app/knowledge_agent/models.py backend/app/knowledge_agent/chunk_ids.py backend/test/test_knowledge_chunk_model.py
git commit -m "feat: define deterministic knowledge chunks"
```

## Task 2：Executor 协议、公共构造器与 Markdown 策略

**Files:**

- Create: `backend/app/knowledge_agent/executors/__init__.py`
- Create: `backend/app/knowledge_agent/executors/base.py`
- Create: `backend/app/knowledge_agent/executors/markdown.py`
- Create: `backend/app/knowledge_agent/executors/registry.py`
- Create: `backend/test/test_knowledge_markdown_executor.py`

- [ ] **Step 1：先写 Markdown 结构失败测试**

```python
from app.knowledge_agent.executors.registry import build_executor_registry
from app.knowledge_agent.profiler import profile_file


def test_markdown_executor_preserves_heading_path():
    source = FIXTURES / "clean-policy.md"
    profile = profile_file(source, root=FIXTURES)
    executor = build_executor_registry()["markdown_hierarchical_v1"]
    chunks = executor.execute(source, profile=profile, run_id="run-1")
    assert chunks
    support = next(chunk for chunk in chunks if "Support levels" in chunk.text)
    assert support.heading_path
    assert support.source_path == "clean-policy.md"
    assert len({chunk.chunk_id for chunk in chunks}) == len(chunks)
```

测试文件内定义：

```python
FIXTURES = Path(__file__).resolve().parents[2] / "knowledge" / "fixtures"
```

并直接使用 `FIXTURES`，不依赖未定义 fixture。

- [ ] **Step 2：运行测试并确认 RED**

Expected: FAIL，提示 Executor 模块不存在。

- [ ] **Step 3：实现协议与公共构造器**

```python
class ExecutionBlocked(RuntimeError):
    def __init__(self, category: str):
        super().__init__(category)
        self.category = category


class StrategyExecutor(Protocol):
    def execute(
        self, source: Path, *, profile: CorpusProfile, run_id: str
    ) -> tuple[KnowledgeChunk, ...]:
        raise NotImplementedError
```

公共 `build_chunks()` 接收 `(text, locator, page, sheet, heading_path)` 记录，过滤空白文本，按最终顺序分配 `chunk_index`，再调用 `make_chunk_id()`。所有格式必须复用此函数，禁止各自生成随机 ID。

- [ ] **Step 4：实现 Markdown Executor**

按 ATX 标题 `#` 到 `######` 维护标题栈，把标题与其后正文组成 section；每个 section 使用现有 `chunk_text()` 处理超长正文。纯文本没有标题时使用空 `heading_path`。注册表先只注册：

```python
return {
    "markdown_hierarchical_v1": MarkdownHierarchicalExecutor(),
}
```

- [ ] **Step 5：运行测试并提交**

Run:

```powershell
python -m pytest test/test_knowledge_markdown_executor.py test/test_knowledge_chunk_model.py -q --noconftest
```

Expected: 全部通过。

```powershell
git add backend/app/knowledge_agent/executors backend/test/test_knowledge_markdown_executor.py
git commit -m "feat: execute hierarchical markdown strategy"
```

## Task 3：DOCX 布局感知 Executor

**Files:**

- Create: `backend/app/knowledge_agent/executors/docx.py`
- Modify: `backend/app/knowledge_agent/executors/registry.py`
- Create: `backend/test/test_knowledge_docx_executor.py`

- [ ] **Step 1：先写段落、标题、表格失败测试**

```python
def test_docx_executor_preserves_headings_and_tables():
    source = FIXTURES / "clean-handbook.docx"
    profile = profile_file(source, root=FIXTURES)
    executor = build_executor_registry()["docx_layout_aware_v1"]
    chunks = executor.execute(source, profile=profile, run_id="run-1")
    assert chunks
    assert any(chunk.heading_path for chunk in chunks)
    assert any(chunk.metadata.get("block_type") == "table" for chunk in chunks)
    assert all(chunk.source_path == "clean-handbook.docx" for chunk in chunks)
```

- [ ] **Step 2：运行测试并确认 RED**

Expected: FAIL，注册表不存在 `docx_layout_aware_v1`。

- [ ] **Step 3：实现 DOCX Executor**

使用 `Document.iter_inner_content()` 按文档顺序读取 `Paragraph` 与 `Table`：

- `Heading N` 更新 N 级标题栈
- 普通段落形成 `block_type=paragraph`
- 表格按行转换为 `列1 | 列2`，形成 `block_type=table`
- 空段落和空表格不生成 Chunk
- 超长段落继续复用 `chunk_text()`

注册：

```python
"docx_layout_aware_v1": DocxLayoutAwareExecutor(),
```

- [ ] **Step 4：覆盖混乱 DOCX 和图片元数据**

新增断言：`messy-notes.docx` 仍能生成非空且 ID 唯一的 Chunk；当 `profile.image_count > 0` 时，每个 Chunk metadata 带 `document_image_count`，但 3.2 不对图片做 OCR。

- [ ] **Step 5：运行测试并提交**

```powershell
python -m pytest test/test_knowledge_docx_executor.py -q --noconftest
git add backend/app/knowledge_agent/executors/docx.py backend/app/knowledge_agent/executors/registry.py backend/test/test_knowledge_docx_executor.py
git commit -m "feat: execute layout aware docx strategy"
```

Expected: DOCX 测试全部通过。

## Task 4：XLSX 结构化 Executor

**Files:**

- Create: `backend/app/knowledge_agent/executors/xlsx.py`
- Modify: `backend/app/knowledge_agent/executors/registry.py`
- Create: `backend/test/test_knowledge_xlsx_executor.py`

- [ ] **Step 1：先写工作表与行定位失败测试**

```python
def test_xlsx_executor_creates_sheet_scoped_row_chunks():
    source = FIXTURES / "clean-projects.xlsx"
    profile = profile_file(source, root=FIXTURES)
    chunks = build_executor_registry()["spreadsheet_structured_v1"].execute(
        source, profile=profile, run_id="run-1"
    )
    assert chunks
    assert {chunk.sheet for chunk in chunks} == {"Projects"}
    assert any("ORB-2407" in chunk.text for chunk in chunks)
    assert all(chunk.metadata["row_number"] >= 1 for chunk in chunks)
```

- [ ] **Step 2：运行测试并确认 RED**

Expected: FAIL，注册表不存在 `spreadsheet_structured_v1`。

- [ ] **Step 3：实现结构化行切片**

使用 `load_workbook(..., data_only=True, read_only=False)`。每个工作表找到第一行非空行为表头；后续非空行转换为：

```text
Project ID: ORB-2407 | Risk: High | Blocker: SSO metadata
```

没有稳定表头时使用 Excel 列字母作为键。每个 Chunk 保存 `sheet`、`row_number`、`table_quality`；合并单元格值只保留左上角，空行不生成 Chunk。

注册：

```python
"spreadsheet_structured_v1": SpreadsheetStructuredExecutor(),
```

- [ ] **Step 4：覆盖混乱工作簿**

对 `messy-operations.xlsx` 断言多个工作表均被保留、空行不会产生空 Chunk、所有 Chunk ID 唯一。

- [ ] **Step 5：运行测试并提交**

```powershell
python -m pytest test/test_knowledge_xlsx_executor.py -q --noconftest
git add backend/app/knowledge_agent/executors/xlsx.py backend/app/knowledge_agent/executors/registry.py backend/test/test_knowledge_xlsx_executor.py
git commit -m "feat: execute structured spreadsheet strategy"
```

Expected: XLSX 测试全部通过。

## Task 5：文本 PDF 与扫描 PDF Executor

**Files:**

- Modify: `backend/app/knowledge_agent/executors/base.py`
- Create: `backend/app/knowledge_agent/executors/pdf.py`
- Modify: `backend/app/knowledge_agent/executors/registry.py`
- Create: `backend/test/test_knowledge_pdf_executor.py`

- [ ] **Step 1：先写文本 PDF 页码失败测试**

```python
def test_text_pdf_executor_preserves_page_number():
    source = FIXTURES / "text-report.pdf"
    profile = profile_file(source, root=FIXTURES)
    chunks = build_executor_registry()["pdf_text_hierarchical_v1"].execute(
        source, profile=profile, run_id="run-1"
    )
    assert any("ORB-2407" in chunk.text for chunk in chunks)
    assert all(chunk.page and chunk.page >= 1 for chunk in chunks)
```

- [ ] **Step 2：先写 OCR Adapter 行为失败测试**

```python
class StaticOcr:
    def extract_pages(self, source):
        return ("扫描通知需要人工复核",)


def test_scanned_pdf_uses_injected_ocr_adapter():
    registry = build_executor_registry(ocr=StaticOcr())
    source = FIXTURES / "scanned-notice.pdf"
    profile = profile_file(source, root=FIXTURES)
    chunks = registry["pdf_ocr_review_v1"].execute(
        source, profile=profile, run_id="run-1"
    )
    assert chunks[0].page == 1
    assert "人工复核" in chunks[0].text


def test_scanned_pdf_without_ocr_is_explicitly_blocked():
    with pytest.raises(ExecutionBlocked, match="ocr_unavailable"):
        build_executor_registry()["pdf_ocr_review_v1"].execute(
            source, profile=profile, run_id="run-1"
        )
```

- [ ] **Step 3：运行测试并确认 RED**

Expected: PDF 策略尚未注册，测试失败。

- [ ] **Step 4：实现两个 PDF Executor**

`PdfTextHierarchicalExecutor` 使用 `PdfReader` 逐页提取文字，每页复用 `chunk_text()`，页面无文字时跳过；最终无 Chunk 时抛 `ExecutionBlocked("pdf_text_empty")`。

定义 OCR 协议和默认实现：

```python
class OcrAdapter(Protocol):
    def extract_pages(self, source: Path) -> tuple[str, ...]:
        raise NotImplementedError


class UnavailableOcrAdapter:
    def extract_pages(self, source: Path) -> tuple[str, ...]:
        raise ExecutionBlocked("ocr_unavailable")
```

`PdfOcrReviewExecutor` 对 OCR 返回内容按页构造 Chunk；空 OCR 结果抛 `ExecutionBlocked("ocr_empty")`。

- [ ] **Step 5：运行测试并提交**

```powershell
python -m pytest test/test_knowledge_pdf_executor.py -q --noconftest
git add backend/app/knowledge_agent/executors/base.py backend/app/knowledge_agent/executors/pdf.py backend/app/knowledge_agent/executors/registry.py backend/test/test_knowledge_pdf_executor.py
git commit -m "feat: execute text and ocr pdf strategies"
```

Expected: 文本 PDF、注入 OCR 和 OCR 不可用路径全部通过。

## Task 6：隔离 StagingStore 与幂等 upsert

**Files:**

- Create: `backend/app/knowledge_agent/staging_store.py`
- Create: `backend/test/test_knowledge_staging_store.py`

- [ ] **Step 1：先写命名、隔离和幂等失败测试**

```python
def test_staging_collection_is_run_and_tenant_scoped():
    assert staging_collection_name("a" * 32, 7) != staging_collection_name("a" * 32, 8)
    assert staging_collection_name("a" * 32, 7) != staging_collection_name("b" * 32, 7)


def test_upsert_is_idempotent(fake_client, chunks):
    store = StagingStore(client=fake_client, encoder=lambda texts: [[0.1, 0.2]] * len(texts))
    assert store.upsert(chunks, user_id=7) == len(chunks)
    assert store.upsert(chunks, user_id=7) == len(chunks)
    assert store.count(run_id=chunks[0].run_id, user_id=7) == len(chunks)
```

集成测试使用 `conftest.py` 已隔离的临时 ChromaDB，实际调用时注入确定性 encoder，避免下载模型。

- [ ] **Step 2：运行测试并确认 RED**

Expected: FAIL，`staging_store` 不存在。

- [ ] **Step 3：实现安全命名和扁平元数据**

```python
def staging_collection_name(run_id: str, user_id: int | None) -> str:
    tenant = hashlib.sha256(str(user_id).encode()).hexdigest()[:8]
    run = re.sub(r"[^a-zA-Z0-9]", "", run_id)[:32]
    return f"kr_{tenant}_{run}"
```

写入前将 `heading_path` 序列化为 JSON 字符串，去除值为 `None` 的字段，保证 Chroma metadata 只有标量。

- [ ] **Step 4：实现 upsert、count 和 delete**

`StagingStore.upsert()` 必须调用 collection `upsert` 而不是 `add`，ID 使用 `KnowledgeChunk.chunk_id`；默认 client 为 `app.store.get_client()`，默认 encoder 为 `app.embed.encode()`。`delete()` 只删除计算出的当前运行 collection。

- [ ] **Step 5：运行测试并提交**

```powershell
python -m pytest test/test_knowledge_staging_store.py -q --noconftest
git add backend/app/knowledge_agent/staging_store.py backend/test/test_knowledge_staging_store.py
git commit -m "feat: add isolated knowledge staging store"
```

Expected: 隔离、幂等、元数据和删除测试全部通过。

## Task 7：执行审计仓储与 `execute_run()` 编排

**Files:**

- Modify: `backend/app/knowledge_agent/models.py`
- Modify: `backend/app/knowledge_agent/repository.py`
- Modify: `backend/app/knowledge_agent/approval.py`
- Create: `backend/app/knowledge_agent/execution.py`
- Create: `backend/test/test_knowledge_run_execution.py`

- [ ] **Step 1：建立完整的内存执行测试环境**

```python
import shutil
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.knowledge_agent.catalog import STRATEGY_CATALOG
from app.knowledge_agent.chunk_ids import make_chunk_id
from app.knowledge_agent.models import KnowledgeChunk
from app.knowledge_agent.pipeline import plan_folder
from app.knowledge_agent.staging_store import staging_collection_name


SOURCE_FIXTURES = Path(__file__).resolve().parents[2] / "knowledge" / "fixtures"


class StaticExecutor:
    def execute(self, source, *, profile, run_id):
        text = source.name + " knowledge"
        return (
            KnowledgeChunk(
                chunk_id=make_chunk_id(
                    run_id=run_id, source_hash=profile.source_hash,
                    strategy_id=self.strategy_id, chunk_index=0,
                    locator="static",
                ),
                text=text, run_id=run_id,
                source_path=profile.source_path,
                source_hash=profile.source_hash,
                strategy_id=self.strategy_id, chunk_index=0,
            ),
        )

    def __init__(self, strategy_id):
        self.strategy_id = strategy_id


class FailingExecutor:
    def __init__(self, category):
        self.category = category

    def execute(self, source, *, profile, run_id):
        raise ExecutionBlocked(self.category)


class RecordingStagingStore:
    def __init__(self):
        self.writes = []
        self.deleted = []
        self.active_collection_writes = 0

    def upsert(self, chunks, *, user_id):
        self.writes.extend(chunks)
        return len(chunks)

    def delete(self, *, run_id, user_id):
        self.deleted.append(staging_collection_name(run_id, user_id))


@dataclass
class ExecutionContext:
    plan: object
    knowledge_root: Path
    database: Path
    policy: Path
    executors: dict
    store: RecordingStagingStore


@pytest.fixture
def context(tmp_path):
    knowledge_root = tmp_path / "knowledge"
    fixtures = knowledge_root / "fixtures"
    shutil.copytree(SOURCE_FIXTURES, fixtures)
    database = tmp_path / "audit.sqlite3"
    plan = plan_folder(
        fixtures, knowledge_root=knowledge_root,
        database_path=database, user_id=7,
    )
    executors = {
        strategy_id: StaticExecutor(strategy_id)
        for strategy_id in STRATEGY_CATALOG
    }
    return ExecutionContext(
        plan=plan, knowledge_root=knowledge_root, database=database,
        policy=fixtures / "clean-policy.md", executors=executors,
        store=RecordingStagingStore(),
    )


def approve(context):
    return approve_run(
        context.plan.run_id, knowledge_root=context.knowledge_root,
        database_path=context.database, user_id=7,
    )


def execute_context(context):
    return execute_run(
        context.plan.run_id, knowledge_root=context.knowledge_root,
        database_path=context.database, user_id=7,
        executors=context.executors, staging_store=context.store,
    )


def execute_approved(context):
    approve(context)
    return execute_context(context)
```

- [ ] **Step 2：先写未批准运行拒绝测试**

```python
def test_execute_run_rejects_unapproved_plan(context):
    with pytest.raises(InvalidRunTransition):
        execute_run(
            context.plan.run_id,
            knowledge_root=context.knowledge_root,
            database_path=context.database,
            user_id=7,
            executors=context.executors,
            staging_store=context.store,
        )
    assert context.store.writes == []
```

- [ ] **Step 3：先写成功执行和状态交接测试**

```python
def test_execute_approved_run_writes_only_staging_and_hands_off_to_evaluation(context):
    approve_run(context.plan.run_id, knowledge_root=context.knowledge_root, database_path=context.database, user_id=7)
    result = execute_run(
        context.plan.run_id,
        knowledge_root=context.knowledge_root,
        database_path=context.database,
        user_id=7,
        executors=context.executors,
        staging_store=context.store,
    )
    assert result.status == "evaluating"
    assert result.dry_run is False
    assert result.vector_store_writes == result.chunk_count
    assert result.staging_collection.startswith("kr_")
    assert context.store.active_collection_writes == 0
```

- [ ] **Step 4：先写失败清理与文件漂移测试**

```python
def test_executor_failure_deletes_staging_and_marks_run_failed(context):
    context.executors["pdf_ocr_review_v1"] = FailingExecutor("ocr_unavailable")
    result = execute_approved(context)
    assert result.status == "failed"
    assert result.execution_error == "ocr_unavailable"
    assert context.store.deleted == [result.staging_collection]


def test_source_change_after_approval_invalidates_before_indexing(context):
    approve(context)
    context.policy.write_text("changed", encoding="utf-8")
    result = execute_context(context)
    assert result.status == "invalidated"
    assert context.store.writes == []
```

- [ ] **Step 5：运行测试并确认 RED**

Run:

```powershell
python -m pytest test/test_knowledge_run_execution.py -q --noconftest
```

Expected: FAIL，提示执行编排或执行审计字段不存在。

- [ ] **Step 6：扩展审计仓储**

为 `knowledge_agent_runs` 增量增加：

```text
staging_collection TEXT
chunk_count INTEGER NOT NULL DEFAULT 0
execution_error TEXT
indexing_started_at TEXT
indexing_completed_at TEXT
```

`KnowledgeRunRecord` 增加对应字段。新增 `load_planned_documents()`，从已有 `profile_json`、`decision_json`、`agent_attempt_json` 恢复 `PlannedDocument`；新增参数化 `save_execution_result()`，禁止保存原始文档全文。

进入 `indexing` 时把运行记录的 `dry_run` 更新为 `0`；staging upsert 成功后把 `vector_store_writes` 更新为实际 Chunk 数。失败并删除 staging 后保持 `vector_store_writes=0`，避免把已回滚写入误报为现存向量。

- [ ] **Step 7：提取可复用文件清单校验**

在 `approval.py` 提取：

```python
def source_manifest_matches(run, *, knowledge_root, database_path, user_id) -> bool:
    stored = load_source_hashes(
        run.run_id, database_path=database_path, user_id=user_id
    )
    resolved_root = knowledge_root.resolve()
    source_folder = (resolved_root / run.folder_path).resolve()
    try:
        source_folder.relative_to(resolved_root)
    except ValueError as exc:
        raise RunStateConflict("KnowledgeRun 文件夹越出知识库根目录") from exc
    if not source_folder.is_dir():
        return False
    current = {
        profile.source_path: profile.source_hash
        for profile in scan_folder(source_folder)
    }
    return current == stored
```

`approve_run()` 和 `execute_run()` 共用它。执行开始前若不匹配，原子转换 `approved -> invalidated`，不创建 staging collection。

- [ ] **Step 8：实现执行编排**

顺序固定为：

```text
读取租户 Run → 要求 approved → 再验文件哈希
→ 原子 approved→indexing
→ 按文档生成 Chunk 并立即 staging upsert
→ 保存 collection/chunk_count/vector_store_writes
→ indexing→evaluating
```

按文档写入可以限制大型文件夹的内存峰值；staging collection 不对搜索接口可见。任一 Executor、Embedding 或 Chroma 写入失败时：删除整个 staging collection、把现存写入数归零、保存脱敏错误分类、原子 `indexing -> failed`。异常分类只允许 `ocr_unavailable`、`ocr_empty`、`parse_error`、`embedding_error`、`storage_error`、`internal_error`。

- [ ] **Step 9：运行测试并提交**

```powershell
python -m pytest test/test_knowledge_run_execution.py test/test_knowledge_run_approval.py test/test_knowledge_run_repository.py -q --noconftest
git add backend/app/knowledge_agent/models.py backend/app/knowledge_agent/repository.py backend/app/knowledge_agent/approval.py backend/app/knowledge_agent/execution.py backend/test/test_knowledge_run_execution.py
git commit -m "feat: execute approved knowledge runs"
```

Expected: 成功、未批准、文件漂移、OCR 阻塞、写入失败和清理路径全部通过。

## Task 8：执行 API 与完整回归

**Files:**

- Modify: `backend/app/api/knowledge_plan.py`
- Modify: `backend/test/test_knowledge_plan_api.py`
- Modify: `README.md`

- [ ] **Step 1：先写执行 API 失败测试**

```python
class RecordingStagingStore:
    def __init__(self):
        self.writes = []
        self.deleted = []

    def upsert(self, chunks, *, user_id):
        self.writes.extend(chunks)
        return len(chunks)

    def delete(self, *, run_id, user_id):
        self.deleted.append(staging_collection_name(run_id, user_id))


class ApiStaticExecutor:
    def __init__(self, strategy_id):
        self.strategy_id = strategy_id

    def execute(self, source, *, profile, run_id):
        return (
            KnowledgeChunk(
                chunk_id=make_chunk_id(
                    run_id=run_id, source_hash=profile.source_hash,
                    strategy_id=self.strategy_id, chunk_index=0,
                    locator=profile.source_path,
                ),
                text=source.name, run_id=run_id,
                source_path=profile.source_path,
                source_hash=profile.source_hash,
                strategy_id=self.strategy_id, chunk_index=0,
            ),
        )


def static_registry():
    return {
        strategy_id: ApiStaticExecutor(strategy_id)
        for strategy_id in STRATEGY_CATALOG
    }


def test_approved_run_can_execute_to_evaluating(tmp_path, monkeypatch):
    knowledge_root = tmp_path / "knowledge"
    shutil.copytree(SOURCE_KNOWLEDGE / "fixtures", knowledge_root / "fixtures")
    app = FastAPI()
    app.include_router(knowledge_plan.router)
    app.dependency_overrides[get_current_user] = lambda: {"user_id": 42}
    database = tmp_path / "audit.sqlite3"
    monkeypatch.setattr(knowledge_plan, "_KNOWLEDGE_ROOT", knowledge_root)
    monkeypatch.setattr(knowledge_plan, "_database_path", lambda: database)
    monkeypatch.setattr(knowledge_plan, "build_executor_registry", static_registry)
    store = RecordingStagingStore()
    monkeypatch.setattr(knowledge_plan, "StagingStore", lambda: store)
    client = TestClient(app)
    planned = client.post(
        "/api/knowledge/plan-folder",
        json={"path": "fixtures", "use_agent": False},
    )
    run_id = planned.json()["run_id"]
    assert client.post(f"/api/knowledge/runs/{run_id}/approve").status_code == 200

    response = client.post(
        f"/api/knowledge/runs/{run_id}/execute"
    )

    assert response.status_code == 200
    assert response.json()["status"] == "evaluating"
    assert response.json()["staging_collection"].startswith("kr_")
```

- [ ] **Step 2：运行测试并确认 RED**

Expected: FAIL，执行端点返回 404/405。

- [ ] **Step 3：实现执行端点**

新增：

```text
POST /api/knowledge/runs/{run_id}/execute
```

端点要求认证；不存在或跨租户返回 404；未批准、重复执行或并发冲突返回 409；文件变化返回 409 和 `status=invalidated`；OCR/解析/Embedding/存储失败返回 422 和脱敏 `execution_error`。成功响应状态为 `evaluating`，表示等待 3.3 评测，不代表已发布。

- [ ] **Step 4：更新 README 边界**

把当前边界更新为：3.2 可写隔离 staging collection，但活动知识库仍不变化；只有 3.3 评测通过后才允许发布。补充执行 curl 示例，不展示 API Key。

- [ ] **Step 5：运行完整回归**

```powershell
python -m pytest test/test_knowledge_fixtures.py test/test_knowledge_expected_labels.py test/test_knowledge_agent_evidence.py test/test_knowledge_agent_adapter.py test/test_knowledge_agent_selector.py test/test_knowledge_agent_profiler.py test/test_knowledge_agent_pipeline.py test/test_knowledge_plan_api.py test/test_knowledge_run_state.py test/test_knowledge_run_repository.py test/test_knowledge_run_approval.py test/test_knowledge_chunk_model.py test/test_knowledge_markdown_executor.py test/test_knowledge_docx_executor.py test/test_knowledge_xlsx_executor.py test/test_knowledge_pdf_executor.py test/test_knowledge_staging_store.py test/test_knowledge_run_execution.py -q --noconftest
```

Expected: 全部通过；未配置真实 OCR 或外部 LLM 时测试仍不访问网络。

- [ ] **Step 6：检查安全边界和提交范围**

```powershell
git diff --check
git status --short
git grep -n "get_collection(user_id)\|add_documents" -- backend/app/knowledge_agent
```

Expected: Knowledge Agent 不调用活动 collection 的 `get_collection(user_id)` 或旧 `add_documents()`；只允许 `staging_store.py` 通过 `get_client()` 创建 `kr_` collection。`.pydeps` 和既有无关文档变更不得进入暂存区。

- [ ] **Step 7：提交并推送**

```powershell
git add backend/app/api/knowledge_plan.py backend/test/test_knowledge_plan_api.py README.md
git commit -m "feat: expose staged knowledge execution"
git push susz347 dev/knowledge
```

Expected: 现有草稿 PR 自动包含 3.2 的完整提交。

## 3.2 验收标准

- 同一文件、同一 Run、同一定位生成完全相同的 Chunk ID。
- Markdown、DOCX、XLSX 和文本 PDF fixture 均产生非空、可定位 Chunk。
- 扫描 PDF 使用注入 OCR Adapter；未配置 OCR 时明确失败并清理 staging。
- 只有 `approved` Run 可以执行。
- 执行前源文件变化会使 Run 变为 `invalidated`，零向量写入。
- 文档按顺序转换并写入不可见的 staging；任一失败会删除整个 staging collection。
- 重复 upsert 不增加向量数量。
- staging collection 同时按租户和 `run_id` 隔离。
- 成功后状态停在 `evaluating`，不得修改当前活动知识库。
- 成功执行后 `dry_run=false` 且 `vector_store_writes=chunk_count`；失败清理后写入数为零。
- 审计数据库只保存状态、计数、collection 名和脱敏错误，不保存原文或 Embedding。
- 第二阶段与 3.1 的 45 个回归测试继续通过。
