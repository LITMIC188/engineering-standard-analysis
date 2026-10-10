# 文件输出契约

每次作业在独立目录 `run/<job-id>/` 生成，原始用户文件只读：

```text
run/<job-id>/
  manifest.json                    # 原始标准/实验方案来源、版本、SHA256、语言、解析工具信息
  clauses.json                     # 条款层级及每段 PDF 物理页码
  requirements.json               # 工程原子要求，依 schemas/requirements.schema.json
  requirements-matrix.csv         # 标准要求矩阵（BOM CSV）
  report.md                       # 分别列明标准事实、翻译不确定性、工程建议
  review_queue.csv                # 无法核验/缺失/条件冲突
  glossary.json                   # 翻译术语表（如需要）
  translations/segments.json     # 双语段落逐块对齐（翻译模式）
  test_plan.json                  # 实验项目清单（实验审核）
  experiment_audit.json           # 标准 ↔ 实验方案审查判定（实验审核）
  experiment_audit.csv            # 审查台账及可复核理由
  reverse_coverage.csv             # 每个实验项目的要求映射，包括未映射项目
  remediation_plan.md             # 实验方案整改建议，区分“要求”与“建议”
  changes.csv                     # 多版对比（如需要）
  traceability.csv                # 条款→设计→测试→证据（如需要）
  study-workspace/source/*.md     # tutor-setup 的独立工作区（如需要）
```

- 保留用户提供的源文件引用路径与 SHA256；**不将标准正文复制到公开项目或远程服务**。
- `source_location` 的 PDF 页码为原始文件从 1 起的物理页码；如有纸质印刷页码放 `printed_page`。
- 字段模型参阅 `schemas/`；对应脚本只做一致性检查，不能证明“符合标准”。
- V2.1 人工记录统一为 `reviewer`、`reviewed_at`、`approval_evidence`；来源核验为 `source_review`，正式审签为 `review_record`，不得由模型填造。旧夹具仅作 V2 兼容性结构测试。
- 可运行入口、引用型 annotations 和多页 spans 见 [runtime-contract.md](runtime-contract.md)。CSV/Markdown 是当前实际导出格式。
