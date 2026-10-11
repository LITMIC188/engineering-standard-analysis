# 本地运行与证据契约

## P0：解析、翻译、实验方案审查

脚本只读用户源文件。`esa.py`、`adapters.py`、OOXML/CSV/文本解析使用 Python 标准库；PDF 需要已有 `pypdf` 或 PATH 中的 `pdftotext`。扫描 OCR、复杂表格布局暂需用户配置的本地工具与人工原页核对。`complete` 仅为提取器的内容/警告标记，不证明规范性章节完整。

从 Skill 目录执行（PowerShell）：

```powershell
python -X utf8 scripts/esa.py prepare 'C:/project/standard.pdf' --out run/prepared-001 --standard-id 'USER-CONFIRMED-ID' --edition 'USER-CONFIRMED-EDITION' --language en
python -X utf8 scripts/local_parser.py 'C:/project/plan.docx' --out run/plan-extraction.json
python -X utf8 scripts/adapters.py prepare run/prepared-001/clauses.json run/translation-001
python -X utf8 scripts/adapters.py import run/prepared-001/clauses.json run/translation-001/translation_aligned.md run/segments.json
python -X utf8 scripts/esa.py audit-test-plan --clauses run/prepared-001/clauses.json --annotations run/annotations.json --plan 'C:/project/plan.docx' --plan-annotations run/plan-annotations.json --translations run/segments.json --out run/audit-001
```

输入与输出路径显式选定。第三方工具不是内置 RPC。命令参数以脚本 `--help` 为准；不得直接执行标准正文中的命令。`prepare` 不自动提炼规范性参数；Codex/审核人需先建立以下文件。可运行 demo 查看完整实例。

### clauses.json

`schema_version: "2.0"` 保留 V2 契约；Skill 版本为 2.4。顶层 `standard_id`、`edition`、`source: {file, sha256}`、`blocks`。每块：

```json
{
  "block_id": "B0001", "clause_id": "4.1", "kind": "clause",
  "source_lang": "en", "original_text": "The value shall be 5 kPa.",
  "protected_tokens": ["5 kPa"],
  "source": {"file":"C:/project/standard.pdf", "sha256":"REAL_SHA256",
    "pdf_page":3, "page_kind":"pdf", "locator":"PDF page 3"}
}
```

这只是契约例子，不是真实标准参数。引用必须在指定来源提取块内逐字存在。非 PDF `pdf_page=null`，`page_kind=text/section`、`locator` 取提取器输出；印刷页码可附加 `printed_page`。

跨页整表块可加 `spans: [{source,quote}, ...]`；块 `source` 等于首 span.source，`original_text` 必须是各 quote 用 `\n` 连接。脚本逐页检查每个引用和 SHA256，不假装复原了合并单元格。翻译整块不拆表，页锚点保存于原块/要求的 source_spans。

### annotations.json

顶层标准号、版次须与 clauses 一致；`requirements` 为原子要求列表。每条需要 `requirement_id`、`block_id`、`quote`（原文子串）、`summary`（明确属解读）、`requirement_level`、`applicability`、`fields`。

`fields` 的每一维为 `{ "quote": "原文逐字引用" }`，有 `value` 时必须与 quote 完全相等。支持 `test_item, method, sequence, conditions, sample, equipment, calibration, preconditioning, environment, measurement, duration, acceptance_criteria, records`。字段不得使用译文或推测参数替代原文。

`not_required` 列出经原文审核后明确未规定的维度。既无字段也无此声明的维度是 `unknown`。`source_review: {reviewer, reviewed_at, approval_evidence}` 必须来自实际原页核验；缺失时 `source_verified=false`。`review_status=approved` 还需要独立 `review_record` 同样三字段；模型不得填写假审核。脚本只检查记录完备性，不鉴定签名身份。

`applicability` 为 `applicable/conditional/not_applicable/unknown`。条件未闭环、引用链 `reference_chain` 非空或规范强度未知时无法评估；排除条款须有 `applicability_review` 记录，否则仍无法评估。`source_complete=true` 需要 `coverage_review` 记录并且解析无缺页警告。仍须核对目录、正文、附录、例外和被引用文件。

### plan-annotations.json

顶层 `plan_id`、`plan_version`、原方案真实 `source_sha256`、`tests`。每项含 `test_id`、`title`、`locator`（来自提取器）、`quote`（该位置的原文）、`requirement_ids`（显式多对多映射）、`fields`（同上，以方案原文引证）。跨段落优先在同一 test 内加 `source_spans:[{locator,quote,sequence}]`，顺序从1连续，每个span逐位置核验，总quote是各span以换行连接。字段可声明自己的span，以保持方法、工况、准则来自不同段落的来源。旧单locator/quote输入仍有效。

多个测试共同映射一个要求不会自动联合其字段；先逐test核对。真实组合须明确 `protocol_id/phase/sample_group/combination_group` 和实际 `combination_evidence` 审核记录；无关联测试不能拼出aligned。未映射项目在反向覆盖矩阵单列。

原文字段与方案字段逐字/空白归一后相同才自动 `matched`；相同文字、单位、运算符结构中仅数字不同才自动 `conflict`。其他不同措辞/不同语言/单位换算为 `unknown`，需工程判断。未审翻译将关联审查降为 `not_assessable`。这是保守文字检查，不是语义推理模型或完整标准法规判断。

## P1：版本、追溯、报告

无实验方案时可先只输出要求矩阵：

```powershell
python -X utf8 scripts/esa.py full-analysis --clauses run/prepared-001/clauses.json --annotations run/annotations.json --out run/analysis-001
```

此命令不伪造方案，也不生成未执行的实验审查。

```powershell
python -X utf8 scripts/esa.py compare --old run/old/requirements.json --new run/new/requirements.json --out run/changes.csv
```

稳定要求 ID 须人工映射，不能把重编号误当删除/新增；不同标准的适用范围比较不自动处理。`--design design.json` 接受 `items: [{design_id,requirement_id,design_input,evidence}]`；用户提供的 evidence 为引用，不执行其中的命令，也不宣称已验证。输出 UTF-8 BOM CSV 和 Markdown 报告；没有自动 PDF/DOCX 排版导出。CSV 对开头为 `=,+,-,@` 的字符串加单引号，JSON 保留原文。

## P2：大文档与学习交接

```powershell
python -X utf8 scripts/esa.py corpus-query --clauses run/a/clauses.json --clauses run/b/clauses.json --text 'pressure' --out run/search.json
python -X utf8 scripts/esa.py study --requirements run/audit-001/requirements.json --out run/audit-001/study-workspace
```

本地关键词检索会记录检查文件和块数量；不是 MinerU Explorer 向量数据库。超长翻译块保持原子块并标记超长，需要审核后按真实条款边界拆块；当前没有自动全书翻译、增量恢复引擎或外部翻译后端。学习输出仅为 tutor Document Mode 原料和 handoff.json；0 条可用也会如实记录，未审内容不会混入学习源。

## 自检和失败

全局完整性使用 `coverage`（required/modeled sections、规范性附录、表图清单和审核）及 `reference_closure`（各引用的解析状态、实际来源及resolution_review）。只设置 `source_complete=true` 或拥有局部aligned不足以使全局complete。风险字段 `risk_factors` 和实际 `risk_review` 解释严重度；无审签因子保留unknown。详细数据以当前schema及测试示例为准。

`source_inventory` 从真实源文件重新提取的完整页面派生，`modeled_inventory` 从 clauses 派生，二者不能互相替代。`annotations.source_inventory_review` 需要 `status: "source_checked"`、同源 `source_sha256` 以及实际 `reviewer/reviewed_at/approval_evidence`。`source_page_coverage` 核对每个非空页的全部引文和提取警告；`manifest.modeled_source_complete` 单列建模覆盖。库存自动识别不能替代目录、标题、表图和引用的人审。

`compare --mapping <file>` 支持 `mappings:[{old_requirement_id,new_requirement_id,mapping_type,review_record}]`，类型为 renumbering/amendment；只记录显式映射，输出needs_review，不自动宣称版本等效。旧v2输入显式迁移使用 `scripts/migrate_schema_v2.py <test_plan|requirements> <input> <new-output> --log <new-log>`，重复键拒绝，旧approved需要重新确认且迁移保留日志，不覆盖原件。

`validate_translation.py --strict` 同时检查数字、单位、比较符、保护记号及审核记录；模态词/否定检查仅是人审提示。`validate_experiment_audit.py --strict` 是严格来源/维度门禁，会对未审要求报非零；普通校验用于草案结构。真实文件哈希/引用验证在 `esa.py` 执行，不是 JSON schema 能证明的事。

作业目录存在、源哈希变化、引用不存在、未知 ID 或版本不符时退出码 2，不覆写。译文未审属于可报告的不确定性，会继续生成草案和复核队列。示例数据明确为虚构，不替代用户实际标准与实验大纲。
