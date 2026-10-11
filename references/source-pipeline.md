# 原文重建、冻结及全文交付

## C-实施-02｜保留提取底稿
### 字段定义

作用域 `ESA_LOCAL` = 本技能目录，`RUN` = 当前全新作业目录。`clauses.json` 保持 schema_version=2.0；原文块的 block_id、clause_id、source.file/sha256/pdf_page/page_kind/locator、quote/spans 是来源键。PDF物理页从1起，文本/OOXML只用真实locator，pdf_page=null。

### 最小模板

```powershell
python -X utf8 scripts/esa.py prepare '<actual-source>' --out run/<new-job>/prepared --standard-id '<confirmed-id>' --edition '<confirmed-edition>' --language en
python -X utf8 scripts/reconstruct_source.py run/<job>/prepared/extraction.json --clauses run/<job>/clauses.json --out-dir run/<job>/reconstruction
```

### 实施约束

prepare输出整页/章节候选，clause_id=UNRESOLVED需要原页复核后建立条款块，不能把候选视为语义抽取完成。reconstruction保留raw、bbox、阅读顺序、来源、OCR候选diff。明确词界才建议空格，未知词、单位、标准号、公式不静默改写。更正应有原页、修改前后、审核记录；候选本身不能升级原文事实。阅读顺序和几何原点未知时标unknown。跨页表/图区域只接受显式同源分组，未知单元格保留原图和待办，不猜参数。

`parser_adapters.py probe`只探测本机Docling/MinerU命令；`import`只读取已导出的结构JSON。实际后端执行、OCR模型和第三方Skill调用另行确认本机配置，不自动上传文件或下载模型。导入未知页码/格式拒绝，不默认page1。导入结构与原始文件逐页核验后才可参与冻结。

## C-实施-03｜标题和完整性冻结
### 字段定义

| 字段名 | 类型 | 必填性 | 示例值 |
|---|---|---|---|
| 来源清单（expected_inventory） | 对象(object) | 必填 | 来源清单={pages,chapters,normative_annexes,tables,figures,references} |
| 审核清单（checklist） | 数组(array) | 必填 | 审核清单=[{inventory_kind:chapters,inventory_id:4.1,status:reviewed}] |
| 源文审核（source_review） | 对象(object) | 必填 | 源文审核={reviewer,reviewed_at,approval_evidence} |
| 标题登记（heading_registry） | 对象(object) | 必填 | 标题登记={source_sha256,headings:[{heading_id,clause_id,title,block_id,source}]} |

### 最小模板

```powershell
python -X utf8 scripts/verify_source.py run/<job>/clauses.json run/<job>/prepared/extraction.json run/<job>/checklist.json --review-record run/<job>/actual-source-review.json --article run/<job>/reconstruction/02_Original_Reconstructed.md --inventory run/<job>/inventory.json --heading-registry run/<job>/reconstruction/clause_heading_registry.json --out run/<job>/verified_source.json
```

### 实施约束

清单六个域均须显式登记，空数组是经核验的“无该对象”，缺域是未知。每个登记对象有核验结果，遗漏页、附录、表图、来源跨度、关键OCR或标题使source_complete=false。原始文件SHA、实际提取/导入证据、条款canonical hash、标题登记hash与完整源语正文hash形成冻结链；任意文章不能冒充底稿。核验失败输出draft及blockers，不生成03_Original_Verified.md。原文完整冻结成功状态为source_checked；这不是approved工程解释或产品结论。新作业/新冻结版本拒绝覆盖已有文件。

审核记录必须由真实审核者提供，脚本只验证字段完备和可自动核对的证据，不能鉴定签名。扫描/复杂公式/表格需要本地实际OCR和逐页原图核验；结构JSON存在或raw候选可读并不等于已核验。当前无法核实的后端路径保持blocked，不用合成测试替代真实原页复核。

## C-实施-04｜条件并行和全文
### 字段定义

源语解析读取被冻结的条款；翻译只读取同一原文。`source_status` 与 `translation_status` 分开，中文原文跳中文翻译。`block_id` 唯一并精确覆盖，文章顺序由原条款序列决定，不按译文顺序重排原文。

### 最小模板

```powershell
python -X utf8 scripts/translate_dispatch.py run/<job>/clauses.json run/<job>/verified_source.json --out run/<job>/dispatch.json
python -X utf8 scripts/render_full_articles.py run/<job>/clauses.json --translations run/<job>/translations/segments.json --verified-source run/<job>/verified_source.json --out-dir run/<job>/articles
```

### 实施约束

dispatch输出工作包而非执行翻译后端；未冻结时不报告ready。TQC的prepare/import仍为文件协议。render将乱序译块按ID对齐，缺/多/重ID或来源漂移拒绝“完整译文”；未审段逐段草案标记。源语全文保持冻结字节，不因译文/阅读优化反写；变更需新冻结作业。`article_manifest.json`记录实际文章文件hash和两个审核状态，Obsidian发布重新核对。中文原文记录跳译原因、保留完整中文源文，不伪造外文译本。

合成端到端回归见 `ESA_LOCAL/tests/test_workflow_smoke.py`；其中人工记录仅属于明确标示的虚构夹具，不能用于真实作业。完整作业还需 [质量门禁](quality-gates.md) 和 [发布预检](obsidian-workflow.md)。
