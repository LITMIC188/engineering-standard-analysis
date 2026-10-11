# Obsidian 受控文件交接

## B-规范-01｜作用域与默认值
### 字段定义

| 字段名 | 类型 | 必填性 | 示例值 |
|---|---|---|---|
| 作业编号（job_id） | 字符串(string) | 必填 | 作业编号=synthetic-001 |
| 知识库根目录（vault_root） | 字符串(string) | 必填 | 知识库根目录=用户确认的本机绝对路径 |
| 目标作用域（target_scope） | 字符串(string) | 必填 | 目标作用域=工程知识/标准A/版本1 |
| 源文件哈希（source_sha256） | 字符串(string) | 必填 | 源文件哈希=本机实际源文件SHA256 |
| 预演模式（dry_run） | 布尔(boolean) | 必填 | 预演模式=true |

### 最小模板

共用外壳与属性映射见 [obsidian-mapping.md](obsidian-mapping.md)，机器 schema 见 `ESA_LOCAL/schemas/obsidian_publish.schema.json`。按接口元数据、公共输入、payload、result 的统一顺序交接；接口是本包适配器名称，不是第三方 Skills 原生命令。

### 实施约束

调用前读取 doctor 指向的本机三个 SKILL.md。`VAULT_ROOT` 必须是本机实际目录，不能是 Git URL。明确授权的目标相对路径为白名单；禁止 `..`、绝对子路径、链接越界、文件名碰撞。默认 `dry_run=true`，输出只在 RUN 内 staging。未确认真实 Vault 时，使用 RUN 内合成测试 Vault，不猜测真实目标。完整标准及译文不自动上传远端。

## B-调用-01｜门禁和接口顺序
### 字段定义

| 步骤编号 | 调用方 | 被调用Skill | 输入 | 输出 | 失败分支 |
|---|---|---|---|---|---|
| B-调用-01 | ESA 适配器 | 内部门禁 | 冻结源、要求、发布策略 | 门禁记录 | blocked |
| B-调用-02 | ESA 适配器 | obsidian-markdown 文件规范 | B-接口-02 render_obsidian_markdown | staging 的原文/要求/授权附件 | blocked |
| B-调用-03 | ESA 适配器 | obsidian-bases 文件规范 | B-接口-03 render_obsidian_base | 标准要求总览.base | blocked |
| B-调用-04 | ESA 适配器 | 本地预检 | 全部staging文件和哈希清单 | 格式、坏链、路径、附件记录 | blocked |
| B-调用-05 | ESA 适配器 | 本地事务 | 已授权白名单、快照及差异 | 写入清单 | rolled_back |
| B-调用-06 | ESA 适配器 | obsidian-cli | B-接口-04 verify_obsidian_publish | 回读及退出码 | pending_cli_validation |
| B-调用-07 | ESA 适配器 | 发布确认器 | 写入清单、真实CLI回读 | 发布或恢复清单 | rolled_back |

### 最小模板

在 ESA_LOCAL 执行，request 内所有 RUN/Vault 路径需换为本次实际完整路径：

```powershell
python -X utf8 scripts/doctor.py --check-cli --out run/<new-job>/doctor.json
python -X utf8 scripts/obsidian_render.py run/<job>/render-request.json
python -X utf8 scripts/obsidian_verify.py run/<job>/verify-request.json
python -X utf8 scripts/obsidian_publish.py run/<job>/publish-request.json
```

### 实施约束

实际写入必须显式 `dry_run=false` 和 `allow_write=true`，同时确认环境变量 `OBSIDIAN_VAULT_ROOT` 与请求根目录一致。严格 CLI 策略在写入前检查可用性与运行实例；缺 CLI 留 staging。允许离线本地写入的策略只可返回 pending，不能称验证成功。已有不同内容默认 WRITE_CONFLICT，输出差异待人工合并；相同内容幂等处理仍不跳过要求的回读。恢复只涉及事务写入的文件，不能覆盖事务后用户自行变更的内容。

## B-异常-01｜状态与错误
### 字段定义

统一结果为 `ok/blocked/retryable/pending_cli_validation/rolled_back`，错误对象为 `code/message/retryable/details`。`ok=false` 与 blocked/pending/rolled_back 一致，不能返回成功标记掩盖门禁或未完成验证。

### 最小模板

SOURCE_NOT_VERIFIED：源/底稿变化、关键审核未闭环；PATH_OUTSIDE_VAULT：路径越界；BASE_YAML_INVALID：Base不合法；LINK_TARGET_MISSING：坏链或附件缺失；WRITE_CONFLICT：已有内容变更；PARTIAL_WRITE：写入或恢复不完整；CLI_UNAVAILABLE：未安装/未运行/运行实例无法验证。

### 实施约束

记录元数据和哈希，不写正文到日志。YAML 静态解析及合成 CLI mock 只证明文件和异常处理，不能代替真实 Obsidian Reading View/Bases UI 的验收。真实 UI 验收在已授权目标 Vault 中实际打开、筛选和回读后另行登记；未执行明确标 pending。
