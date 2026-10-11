# engineering-standard-analysis

V2.4 本地开发版：原文核验、源语/中文/双语全文、实验方案差距审查与 Obsidian 文件发布适配。

入口是 [SKILL.md](SKILL.md)，使用 `$engineering-standard-analysis`。以冻结源语原文为事实来源；外文解析与专业中文翻译可从同一底稿条件并行，中文原文跳译。自动结果保持草案，真实来源审核和工程审签分别记录，不自动认定产品合格或认证。

## 使用与安装

将完整目录放入一个 Codex Skill 根目录，保留已有同名目录，避免重复安装。当前修改目标是工作区目录，没有自动安装到用户全局 Skills，也没有修改第三方 Skills。

```powershell
python -X utf8 scripts/doctor.py --check-cli
python -X utf8 scripts/esa.py --help
python -X utf8 scripts/demo.py --out run/<new-demo> --format md
python -X utf8 -m unittest discover -s tests -v
```

Python 标准库支持文本/CSV/DOCX/XLSX和自有 JSON 格式发布文件。数字PDF使用已有 `pypdf` 或 `pdftotext`；PDF演示需 `reportlab`。完整 JSON Schema 校验需本地 `jsonschema`；外来非JSON YAML可用本地 PyYAML。运行脚本不会自动安装组件、下载 OCR 模型或联网翻译。

## 运行说明

- [本地运行与证据契约](references/runtime-contract.md)：旧入口、原子引用、多段方案来源、审查组、引用闭环、版本映射及显式迁移。
- [原文流水线](references/source-pipeline.md)：OCR候选、几何布局、标题注册、完整性清单、冻结及全文交付。
- [Obsidian 属性与接口](references/obsidian-mapping.md)、[发布工作流](references/obsidian-workflow.md)：要求笔记、Bases索引、默认staging、哈希清单、冲突拒绝、受控写入及回滚。
- [质量门禁](references/quality-gates.md)：源文、翻译、工程判断与发布状态分开核验。
- [输出契约](references/output-contract.md)、[第三方状态](references/skill-routing.md)：文件位置及已实现/未运行后端的边界。
- [开发验收报告](docs/acceptance-report.md)：测试证据、方案条目对应、迁移和仍需真实环境验收的事项。

Docling/MinerU 仅提供本地探测和导出结构的文件导入，不声称已运行解析后端。TQC仍是文件交接协议，没有内置翻译API。Obsidian三技能是已读取的本机指令规范，适配器是本包脚本；不假设跨技能RPC。CLI缺失或运行实例不明时返回pending，不能把合成mock/静态YAML通过写成应用内验收。

## 发布包和验证边界

V2.1原包保留于 `dist/`；[V2.4验收包](dist/engineering-standard-analysis-v2.4.zip) 和 [SHA256](dist/engineering-standard-analysis-v2.4.zip.sha256) 同样位于 `dist/`。本地完整差异补丁另存于工作目录的 `ESA_V2.4_2026-10-11/`。打包仅包含维护的Skill源码、模板、合成测试和开发文档，排除所有用户作业、标准正文、Vault内容和本地测试依赖。

没有真实 ISO/JIS/IEC 标准或实际产品实验方案随包发布。测试夹具的审签字段明确属于合成测试，不是真实审核。`aligned` 只表示可核对字段的方案文本一致；章节/附录/表图/规范引用全局完整性独立判断。`study`只交接真实approved知识，不自动运行tutor或覆盖学习库。
