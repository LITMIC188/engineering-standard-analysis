# Engineering Standard Analysis V2.4

## 更新

- 原文重建、正式标题注册、完整页面与章节/附录/表图/引用核验，以及同源哈希冻结。
- 按稳定 ID 生成源语、中文和双语全文；未审译文或数字/单位异常保持草稿。
- 实验方案逐测试、协议、阶段与样品组审查；无真实组合证据不能拼接为 aligned。
- 多段来源追溯、全标准覆盖、风险因子与显式版本映射；旧数据迁移保留日志。
- Obsidian Markdown/Bases staging、相对附件、哈希与冲突检查、事务回滚及 CLI 回读门禁。
- 修复 Windows 控制台中文输出和等价来源路径比较问题。

## 使用

下载 `engineering-standard-analysis-v2.4.zip`，按同名 `.sha256` 文件核对 SHA256。解压后的完整 `engineering-standard-analysis/` 目录作为 Skill 安装目录，使用 `$engineering-standard-analysis`。

默认只生成 staging。真实 Obsidian Vault/CLI/界面及 Docling、MinerU、TQC 后端仍需实际环境验收。测试使用合成标准、审核记录与临时 Vault，不构成真实标准审批、产品认证或试验完成证明。发布包不含用户标准、真实 Vault 或本机环境路径。

程序验证记录见 `docs/acceptance-report.md` 和 `docs/evidence/final-validation.json`；发布前通过 Windows/Linux、Python 3.12/3.14 四组 GitHub CI。
