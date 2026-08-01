# Knowledge Agent Phase One Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a dry-run Knowledge Agent that profiles a mixed document fixture folder, selects a catalog strategy or deterministic fallback, persists an auditable plan, and exposes it through a protected API.

**Architecture:** The pipeline is read-only with respect to Chroma and global RAG settings. `profiler.py` derives deterministic evidence from files, `selector.py` validates an optional agent suggestion against a fixed catalog, and `pipeline.py` stores and returns an `IngestionPlan`; invalid or missing suggestions use the fallback mapping.

**Tech Stack:** FastAPI, Pydantic v2, SQLite, PyPDF2, `python-docx`, `openpyxl`, `reportlab`, pytest.

---

## 🗂️ File structure

| Path | Responsibility |
| --- | --- |
| `backend/app/knowledge_agent/models.py` | Immutable profile, decision and report models. |
| `backend/app/knowledge_agent/catalog.py` | Versioned strategy definitions and compatibility checks. |
| `backend/app/knowledge_agent/profiler.py` | Recursive scanning, SHA-256 and format signals. |
| `backend/app/knowledge_agent/selector.py` | Optional suggestion validation and deterministic fallback. |
| `backend/app/knowledge_agent/repository.py` | SQLite run/document/decision audit records. |
| `backend/app/knowledge_agent/pipeline.py` | Orchestrates dry-run planning without Chroma writes. |
| `backend/app/api/knowledge.py` | Adds authenticated `POST /plan-folder`. |
| `backend/test/test_knowledge_agent_*.py` | Unit and API tests. |
| `knowledge/fixtures/` | Generated, fictional DOCX/XLSX/PDF/Markdown fixtures. |
| `knowledge/evals/questions.jsonl` | Retrieval assertions for later phases. |
| `scripts/generate_knowledge_fixtures.py` | Reproducibly writes the binary fixtures. |

## 🧪 Task 1: Create reproducible fixtures and evaluation data

**Files:**

- Modify: `backend/requirements.txt`
- Create: `scripts/generate_knowledge_fixtures.py`
- Create: `knowledge/fixtures/clean-policy.md`
- Create: `knowledge/evals/questions.jsonl`
- Test: `backend/test/test_knowledge_fixtures.py`

- [ ] **Step 1: Write the failing fixture inventory test**

```python
from pathlib import Path

EXPECTED = {
    "clean-policy.md", "clean-handbook.docx", "messy-notes.docx",
    "text-report.pdf", "scanned-notice.pdf", "clean-projects.xlsx",
    "messy-operations.xlsx",
}

def test_fixture_inventory_is_complete():
    root = Path(__file__).parents[2] / "knowledge" / "fixtures"
    assert {path.name for path in root.iterdir() if path.is_file()} == EXPECTED
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `python -m pytest test/test_knowledge_fixtures.py -q` from `backend/`.

Expected: failure because the fixture folder and files do not exist.

- [ ] **Step 3: Add generation dependencies and generator**

Append `python-docx==1.1.2`, `openpyxl==3.1.5`, and `reportlab==4.2.5` to `backend/requirements.txt`. The generator must write only fictional Chinese operations content, embed one generated diagram image in `clean-handbook.docx`, create a text PDF and an image-only PDF, and create both a stable-header workbook and a merged-cell workbook.

```python
ROOT = Path(__file__).parents[1] / "knowledge" / "fixtures"

def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    write_markdown(ROOT / "clean-policy.md")
    write_docx(ROOT / "clean-handbook.docx", clean=True)
    write_docx(ROOT / "messy-notes.docx", clean=False)
    write_pdf(ROOT / "text-report.pdf", image_only=False)
    write_pdf(ROOT / "scanned-notice.pdf", image_only=True)
    write_workbook(ROOT / "clean-projects.xlsx", clean=True)
    write_workbook(ROOT / "messy-operations.xlsx", clean=False)
```

- [ ] **Step 4: Generate and verify fixtures**

Run: `python scripts/generate_knowledge_fixtures.py` from repository root, then `python -m pytest test/test_knowledge_fixtures.py -q` from `backend/`.

Expected: PASS; every generated binary file is small enough to commit and the JSONL file contains one valid JSON object per line.

- [ ] **Step 5: Commit fixture work**

```bash
git add backend/requirements.txt scripts/generate_knowledge_fixtures.py knowledge
git commit -m "test: add mixed knowledge fixtures"
```

## ⚙️ Task 2: Define the strategy catalog and selector

**Files:**

- Create: `backend/app/knowledge_agent/__init__.py`
- Create: `backend/app/knowledge_agent/models.py`
- Create: `backend/app/knowledge_agent/catalog.py`
- Create: `backend/app/knowledge_agent/selector.py`
- Test: `backend/test/test_knowledge_agent_selector.py`

- [ ] **Step 1: Write failing selection tests**

```python
def test_invalid_agent_strategy_falls_back(pdf_profile):
    decision = select_strategy(pdf_profile, {"strategy_id": "shell_exec_v9"})
    assert decision.decision_source == "fallback"
    assert decision.strategy_id == "pdf_text_hierarchical_v1"

def test_scanned_pdf_requires_review(scanned_pdf_profile):
    decision = select_strategy(scanned_pdf_profile, None)
    assert decision.strategy_id == "pdf_ocr_review_v1"
    assert decision.requires_review is True
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `python -m pytest test/test_knowledge_agent_selector.py -q` from `backend/`.

Expected: import error because the package does not yet exist.

- [ ] **Step 3: Implement immutable models, catalog, and fallback**

```python
class StrategyDecision(BaseModel, frozen=True):
    strategy_id: str
    decision_source: Literal["agent", "rule", "fallback"]
    confidence: float = Field(ge=0, le=1)
    reason: str
    requires_review: bool = False

def select_strategy(profile: CorpusProfile, suggestion: dict | None) -> StrategyDecision:
    if suggestion and is_compatible(profile, suggestion.get("strategy_id")):
        return validated_agent_decision(profile, suggestion)
    return fallback_for(profile)
```

`fallback_for` must choose by file type and profile signals only; it may never modify `settings.rag` or return a strategy absent from the catalog.

- [ ] **Step 4: Run selector tests**

Run: `python -m pytest test/test_knowledge_agent_selector.py -q` from `backend/`.

Expected: PASS, including unknown strategy, incompatible suggestion and low-text PDF cases.

- [ ] **Step 5: Commit selector work**

```bash
git add backend/app/knowledge_agent backend/test/test_knowledge_agent_selector.py
git commit -m "feat: add knowledge strategy selector"
```

## 🔎 Task 3: Profile fixture files deterministically

**Files:**

- Create: `backend/app/knowledge_agent/profiler.py`
- Test: `backend/test/test_knowledge_agent_profiler.py`

- [ ] **Step 1: Write failing profiler tests**

```python
def test_profile_scanned_pdf_has_low_text_ratio(fixtures_dir):
    profile = profile_file(fixtures_dir / "scanned-notice.pdf")
    assert profile.file_type == "pdf"
    assert profile.text_extraction_ratio < 0.1

def test_profile_clean_workbook_detects_stable_header(fixtures_dir):
    profile = profile_file(fixtures_dir / "clean-projects.xlsx")
    assert profile.table_quality == "stable"
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `python -m pytest test/test_knowledge_agent_profiler.py -q` from `backend/`.

Expected: import error for `profile_file`.

- [ ] **Step 3: Implement safe recursive scanning and profiling**

```python
def scan_folder(root: Path) -> list[Path]:
    resolved_root = root.resolve()
    return sorted(path for path in resolved_root.rglob("*")
                  if path.is_file() and resolved_root in path.resolve().parents)

def profile_file(path: Path) -> CorpusProfile:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    # Dispatch only to PDF, DOCX, XLSX, Markdown, or text profilers.
    return dispatch_profile(path, digest)
```

The PDF profiler must use `PyPDF2.PdfReader` and report page count plus extracted-character ratio. The DOCX profiler must count headings, tables and embedded images. The XLSX profiler must report sheet count, merged-cell count, blank-row count and `table_quality`.

- [ ] **Step 4: Run profiler tests**

Run: `python -m pytest test/test_knowledge_agent_profiler.py -q` from `backend/`.

Expected: PASS; scanning never follows paths outside the supplied folder.

- [ ] **Step 5: Commit profiler work**

```bash
git add backend/app/knowledge_agent/profiler.py backend/test/test_knowledge_agent_profiler.py
git commit -m "feat: profile knowledge fixtures"
```

## 🗄️ Task 4: Persist dry-run plans and expose the API

**Files:**

- Create: `backend/app/knowledge_agent/repository.py`
- Create: `backend/app/knowledge_agent/pipeline.py`
- Modify: `backend/app/api/knowledge.py`
- Modify: `backend/app/main.py`
- Test: `backend/test/test_knowledge_agent_pipeline.py`
- Test: `backend/test/test_api_knowledge.py`

- [ ] **Step 1: Write failing pipeline and API tests**

```python
def test_plan_folder_uses_fallback_when_agent_is_disabled(fixtures_dir, tmp_path):
    plan = plan_folder(fixtures_dir, agent_selector=None, db_path=tmp_path / "plans.db")
    assert plan.documents
    assert any(item.decision.decision_source == "fallback" for item in plan.documents)

def test_plan_folder_endpoint_requires_auth(client):
    response = client.post("/api/knowledge/plan-folder", json={"path": "knowledge/fixtures"})
    assert response.status_code == 401
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `python -m pytest test/test_knowledge_agent_pipeline.py test/test_api_knowledge.py -q` from `backend/`.

Expected: import error and 404 for the new endpoint.

- [ ] **Step 3: Implement repository, pipeline, and endpoint**

```python
@router.post("/plan-folder")
def api_plan_folder(body: PlanFolderRequest, current_user: dict = Depends(get_current_user)):
    root = resolve_allowed_knowledge_path(body.path)
    return plan_folder(root, agent_selector=None, user_id=current_user["user_id"])
```

`resolve_allowed_knowledge_path` must accept paths only inside the repository `knowledge/` directory. `plan_folder` may insert audit rows into SQLite but must not import or call `store.add_documents`, `encode`, `chunk_text`, or mutate `settings.rag`.

- [ ] **Step 4: Run focused and complete backend tests**

Run: `python -m pytest test/test_knowledge_agent_pipeline.py test/test_api_knowledge.py -q`, then `python -m pytest test -q` from `backend/`.

Expected: focused tests PASS; report any pre-existing failures separately from new failures.

- [ ] **Step 5: Commit API and pipeline work**

```bash
git add backend/app/knowledge_agent backend/app/api/knowledge.py backend/app/main.py backend/test
git commit -m "feat: add knowledge planning dry run"
```

## ✅ Task 5: Update documentation and publish

**Files:**

- Modify: `docs/project/pr/pr-00000001-knowledge-agent-rag-design.md`
- Modify: `docs/superpowers/specs/2026-08-01-knowledge-agent-rag-design.md`

- [ ] **Step 1: Record generated fixtures, endpoint contract, and test output**

Document the exact endpoint request/response, the fallback behavior, known limitations, and the commands that passed. Do not claim DOCX/XLSX ingestion is complete: phase one only profiles and plans.

- [ ] **Step 2: Verify the full diff**

Run: `git diff --check` and inspect `git status --short`.

Expected: no whitespace errors; only intended files are staged.

- [ ] **Step 3: Commit and push the phase**

```bash
git add docs
git commit -m "docs: record knowledge planning phase"
git push
```

## 🔍 Plan self-review

| Specification requirement | Plan task |
| --- | --- |
| Real mixed fixtures | Task 1 |
| Corpus profiling | Task 3 |
| Controlled Agent choice | Task 2 |
| Agent failure fallback | Tasks 2 and 4 |
| No vector writes in phase one | Task 4 |
| Auditability and protected API | Task 4 |
| Evaluation fixture for later RAG work | Task 1 |

The plan contains no placeholder tasks, keeps vector ingestion and hybrid retrieval out of phase one, and uses one immutable decision model consistently across selector, pipeline and API.
