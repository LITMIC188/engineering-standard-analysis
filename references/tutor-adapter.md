# tutor-setup 低耦合接入

- 保留 `C:\Users\Administrator\.agents\skills\tutor-setup\SKILL.md` 本机现有内容，不修改其文件。
- 先读取本机实际 `SKILL.md`，确认输入格式、依赖、产物目录、环境变量和运行方式；若无法读取，应声明此适配为预案。
- 由 ESA 生成 `study-workspace/source/`：仅包括已清楚分类的概念、带原文页码/条款定位的段落摘要、术语（原语言 + 中文），必要时附已知非规范性教学解释。
- 不将完整用户持有标准上传公开网络，不在公开仓库发布完整译文；仅在用户授权的本地工作区生成教学资料。
- 避免在 tutor 的工作目录中混入分析工程的 `pyproject.toml` / `package.json` 等，以免某些 tutor-setup 版本误判为代码仓库模式。
- 在独立 `study-workspace/` 执行 tutor-setup，其输出 StudyVault 不可逆向修改 ESA 的标准要求矩阵，学习题答案也不当作原始标准证据。
- 能力不可用时保留 `study-workspace/source/*.md` 与说明，并让用户自行调用其已安装版本。

## 本机接口核对（2026-10-10）

已读取上述本机 Skill，确认 Document Mode 接受 PDF/文本/Markdown/HTML/EPUB 文件，显式选定 source/output 优先于自动模式识别；中间文件应在所选输出 `.tutor-work/`，不修改用户现有笔记。该 Skill 是指令入口，不提供可假定的 Python RPC。

V2.1 用 `esa.py study --requirements <audit>/requirements.json --out <new-study-workspace>` 生成审核后原料和 `handoff.json`，只包含 `approved` + 来源已核实 + 记录完备的条目，并重新核验原源哈希与多页引用。此步骤不生成 StudyVault，不声称已运行 tutor。显式调用本机 tutor 时选择 **Document Mode**、`<study-workspace>/source/` 与 `<study-workspace>/StudyVault/`，然后执行其模板和质量检查。未经审签的条目在 handoff.excluded_ids；全部未审时 source 为空。
