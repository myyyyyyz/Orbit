# 知识源目录

Knowledge Agent **只允许**在此目录范围内规划与索引（越界请求会被 `_assert_descendant` 拒绝）。

## 使用方式

把你的知识文件放进本目录（支持子目录）：

```
knowledge/
├── evals/
│   └── questions.jsonl     # 检索评测数据集（发布门禁依赖）
├── 产品文档/
│   ├── 需求规格.docx
│   └── 接口说明.md
└── 运营数据/
    └── 季度报表.xlsx
```

支持格式：`.md` · `.docx` · `.xlsx` · `.pdf`（含扫描件，需配置 OCR Adapter）。

然后在前端 **知识库 → RAG Workbench** 中选择对应相对路径开始规划。

## 评测数据集（evals/questions.jsonl）

**发布门禁依赖此文件**：`promote` 前必须通过 `evaluate`，而 evaluate 会用这里的问题集计算 Source Hit@5 / Locator Hit@5 / MRR / nDCG。

每行一个 JSON 对象：

| 字段 | 必填 | 说明 |
|------|:----:|------|
| `schema_version` | ✅ | 固定 `"rag-retrieval.v1"` |
| `id` | ✅ | 用例唯一标识 |
| `question` | ✅ | 检索问题 |
| `expected_answer` | | 期望答案要点（人工核对用） |
| `relevant_sources` | ✅ | 应命中的源文件名数组 |
| `relevant_locators` | | 应命中的位置，如 `[{"heading":"支持级别"}]` 或 `[{"page":1}]` |
| `critical` | | `true` 时该用例未命中直接阻断发布 |
| `tags` | | 分类标签，便于分析薄弱环节 |

示例：

```json
{"schema_version":"rag-retrieval.v1","id":"policy-p1-sla","question":"P1 故障的首次响应时限是多久？","expected_answer":"4 小时","relevant_sources":["服务政策.md"],"relevant_locators":[{"heading":"支持级别"}],"critical":true,"tags":["markdown","heading"]}
```

> 仓库内 `questions.jsonl` 仅含示例条目，请按你的知识库内容替换。
> 数据集为空时评测无法给出有效指标，发布门禁将拒绝通过。

## 注意

- 本目录在 Docker 中以**只读**方式挂载到 `/app/knowledge`
- 通过前端上传的本地文件夹会进入租户隔离的 `ImportBatch` 暂存区，不直接写入此目录
- 单文件上限 25 MiB，单批次上限 250 MiB / 500 个文件
