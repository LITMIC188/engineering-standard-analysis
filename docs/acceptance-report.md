# V2.4 本地优化验收记录

本次依据用户提供的 A/B/C 总方案修改工作目录中的 Skill，使用 skill-creator 规范和本机三个 Obsidian Skills 的实际指令。基线为 `3ef67a20180f6fd49461f78cf16dd716989028a7`，开发分支为 `codex/esa-obsidian-v2.4`。本报告记录程序行为；合成测试中的审核人、数字、标准号和方案均是测试资料，不代表真实标准审核或认证。

## 修改与验收映射

| 规范项 | 实现与验证位置 | 本地结果/边界 |
|---|---|---|
| C-修改-01～04 | `ocr_space_restore.py`、`heading_registry.py`、`reconstruct_source.py`、`verify_source.py`；source/layout/workflow tests | raw 与校订候选分层、标题追溯、精确原文/哈希和库存冻结；未知几何、缺图、未审关键问题阻断 |
| C-修改-05～06 | `render_full_articles.py`、`layout_tables.py`；source/layout tests | 稳定 ID 重排全文，源文与译文状态分开；复杂表格保留 unknown，不宣称自动复原全部结构 |
| C-修改-07～08 | `validate_translation.py`；translation cues/validation extended tests | 数字、单位、公式与比较符核对；否定/例外提示；真实异常不可用词法例外豁免 |
| C-修改-09～13 | `esa.py`；audit edge/independent audit/runtime tests | 规范义务、逐方案评估、受审组合、多来源段落、全局覆盖与风险因子；未决维度保留 unknown |
| C-修改-14～15 | requirements/test_plan schemas、`json_io.py`、`migrate_schema_v2.py`、`validate_run.py`；migration tests | 拒绝重复键，保留旧格式，迁移不沿用旧 approved；版本显式映射仍需审核 |
| C-修改-16～17 | `doctor.py`、`parser_adapters.py`、`translate_dispatch.py` | 本地结构导入与实际依赖检测；Docling/MinerU/TQC 未安装，不声称执行其后端 |
| C-修改-18 | 三个 Obsidian scripts、publish schema、integration/independent publish/workflow tests | B 公共外壳、Markdown/Bases staging、路径/哈希/冲突、写入/回读失败回滚；真实应用验收待完成 |
| C-修改-19 | `.github/workflows/ci.yml`、全部回归 tests | 已配置 Windows/Linux CI；远端 CI 尚未运行 |
| C-修改-20～21 | tutor/output/runtime/quality/source/Obsidian references、`SKILL.md`、`agents/openai.yaml` | 已审知识交接、全文交付和条件分支；不假设跨 Skill RPC，不自动调用 tutor |

## 数据迁移与使用

Skill 版本为 2.4；既有 clauses/requirements/test_plan 的 `schema_version` 仍为 2.0。新增源文冻结和 Obsidian 接口为 1.0。旧输入优先保留；显式迁移到新文件并保存日志，旧 approved 降回待审。source_spans 兼容旧单位置格式和现代带 sequence 的格式。新增库存、引用闭环、风险与来源字段缺失时全局审核不能通过。

新作业选择全新的 `run/<job-id>`。默认 `dry_run=true` 会生成独立 staging，不会写 Vault。真实写入需要明确 Vault、目标范围、环境路径匹配以及 CLI 预检；草稿要求只能进入独立 draft 范围。已有不同内容拒绝覆盖。失败回滚以本事务实际写入文件和哈希为准，遇外部修改报告冲突并保留用户内容。

## 验证记录

最终命令、退出码、测试数量与校验结果见 `evidence/final-validation.json`；完整测试日志见 `evidence/final-tests.log`。基线原有 41 项测试通过；最终 119/119 项通过。交付包在全新解包目录再次通过 119/119 项，日志见 `evidence/package-clean-tests.log`。最终包含独立负例及从真实合成文件提取开始的端到端测试。

测试只使用虚构文本/合成 PDF 和临时 Vault。真实 CLI 回读在测试中使用受控替身验证失败处理，不等于已验证用户运行中的 Obsidian。PyYAML 静态解析不证明 Bases 在真实应用中的渲染效果。skill-creator 格式校验不证明标准或译文正确。

## 待完成与默认处理

- 本机缺 Obsidian CLI，未提供实际 Vault：状态保留 `pending_cli_validation`，仅交付 staging 能力。后续在明确授权的测试范围验证实际 CLI、附件、Bases 视图和应用界面。
- 未提供实际原标准、专业人工审核记录、产品适用范围和实验大纲：不生成真实标准 approved，不作产品符合结论。
- Docling、MinerU、translation-quality-codex 未安装：仅支持离线结构文件/译文文件协议和缺依赖报告，后续按授权安装并验证实际后端。
- 远端 PR、GitHub CI 与公开/私有发布尚未执行：本次交付本地可审查源码、差异文件与 ZIP，不上传标准、译文或附件。

发布包不包含 `run/`、第三方临时验证依赖、用户标准全文或个人 Vault。校验和随 ZIP 交付。原输入方案和用户 Vault 均未修改。
