# 第三方技能路由（8 个原有 + 4 个翻译 + tutor-setup）

**接入方法**：本文件提供适配映射，并不代表第三方项目已经在用户机器安装。先读取对应项目实际 `SKILL.md`，确认 GitHub 版本、许可证、依赖、联网、输出契约与命令。允许通过脚本/本地文件交接；不假定跨 Skill API 可用。

| 技能 / 项目 | GitHub | 作用 | 默认/按需 |
|---|---|---|---|
| Docling | https://github.com/docling-project/docling | 数字PDF版面/表格结构化 | 默认文档解析 |
| MinerU | https://github.com/opendatalab/MinerU | OCR、复杂图文表格 | 扫描及困难页面 |
| doc-query | https://github.com/doculent/community | 条款定位/多文档查询 | 按需 |
| doc-extract | https://github.com/doculent/community | 技术参数抽取 | 解析模式 |
| doc-compare | https://github.com/doculent/community | 新旧版本差异 | compare |
| Traceability Matrix | https://github.com/peterbamuhigire/chwezi-sdlc-documentation | 需求追溯思想/矩阵 | 设计验证/实验审查 |
| iso-standards-readiness | https://github.com/K-Dense-AI/scientific-agent-skills | 13485/14971 管理体系证据 | 仅 QMS |
| MinerU Document Explorer | https://github.com/opendatalab/MinerU-Document-Explorer | 多文件检索 | 大规模文件库 |
| translation-quality-codex | https://github.com/WenhaoLiu0218/translation-quality-codex | 分块术语优先+译审+审计锚点 | **外文标准默认** |
| document-translate-preserve-format | https://github.com/lijiafengs/document-translate-preserve-format | OOXML格式保真译本/参考版 | 有可编辑DOCX/PPTX/XLSX时 |
| academic-paper-translator | https://github.com/zhaoshutiao/academic-paper-translator | 长文分块+页码标识 | 按需可选 |
| translate-book | https://github.com/deusyu/translate-book | 书籍体量增量翻译/合并检查 | 超长文档可选，不默认 |
| tutor-setup | https://github.com/bssm-oss/tutor-skills-codex | Obsidian 学习包 | 仅学习分支 |

## 核心协作契约
- 本框架的 `clauses.json` + `requirements.json` 是**工程层标准化交换格式**；第三方输出先经适配，不直接粘贴为工程事实。
- 翻译质量引擎按**原文块 ID**输出译文后，再映射至 `source` 与 `clause_id`。不得将第三方默认的“流畅润色”规则凌驾于标准规范强度和单位保留之上。
- 格式保真工具的输出是阅读用翻译件，不替代可核验的官方原始 PDF。PDF 保版式重排风险须报告。
- Document Explorer 是检索器，不能证明“未找到”即“不存在”；全量检查必须走章节/附录覆盖清单。
- Test Plan 审查是**框架内自定义工作流**，Traceability Matrix 提供方法借鉴，但现有 8 个技能没有被证实具备一键判定实验方案是否符合 ISO/JIS 的能力。
- `iso-standards-readiness` 不提供产品标准具体试验限值。
- `tutor-setup` 本机 `SKILL.md` 可能与 Github 版本不同：以现场本地版本为准；不能读取时仅输出准备好的学习原料，不声称已调用。

## V2.1 实际接入状态

| 原工具类别 | 本包实际可运行入口 | 第三方后端状态 |
|---|---|---|
| Docling | `local_parser.py` 本地数字 PDF/OOXML 文本降级 | 未安装、未执行；不含 Docling JSON 专用导入器 |
| MinerU | 空白页/扫描件标缺失，保留本地 OCR 路由 | 未安装、未执行；无 OCR 模型自动下载 |
| doc-query | `esa.py query` 已验证来源的块内查询 | 本地替代；未接社区工具执行接口 |
| doc-extract | `prepare` + 引用驱动 annotations + `full-analysis` | 本地结构化替代；语义抽取由 Codex/审核者完成 |
| doc-compare | `compare` 稳定 ID 字段/文本比对 | 本地替代；不推定技术等效或加严/放宽 |
| Traceability Matrix | 审查 `--design` + `traceability.csv` | 框架内实现；未执行第三方代码 |
| iso-standards-readiness | `qms-readiness` 指令路由 | 未接执行后端；须提供实际 Skill 与体系证据 |
| MinerU Document Explorer | `corpus-query` 本地显式文件关键词检索 | 本地降级；无向量库/Explorer 服务 |
| translation-quality-codex | `adapters.py prepare/import` 的真实 S-ID 文件协议 | 已实现文件适配；未安装上游 Skill，无翻译 API |
| 其他三种翻译 Skill | 格式/文档长度路由，整表保留与超长块提示 | 未安装、未执行，尚无格式保真/全书自动翻译适配 |
| tutor-setup | 已核对本机 Document Mode，`study` 原料 + handoff | 文件交接已实现；未自动调用，不覆盖原 Skill |

已知源码接口依据见 [adapters.md](adapters.md)。其他项目保留原有候选网址，但没有逐一审计源码/许可证；使用前须核实，不能把本表当第三方完整集成清单。
