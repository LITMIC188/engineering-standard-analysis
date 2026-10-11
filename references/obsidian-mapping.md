# Obsidian mapping adapter

This adapter implements B-接口-02 (`render_obsidian_markdown`), B-接口-03 (Bases generation within rendering), and B-接口-04 (`verify_obsidian_publish`). The publisher is the internal transactional writer described in B-调用-05; its private command wrapper is `publish_obsidian_bundle`.

The public interface object keeps the B field sequence: `interface_id`, `interface_name`, `job_id`, `schema_version`, `vault_root`, `target_scope`, `source_sha256`, `dry_run`, `payload`; result order is `ok`, `status`, `output_files`, `details`, followed on errors by `error: {code,message,retryable,details}`. Error logs contain paths, event codes, counts, and hashes only; they never contain note bodies or standard quotations.

## Field mapping

| 来源字段/来源路径或作用域 | 目标字段/目标位置或作用域 | 转换规则 | 必填性 | 示例 |
|---|---|---|---|---|
| `RUN/manifest.json.job_id` | `04_要求/*.md` frontmatter `esa_job_id` | 原样复制 | 必填 | `作业编号=ESA-DEMO-001` |
| `RUN/requirements.json.standard_id` | frontmatter `esa_standard_id` | 原样复制，不猜测 | 必填 | `源标准编号=TEST-STD-001` |
| `RUN/requirements.json.edition` | frontmatter `esa_edition` | 字符串保存 | 必填 | `源标准版本=TEST-1` |
| `RUN/verified_source.json.source_sha256` | frontmatter `esa_source_sha256` | 必须等于接口哈希 | 必填 | `源文件哈希=<64位SHA256>` |
| `RUN/requirements.json.requirements[].requirement_id` | `04_要求/<requirement_id>.md` / `esa_requirement_id` | 稳定 ID；重复 ID 阻断 | 必填 | `要求编号=DEMO-REQ-001` |
| `RUN/requirements.json.requirements[].clause_id` + `titles_registry.headings[].title` | frontmatter `esa_clause_id`、正文标题 | 标题必须从哈希关联的登记表取用，ID 不充当原文标题 | 必填 | `条款编号=X.1` |
| `RUN/requirements.json.requirements[].source.pdf_page` | `esa_pdf_page`、来源追溯 | 逐项复制；不生成不存在的 PDF embed | 必填 | `物理页码=1` |
| `RUN/requirements.json.requirements[].review_status` | `esa_review_status` | 原样复制；approved 必须有 review_record | 必填 | `审核状态=draft` |
| `RUN/requirements.json.requirements[].requirement_level` | `esa_requirement_level` | 枚举原样复制 | 选填 | `要求性质=mandatory` |
| `RUN/requirements.json.requirements[].source.quote` | 原文证据区 | 原样引用源语，不以译文补写 | 选填 | `原文证据=冻结源摘录` |
| `RUN/verified_source.json.article_path` | `VAULT_TARGET/01_原文.md` | 校验 `article_sha256` 后复制 | 必填 | `源语全文=01_原文.md` |
| `payload.attachments[].source_path/sha256` | `VAULT_TARGET/<target_path>` | 相对路径，字节 hash 匹配后复制 | 选填 | `附件路径=assets/page-001.jpg` |
| 生成笔记 frontmatter | `VAULT_TARGET/标准要求总览.base` | Bases 限定实际要求目录、job_id、standard_id；approved 视图再筛 approved | 必填 | `视图名称=要求总览` |

The generated frontmatter and `.base` are JSON objects, which are valid YAML 1.2 documents. The adapter validates those generated documents with the standard library. It validates requirements against the required fields and enums in the repository's existing `schemas/requirements.schema.json`; it does not claim an external JSON Schema validator ran.

## Frozen source gate

`verified_source.json` must contain `source_sha256`, `source_complete`, `review_status`, `source_review`, `article_sha256`, `source_file`, `article_path`, `clauses_sha256`, `heading_registry_sha256`, an empty `blockers` list, a reviewed `checklist`, and all six `expected_inventory` domains. `source_review` must contain `reviewer`, `reviewed_at`, and `approval_evidence`; `source_complete` must be true and `review_status` must be `source_checked`. The source file's byte hash, the canonical clauses hash, the canonical rendered source article, and the canonical titles registry hash are recomputed. Requirement quotes, block IDs, clause IDs, editions, source file/hash/page/locator/page kind, and registered source titles are matched back to those clauses. `approved` requirements also need `source_verified`, a valid `source_review`, and an approval `review_record`.

When `translations_path` is supplied, also supply `article_manifest_path`; the adapter rerenders translated and bilingual articles from `segments.json`, verifies their review states and bytes against `article_manifest.json`, then stages them. Unreviewed translation content stays marked draft and production policy may require an approved state.

## Staging and publish

`dry_run=true` still materializes the complete staging bundle under the selected RUN directory so it can be reviewed; `vault_written` stays false. Staging is bound to job, scope, source, clauses, heading registry, and per-file SHA256, and is written only after every staged target is conflict-checked. Publishing performs a fresh render and compares the whole staging manifest before either dry-run success or a write. A vault transaction requires both `dry_run=false` and `payload.allow_write=true`, `OBSIDIAN_VAULT_ROOT` equal to `vault_root`, approved requirements by default, and staged paths wholly under `target_scope`. Forced CLI validation checks `obsidian help` and an explicit vault-root probe before writing, uses `vault=<name>` and `path=<vault-relative-path>`, and rolls back only files that still match the hashes this transaction wrote. Existing differing files cause `WRITE_CONFLICT`; same hashes are idempotent. Runtime logs contain paths, codes, counts, and hashes, never note bodies.

Example invocation: `python scripts/obsidian_render.py request.json`, then `python scripts/obsidian_publish.py request.json`. Request field order must follow B-接口. `python scripts/obsidian_verify.py request.json` performs local link checks in dry-run; CLI readback is only claimed when it actually executes and matches hashes.

The automated tests use temporary vaults and synthetic content. They cannot prove Obsidian reading-view rendering or Bases UI behavior; that remains a manual UI verification step.
