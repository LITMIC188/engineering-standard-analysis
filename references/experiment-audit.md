# 现有实验/试验方案对标准要求的作业符合性审查

## 定义三类截然不同的结论
- **方案覆盖/作业一致性**：现有计划是否覆盖适用标准的项目、程序、测量、判定及记录要求。这是本模式主目标。
- **试验执行符合性**：需要实际执行记录、设备校准与状态、原始测量记录、偏差及签字，不得只靠试验方案推断。
- **产品性能符合性/认证**：需要实际测试结果、完整标准适用性和规定程序的正式审核；本 Skill 不自动发证或下结论。

## 输入契约
需取得（如有）：标准源 PDF 与确定版本、实验方案原始文件及版次、产品/配置与型号、拟测试样品和使用条件；有实际记录时作为**单独证据**提供。支持 Markdown、DOCX、PDF、CSV/XLSX 的解析路径，但调用实际可用工具处理格式，不强制假设已经安装。

## 审查顺序（必须按顺序构建证据）
1. 提取**适用范围**及规范性引用。跨 ISO/JIS/YY/GB 要先比对产品/版本/适用条件；不能认为国外标准必然完全适用于特定产品或地区。
2. 将每条标准试验要求拆分为原子要求：测试对象、试样与数量（**只在原文规定时**）、前处理、环境、介质、仪器精度/校准、参数/工况、顺序/循环、测量点/方法、持续时间、接受准则、记录、异常与复测规则（若有）。按标准原文逐项填，未知为 `null`。
3. 从现有实验方案抽取对应项；保存 `test_id`、方案页码/章节及原文摘要。若仅有测试名称，没有步骤/判定规则，只能给“信息不足”或“部分覆盖”，不可自动算符合。
4. 建立 `requirement_id` ↔ `test_id` 多对多关系，逐字段对照（方法、条件、样品、仪器、测量、判定、记录）。缺乏明示条款时不臆造要求。
5. 为每个适用要求生成 `experiment_audit.json` 的至少一条结论；允许没有 `test_id`，表示无映射。依据证据状态 `aligned`/`partial`/`missing`/`conflict`/`not_assessable`/`not_applicable`，并附证据、原因和补正项。
6. 审核结果基于**计划文件内容**而非模型主观判断。`aligned` 也仅代表已提供方案文本与所核对的标准要求一致，仍需人工审核；不能直接说明产品测试合格。
7. 输出 `remediation_plan.md`，按安全/关键参数风险及缺口优先级，逐项写：缺项→对应条款→拟调整步骤→负责人/证据状态（未给则保持空值）→复核动作；建议与原文要求必须分开。

## 结论标签
| 标签 | 含义 | 举例（非真实标准要求） |
|---|---|---|
| `aligned` | 在当前提供的计划文档里，覆盖所有已经列出并可验证的原子要求（仍需人工复核） | 条件、方法、判定和来源一致 |
| `partial` | 有对应项目，但关键字段缺失 | 只有“耐压测试”标题，没有操作参数 |
| `missing` | 适用原子要求没有映射的试验项目 | 标准要求未进入试验目录 |
| `conflict` | 方案与已核实标准明确冲突 | 已核实限值被改动 |
| `not_assessable` | 标准/方案依据不完整或 OCR/翻译未核实 | 引用标准缺失、条件未知 |
| `not_applicable` | 有明确不适用依据 | 条款仅针对本产品不具备的选装件 |

## 风险控制
- 当规范性要求和方案冲突，结论为 `conflict`，不要自动将方案改写为所谓“符合”。
- 标准中没有给出的抽样方法、顺序、试验时间等不必强行填值，区分建议和强制条款。
- 存在多个被引用标准时保留 `reference_chain` 并标为待核实，直到拿到相应原文。
- 发现重大安全试验条件缺失，标记 `critical` + `needs_human_review`，不要对未执行的试验给出“已通过”。
- 方案审查不能取代经认可的试验方法确认、法规/认证机构判断或有资质工程师复核。

## 审查结论前的双重覆盖控制
- 横向覆盖：所有适用标准原子要求至少一条审查记录；若 `missing`/`conflict`/`partial`/`not_assessable` 任一存在，整体不得表达“方案满足全部标准要求”。
- 纵向覆盖：即便一个 test_id 已映射 requirement_id，仍需逐项核对 method、conditions、sample、equipment、calibration、preconditioning、environment、measurement、duration、sequence、acceptance_criteria、records（标准未规定的维度标 `not_required`，而不是自动猜测）。
- `aligned` 必须至少一维 `matched` 且无 `missing`/`conflict`/`unknown` 的适用维度；仅对**所获完整标准条款与方案文档的文本一致性**有效。

## V2.4 证据组与全局门禁

先逐个test评估；方法、工况和准则分散于同一方案多个段落时，使用同一test的有序source_spans，而不是生成无关联测试并联合字段。需要联合多个测试时，明确相同protocol_id、phase、sample_group、combination_group，并保存各测试真实combination_evidence。保留全部映射test_ids及逐候选evaluations，不因未能组合而删除映射证据。

requirement_level与normative_nature共同决定audit_obligation。来源未核验、规范性质矛盾、适用条件或参考标准未闭环保持not_assessable；资料性说明不作为mandatory缺项。resolved引用须匹配实际引用文件和SHA及resolution_review，文件改变重新阻断。

severity取决于实际审签risk_factors及risk_review，并在risk_rationale写明推导；缺因子或unknown不自动降级。局部字段aligned和全局coverage.complete分别报告，整体结论不能只统计aligned数量。规范性附录、表图或引用库存缺失必须保留未闭环状态。严格审查校验会对现代证据契约重新计算aligned，不仅相信调用者给出的matched列表。
