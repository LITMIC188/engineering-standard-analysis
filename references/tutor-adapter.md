# tutor-setup 低耦合接入

- 通过 `scripts/doctor.py` 检测实际 `tutor-setup/SKILL.md`，保留本机现有内容，不硬编码其他机器用户名或修改该文件。
- 先读取本机实际 `SKILL.md`，确认输入格式、依赖、产物目录、环境变量和运行方式；若无法读取，应声明此适配为预案。
- 由 ESA 生成 `study-workspace/source/`：仅包括已清楚分类的概念、带原文页码/条款定位的段落摘要、术语（原语言 + 中文），必要时附已知非规范性教学解释。
- 不将完整用户持有标准上传公开网络，不在公开仓库发布完整译文；仅在用户授权的本地工作区生成教学资料。
- 避免在 tutor 的工作目录中混入分析工程的 `pyproject.toml` / `package.json` 等，以免某些 tutor-setup 版本误判为代码仓库模式。
- 在独立 `study-workspace/` 执行 tutor-setup，其输出 StudyVault 不可逆向修改 ESA 的标准要求矩阵，学习题答案也不当作原始标准证据。
- 能力不可用时保留 `study-workspace/source/*.md` 与说明，并让用户自行调用其已安装版本。

## 文件交接与知识链接

本机版本在实际调用前读取；显式选择 Document Mode、原料和输出目录，中间文件使用目标 `.tutor-work/`，不修改用户现有笔记。该 Skill 是指令入口，不提供可假定的 Python RPC。

V2.1 用 `esa.py study --requirements <audit>/requirements.json --out <new-study-workspace>` 生成审核后原料和 `handoff.json`，只包含 `approved` + 来源已核实 + 记录完备的条目，并重新核验原源哈希与多页引用。此步骤不生成 StudyVault，不声称已运行 tutor。显式调用本机 tutor 时选择 **Document Mode**、`<study-workspace>/source/` 与 `<study-workspace>/StudyVault/`，然后执行其模板和质量检查。未经审签的条目在 handoff.excluded_ids；全部未审时 source 为空。

Obsidian 要求笔记的 `esa_requirement_id` 与 handoff 的条目 ID 是稳定关联键。用户需要学习库链接时，从实际 publish_manifest 的已发布路径映射到 `[[真实相对路径|知识条目]]`；不存在的笔记不创建伪链接，未审或 pending 的内容不进入已审教材。先核实两个目录确属同一 Vault，再加入 wikilinks；链接和教材不得反向修改冻结要求。默认仅交接原料。
