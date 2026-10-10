# engineering-standard-analysis

V2.1 Codex Skill：本地工程标准双语解析、实验方案差距审查与可追溯学习材料交接。

Skill 入口：[SKILL.md](SKILL.md)。完整运行契约：[references/runtime-contract.md](references/runtime-contract.md)。

## 安装

下载 [dist/engineering-standard-analysis-v2.1.zip](dist/engineering-standard-analysis-v2.1.zip)，校验 [SHA256SUMS](dist/SHA256SUMS)，将其中 `engineering-standard-analysis/` 放到一个 Skill 根目录。Windows 可选择 `%USERPROFILE%\.agents\skills` 或 `%USERPROFILE%\.codex\skills`；二选一，避免重复安装，不覆盖已有同名目录。

也可将本仓库克隆到所选 Skill 根目录下的 `engineering-standard-analysis/`。Skill 名称为 `engineering-standard-analysis`，调用示例：

```text
使用 $engineering-standard-analysis，读取本地标准及现有实验方案，输出逐条要求、差距矩阵和整改建议。
```

## 本地运行

文本、CSV、DOCX、XLSX 路径使用 Python 标准库；数字 PDF 需要本机已有 `pypdf` 或 `pdftotext`。PDF 演示还需要 `reportlab`；缺少依赖时可显式使用 Markdown 演示。不自动安装系统组件、下载 OCR 模型或调用外部翻译 API。

```powershell
python -X utf8 scripts/esa.py --help
python -X utf8 scripts/demo.py --out run/demo-check --format md
python -X utf8 -m unittest discover -s tests -v
```

审查入口 `audit-test-plan` 使用带原文引用的 `clauses.json`、`annotations.json` 和 `plan-annotations.json`，契约与完整示例见运行文档。自动提取页/章节候选块后，Codex/审核者建立原子要求及方案映射；不声称已完成全标准语义抽取。

## 当前能力与边界

- P0：本地解析、来源 SHA256/条款/物理页码或非 PDF 位置、TQC S-ID 双语文件适配、数字/单位/比较符/部分公式检查、13 维实验方案审查、双向覆盖与整改矩阵。
- P1：要求矩阵、稳定 ID 的版本字段/文本差异、设计验证追溯、CSV/Markdown 报告。
- P2：显式多文件关键词检索、超长块提示与整表保留、经审签知识的 tutor Document Mode 原料交接。

八类第三方工程工具当前提供路由/本地替代入口，尚未安装执行其后端。TQC 已实现文件协议适配，但没有上游 Skill 或翻译 API 后端；其他翻译 Skill、扫描 OCR、格式保真翻译、全书翻译和向量检索仍需适配。详见 [工具状态](references/skill-routing.md) 与 [适配说明](references/adapters.md)。本包不包含这些第三方源码。

## 验证

开发验收：41 项自动化测试通过，Skill Creator 官方验证通过，英文/日文虚构 PDF 端到端检查完成，输出 JSON Schema 通过，并完成独立使用测试。严格翻译检查会对未人审的演示译文返回非零，这是预期门禁；不得为了通过检查伪造审核记录。

没有真实 ISO/JIS/IEC 标准或实际实验大纲包含在此仓库。演示与测试夹具均为虚构，测试专用审核元数据不是实际审签。无法核实的翻译、条款和实验条件保持未决；`aligned` 仅表示已建模字段的方案文本一致，不代表实际试验完成、产品合格或认证。`study` 只交接已批准知识，不自动运行或覆盖 `tutor-setup`。
