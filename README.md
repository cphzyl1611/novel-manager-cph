# novel_repo_manager

本项目是一个本地 TXT 小说仓库管理工具的 MVP。它面向“先扫描、再报告、最后人工确认”的安全工作流，用 SQLite 记录扫描结果、重复组、错误和移动操作。

## 明确不做的功能

本项目只管理本地 TXT 小说文件，不实现、不规划、不预留任何在线抓取功能。

这里的“在线抓取”包括但不限于：

- 自动从网站搜索小说。
- 自动下载小说正文。
- 自动抓取最新章节。
- 自动抓取封面、简介、评论。
- 自动解析小说网站页面。

项目保留并聚焦的能力是本地 TXT 扫描、本地去重、本地更新检测、本地质量评分、本地分组、本地标签、本地报告，以及可选的 Calibre 导出。

## 安全原则

- 永远不直接删除任何文件。
- 永远不覆盖任何文件，目标重名时自动追加后缀。
- 文本清洗只用于分析，不修改原始 TXT。
- 危险操作先 `--dry-run`，真正移动必须显式 `--confirm`。
- 移动文件会写入 `db/novel_repo.sqlite` 的 `operations` 表和 `logs/operations.log`。
- 扫描单个文件失败不会中断任务，错误写入 `scan_errors`。
- 第一版只做精确重复：`raw_sha256` 和 `clean_sha256`。

## 安装依赖

```bash
python -m pip install -r requirements.txt
```

要求 Python 3.10+。SQLite 使用 Python 标准库，不需要额外数据库服务。

## 初始化仓库

```bash
python run.py init --repo "D:/NovelRepo"
```

会创建 `incoming/`、`library/`、`archive/`、`review_duplicates/`、`reports/`、`db/`、`cache/`、`config/`、`logs/`、`exports/` 等目录，创建数据库和默认配置文件。已有配置文件不会被覆盖。

## 检查环境

```bash
python run.py doctor --repo "D:/NovelRepo"
```

检查目录、数据库和配置文件是否可用。

## 扫描 library

```bash
python run.py scan --repo "D:/NovelRepo" --area library
```

只扫描变化文件：

```bash
python run.py scan --repo "D:/NovelRepo" --area library --changed-only
```

限制扫描数量：

```bash
python run.py scan --repo "D:/NovelRepo" --area library --limit 100
```

## 扫描 incoming

```bash
python run.py scan --repo "D:/NovelRepo" --area incoming
```

扫描两个区域：

```bash
python run.py scan --repo "D:/NovelRepo" --area all
```

## 查找重复

```bash
python run.py find-duplicates --repo "D:/NovelRepo" --mode exact --area all
```

输出：

- `reports/duplicate/duplicate_report_YYYYMMDD_HHMMSS.html`
- `reports/duplicate/duplicate_report_YYYYMMDD_HHMMSS.json`

报告只给出 `keep`、`review`、`archive_candidate`，不会建议删除。

## 近似重复检测

近似重复检测用于发现“文件名不同但内容大部分相同”的本地 TXT 小说。它不同于 exact duplicate：exact 只看 `raw_sha256` / `clean_sha256` 完全一致；near 会综合标题相似度、作者、章节标题重合率、SimHash、正文分块 Jaccard 和长度合理性。

该功能不会删除文件、不会移动文件、不会修改 TXT 原文。默认只生成报告：

```bash
python run.py find-duplicates --repo "D:/NovelRepo_Test" --mode near --area all
```

同时生成精确重复和近似重复报告：

```bash
python run.py find-duplicates --repo "D:/NovelRepo_Test" --mode all --area all
```

包含低置信可疑候选：

```bash
python run.py find-duplicates --repo "D:/NovelRepo_Test" --mode near --include-low-confidence
```

显式写入 `duplicate_groups` / `duplicate_group_members`：

```bash
python run.py find-duplicates --repo "D:/NovelRepo_Test" --mode near --apply
```

写入作品组候选：

```bash
python run.py find-duplicates --repo "D:/NovelRepo_Test" --mode near --apply --apply-to-work-groups --min-score 0.90
```

`--apply` 只写 SQLite 数据库，不移动、不删除、不覆盖小说文件。`--apply-to-work-groups` 只会处理高置信、无风险候选；作者冲突、低置信、章节覆盖异常、疑似新版都会标记为 `manual_review`。

如果报告中出现 `possible_update_version`，说明它可能是新版或更完整版本，不应按普通重复处理，后续应进入本地 update detection 流程人工确认。

近似重复诊断用于排查 near duplicate 没命中的原因。它会输出候选对、分项分数、过滤状态、过滤原因和标题规范化样例，默认只生成诊断报告，不写数据库：

```bash
python run.py diagnose-near --repo "D:/NovelRepo_Test" --query "高考陪读"
python run.py diagnose-near --repo "D:/NovelRepo_Test" --query "温暖"
python run.py diagnose-near --repo "D:/NovelRepo_Test" --query "传奇老灯"
```

输出：

- `reports/diagnostic/near_diagnostic_YYYYMMDD_HHMMSS.html`
- `reports/diagnostic/near_diagnostic_YYYYMMDD_HHMMSS.json`
- `reports/diagnostic/near_diagnostic_YYYYMMDD_HHMMSS.md`

## 查看质量报告

```bash
python run.py quality-report --repo "D:/NovelRepo" --area all
```

输出：

- `reports/quality/quality_report_YYYYMMDD_HHMMSS.html`
- `reports/quality/quality_report_YYYYMMDD_HHMMSS.json`

质量报告按低分优先展示广告多、乱码高、章节异常、疑似截断的文件。

## 查看扫描错误

```bash
python run.py error-report --repo "D:/NovelRepo"
```

输出：

- `reports/errors/scan_error_report_YYYYMMDD_HHMMSS.html`
- `reports/errors/scan_error_report_YYYYMMDD_HHMMSS.json`

## 汇总 Markdown 报告

`summary-report` 会读取重复报告、质量报告和扫描错误报告的 JSON 文件，生成一个统一的 Markdown 汇总，方便在 VS Code、Typora、Obsidian 或 GitHub Markdown 中快速查看整理结果。

自动汇总最新报告：

```bash
python run.py summary-report --repo "D:/NovelRepo"
```

指定具体 JSON 报告：

```bash
python run.py summary-report --repo "D:/NovelRepo" \
  --duplicate-report "D:/NovelRepo/reports/duplicate/duplicate_report_xxx.json" \
  --quality-report "D:/NovelRepo/reports/quality/quality_report_xxx.json" \
  --error-report "D:/NovelRepo/reports/errors/scan_error_report_xxx.json"
```

输出文件位于：

- `reports/summary/summary_report_YYYYMMDD_HHMMSS.md`

该命令只读取已有报告并生成 Markdown，不修改 TXT 文件，不修改已有报告，不移动文件。

## 查看书库

`list-books` 从 SQLite 的 `books` 表读取已扫描小说，用表格展示基础信息。该命令只读，不修改文件。

```bash
python run.py list-books --repo "D:/NovelRepo"
```

常见过滤示例：

查看低质量小说：

```bash
python run.py list-books --repo "D:/NovelRepo" --poor-only --limit 50
```

搜索某个关键词：

```bash
python run.py list-books --repo "D:/NovelRepo" --query "关键词"
```

按广告行排序：

```bash
python run.py list-books --repo "D:/NovelRepo" --sort ad_line_count --desc --limit 30
```

只看 `library`：

```bash
python run.py list-books --repo "D:/NovelRepo" --area library
```

只看存在问题的文件：

```bash
python run.py list-books --repo "D:/NovelRepo" --problem-only
```

## 查看单本小说详情

`inspect-book` 用于查看某一本书的扫描结果、质量原因和章节预览。该命令只读，不修改文件。

按 book_id 查看：

```bash
python run.py inspect-book --repo "D:/NovelRepo" --book-id 123
```

按关键词列出候选书：

```bash
python run.py inspect-book --repo "D:/NovelRepo" --query "书名关键词"
```

显示所有章节：

```bash
python run.py inspect-book --repo "D:/NovelRepo" --book-id 123 --chapters
```

显示完整 hash：

```bash
python run.py inspect-book --repo "D:/NovelRepo" --book-id 123 --show-hash
```

## 报告索引和打开报告

这些命令只读取 `reports/` 目录或生成索引文件，不修改小说文件，不修改已有 JSON/HTML 报告，不移动文件。

列出最近报告：

```bash
python run.py list-reports --repo "D:/NovelRepo"
```

只列出重复报告：

```bash
python run.py list-reports --repo "D:/NovelRepo" --type duplicate
```

每种类型只看最新一个：

```bash
python run.py list-reports --repo "D:/NovelRepo" --latest-only
```

打开最新报告：

```bash
python run.py open-latest-report --repo "D:/NovelRepo"
```

默认优先打开最新 `summary_report_*.md`，其次是重复、质量、错误 HTML 报告。如果系统环境不适合打开文件，会输出路径供手动打开。

生成报告索引：

```bash
python run.py report-index --repo "D:/NovelRepo"
```

输出文件：

- `reports/index.html`
- `reports/index.md`

## 作品分组 work_group

`work_group` 用于表示同一部小说的不同 TXT 版本，例如原始重复文件、清洗后内容一致的文件、标题和作者规范化后完全一致的不同版本。它为后续本地近似重复和本地更新检测打基础。

`group-books` 默认只生成分组候选报告，不写入数据库，不移动小说文件：

```bash
python run.py group-books --repo "D:/NovelRepo_Test"
```

报告输出：

- `reports/group/group_report_YYYYMMDD_HHMMSS.html`
- `reports/group/group_report_YYYYMMDD_HHMMSS.json`

显式写入数据库：

```bash
python run.py group-books --repo "D:/NovelRepo_Test" --apply --min-confidence 0.95
```

`--apply` 只写 `work_groups` 和 `book_group_members` 等数据库分组表，不移动、不删除、不覆盖小说文件。低置信或作者冲突的候选会标记为 `manual_review`，不会自动合并。

只预览写入计划：

```bash
python run.py group-books --repo "D:/NovelRepo_Test" --dry-run
```

查看作品组：

```bash
python run.py list-groups --repo "D:/NovelRepo_Test"
```

查看某个作品组：

```bash
python run.py inspect-group --repo "D:/NovelRepo_Test" --group-id 1
```

人工设置主版本：

```bash
python run.py set-primary --repo "D:/NovelRepo_Test" --group-id 1 --book-id 123
```

人工合并作品组：

```bash
python run.py merge-groups --repo "D:/NovelRepo_Test" --source-group-id 2 --target-group-id 1
```

拆分错误分组：

```bash
python run.py split-group --repo "D:/NovelRepo_Test" --book-id 123
```

这些人工命令只修改数据库分组记录，并写入 `operations` 表用于追溯，不会移动或修改 TXT 文件。

## 更新检测 check-updates

`check-updates` 用于比较 `incoming` 中的新文件和 `library` 中的旧文件，判断 incoming 是否可能是新版、完整版、补章版或更高质量版本。

本阶段只生成报告，不执行替换，不移动、不删除、不覆盖、不修改 TXT。`replace_recommended` 只是建议，`manual_review` 需要人工看，`reject` 不建议更新。真正替换以后会单独实现 `apply-updates`，并且必须归档旧版。

默认生成报告：

```bash
python run.py check-updates --repo "D:/NovelRepo_Test"
```

按关键词检查：

```bash
python run.py check-updates --repo "D:/NovelRepo_Test" --query "高考陪读"
```

包含 reject 候选：

```bash
python run.py check-updates --repo "D:/NovelRepo_Test" --include-rejected
```

保存候选到数据库：

```bash
python run.py check-updates --repo "D:/NovelRepo_Test" --save-candidates
```

`--save-candidates` 只写 `update_candidates` 表，不动小说文件。

报告输出：

- `reports/update/update_report_YYYYMMDD_HHMMSS.html`
- `reports/update/update_report_YYYYMMDD_HHMMSS.json`
- `reports/update/update_report_YYYYMMDD_HHMMSS.md`

## 应用更新 apply-updates

`apply-updates` 根据 `check-updates` 生成的 `update_report_*.json` 执行安全更新应用。它只处理 `recommendation = replace_recommended` 的候选，`manual_review` 和 `reject` 会被跳过。

执行规则：
- 旧版从 `library/` 移动到 `archive/replaced/`
- 新版从 `incoming/` 移动到 `library/`
- 不删除文件
- 不覆盖文件，重名会自动改名
- 不修改 TXT 内容
- 移动前后校验 `raw_sha256`
- 写入 `operations` 表、`logs/operations.log` 和 `logs/apply_updates_YYYYMMDD_HHMMSS.json`

必须先 dry-run：

```bash
python run.py apply-updates --repo "D:/NovelRepo_Test" --report "D:/NovelRepo_Test/reports/update/update_report_xxx.json" --dry-run
```

确认无误后才执行真实移动：

```bash
python run.py apply-updates --repo "D:/NovelRepo_Test" --report "D:/NovelRepo_Test/reports/update/update_report_xxx.json" --confirm --yes-i-understand
```

`--confirm` 必须同时带 `--yes-i-understand`，否则命令会拒绝执行。`--dry-run` 和 `--confirm` 不能同时使用。

可选过滤参数：

```bash
python run.py apply-updates --repo "D:/NovelRepo_Test" --report "D:/NovelRepo_Test/reports/update/update_report_xxx.json" --dry-run --min-same-work-score 0.90 --min-coverage 0.95 --max-quality-drop 3
```

如果发生误操作，请先查看 `logs/apply_updates_*.json` 和 `logs/operations.log`，其中记录了旧版来源路径、归档路径、新版来源路径、新版入库路径、hash 和处理状态，可据此手动恢复。

## 批量重命名建议 rename-plan

`rename-plan` 用于根据 `books` 表里的书名、作者、状态、质量和标签信息生成规范文件名建议。它只生成 HTML / JSON / Markdown 报告，不真正重命名文件，不移动、删除、覆盖 TXT，也不修改 `books.current_path`。

默认只处理 `library`：

```bash
python run.py rename-plan --repo "D:/NovelRepo_Test"
```

选择命名风格：

```bash
python run.py rename-plan --repo "D:/NovelRepo_Test" --style title-author-status
python run.py rename-plan --repo "D:/NovelRepo_Test" --style title-author
python run.py rename-plan --repo "D:/NovelRepo_Test" --style title-only
```

`title-author-status` 默认规则：
- 有作者：`书名 - 作者 [状态].txt`
- 无作者：`书名 [状态].txt`
- 只有显式加 `--include-unknown-author` 才会写入 `未知作者`

```bash
python run.py rename-plan --repo "D:/NovelRepo_Test" --include-unknown-author
python run.py rename-plan --repo "D:/NovelRepo_Test" --max-status-count 2
```

按关键词或范围生成：

```bash
python run.py rename-plan --repo "D:/NovelRepo_Test" --query "高考陪读"
python run.py rename-plan --repo "D:/NovelRepo_Test" --area all --include-unchanged
```

报告输出：

- `reports/rename/rename_plan_YYYYMMDD_HHMMSS.html`
- `reports/rename/rename_plan_YYYYMMDD_HHMMSS.json`
- `reports/rename/rename_plan_YYYYMMDD_HHMMSS.md`

报告会标记 `rename_recommended`、`no_change`、`manual_review`，并显示文件名冲突、作者可疑、来源前缀清理、章节范围清理、缺作者、低质量、乱码风险、目标名截断等原因。`manual_review` 不自动处理，因为这些情况需要人工确认。以后如果要真实重命名，应单独实现 `apply-renames`，并且必须 dry-run + confirm。

## 标签系统

标签用于题材、状态、质量、来源和自定义分类。一本文本小说可以有多个标签；标签只写 SQLite 数据库，不修改 TXT 原文，不移动、不删除、不覆盖文件。

常用命令：

```bash
python run.py list-tags --repo "D:/NovelRepo_Test"
python run.py list-tags --repo "D:/NovelRepo_Test" --category genre
python run.py create-tag --repo "D:/NovelRepo_Test" --name "克苏鲁" --category genre --description "克苏鲁题材"
python run.py tag-book --repo "D:/NovelRepo_Test" --book-id 123 --tag "玄幻"
python run.py tag-book --repo "D:/NovelRepo_Test" --book-id 123 --tag "克苏鲁" --create
python run.py untag-book --repo "D:/NovelRepo_Test" --book-id 123 --tag "玄幻"
python run.py books-by-tag --repo "D:/NovelRepo_Test" --tag "玄幻"
```

删除标签必须先 dry-run：

```bash
python run.py delete-tag --repo "D:/NovelRepo_Test" --tag "克苏鲁" --dry-run
python run.py delete-tag --repo "D:/NovelRepo_Test" --tag "克苏鲁" --confirm
```

删除标签只会删除 `tags` 和 `book_tags` 关系，不会删除小说文件。

自动标签只做保守规则，不做 AI 分类：

```bash
python run.py auto-tag --repo "D:/NovelRepo_Test" --dry-run
python run.py auto-tag --repo "D:/NovelRepo_Test" --apply
```

`auto-tag` 默认等同 dry-run；只有 `--apply` 才写入 `book_tags`，自动标签的 `source=auto`。标签和阅读状态没有单独报告，会汇总在 `summary-report` 的“标签与阅读状态汇总”中。

## 阅读状态

`reading_status` 用于阅读管理，默认支持：

- 未读
- 正在读
- 已读
- 弃书
- 想重读
- 待整理

设置和查询：

```bash
python run.py set-status --repo "D:/NovelRepo_Test" --book-id 123 --status "已读"
python run.py books-by-status --repo "D:/NovelRepo_Test" --status "未读"
python run.py list-books --repo "D:/NovelRepo_Test" --status "待整理"
```

如果确实需要自定义状态：

```bash
python run.py set-status --repo "D:/NovelRepo_Test" --book-id 123 --status "搁置" --allow-custom-status
```

阅读状态只修改 `books.reading_status`，并写入 `operations` 表和操作日志，不修改 TXT 文件。

## 暂存重复文件

先 dry-run：

```bash
python run.py stage-duplicates --repo "D:/NovelRepo" --report "reports/duplicate/duplicate_report_xxx.json" --dry-run
```

确认无误后执行：

```bash
python run.py stage-duplicates --repo "D:/NovelRepo" --report "reports/duplicate/duplicate_report_xxx.json" --confirm
```

只会移动报告里 `suggested_role` 为 `archive_candidate` 或 `review` 的文件到 `review_duplicates/`。移动前后会校验 `raw_sha256`，并写入 `operations` 表、`logs/operations.log` 和 `logs/stage_duplicates_apply_YYYYMMDD_HHMMSS.json`。

## dry-run 和 --confirm 的区别

`--dry-run` 只展示将要移动的源路径和目标路径，不改动文件，不写操作记录。

`--confirm` 才会真正移动文件。即使执行移动，也不会删除文件，也不会覆盖目标文件。

## 为什么不会删除文件

MVP 中没有删除命令。重复文件只会被移动到 `review_duplicates/`，保留人工复核空间。所有移动都要显式 `--confirm`，并且有数据库和日志记录可追溯。

## 数据库备份

```bash
python run.py backup-db --repo "D:/NovelRepo"
```

备份文件位于 `db/backups/novel_repo_YYYYMMDD_HHMMSS.sqlite`。

## 常见问题

乱码怎么办：先查看 `error-report` 和质量报告。如果文件进入 `scan_errors`，可以手工转换为 UTF-8 后重新扫描；如果只是低质量，先保留原文件，按报告人工复核。

章节识别不准怎么办：第一版只识别常见章节格式，报告中的缺章、倒序和重复章节是辅助信号，不自动修改文件。

广告清理误判怎么办：清洗只用于计算 `clean_sha256` 和质量指标，不会改原始 TXT。可以调整 `config/cleaning_rules.yaml` 后重新扫描。

报告怎么看：重复报告优先看每组的 `keep` 和 `archive_candidate`；质量报告优先看低分项；错误报告看文件路径、错误类型和建议处理。

如何先用几十本小说测试：新建一个临时仓库，只复制几十本到 `library/`，按“初始化、扫描、查重、质量报告、dry-run 暂存”的顺序验证。

## 最小验收测试集建议

```text
NovelRepo/
├─ library/
│  ├─ A.txt
│  ├─ A_copy.txt
│  ├─ A_utf8.txt
│  ├─ A_ad.txt
│  ├─ A_bad_encoding.txt
│  ├─ A_missing.txt
│  └─ B.txt
└─ incoming/
```

验收目标：

1. `A.txt` 和 `A_copy.txt` 被 raw hash 判重。
2. `A.txt` 和 `A_utf8.txt` 被 clean hash 判重。
3. `A_ad.txt` 广告行被统计，质量分降低。
4. `A_bad_encoding.txt` 进入 `scan_errors` 或低质量。
5. 不删除任何文件。
6. 生成 duplicate_report、quality_report、scan_error_report。
7. dry-run 不移动文件。
8. `--confirm` 后只移动到 `review_duplicates/`。
9. `operations` 表有记录。

## 应用重命名 apply-renames

`apply-renames` 根据 `rename-plan` 生成的 JSON 执行安全改名。它只处理 `action=rename_recommended` 的项目，不处理 `manual_review`、`no_change`、冲突项或高风险项。

安全边界：

- 不删除文件；
- 不覆盖文件；
- 不跨目录移动；
- 不修改 TXT 内容；
- 不处理 `target_name_conflict`；
- 默认不会真实执行，必须先 dry-run；
- 真正执行必须同时使用 `--confirm --yes-i-understand`；
- 每个成功改名都会写入 `operations` 表和 `logs/operations.log`；
- 每次批量执行都会生成 `logs/apply_renames_YYYYMMDD_HHMMSS.json`。

先预览：

```bash
python run.py apply-renames --repo "D:/NovelRepo_Test" --report "D:/NovelRepo_Test/reports/rename/rename_plan_xxx.json" --dry-run
```

确认无误后执行：

```bash
python run.py apply-renames --repo "D:/NovelRepo_Test" --report "D:/NovelRepo_Test/reports/rename/rename_plan_xxx.json" --confirm --yes-i-understand
```

如果误操作，可以根据 `logs/apply_renames_*.json` 中的 `current_path` 和 `target_path` 手动恢复原文件名。

## 改名后元数据刷新

`apply-renames` 只负责安全改文件名和更新路径字段。它不会重新扫描正文，也不会自动刷新 `title_raw`、`title_norm`、`author_raw`、`author_norm`。如果改名后 `list-books` 里仍看到旧标题噪声，可以使用 `refresh-metadata` 根据当前文件名刷新数据库元数据。

该命令只修改 SQLite 元数据，不读取 TXT 全文，不计算 hash，不解析章节，不修改文件。

先预览：

```bash
python run.py refresh-metadata --repo "D:/NovelRepo_Test" --area library --dry-run
```

确认无误后写入数据库：

```bash
python run.py refresh-metadata --repo "D:/NovelRepo_Test" --area library --apply
```

## 健康检查 post-rename-check

`post-rename-check` 用于检查改名后数据库和文件系统的一致性，包括路径是否存在、`file_name` 是否匹配当前路径、文件名和 `title_norm` 是否仍有明显噪声、`repo_area` 是否和路径基本一致、hash 字段是否为空，以及 work_group 引用是否仍有效。

它是只读检查，不修改文件，也不修改数据库。报告输出到 `reports/health/`。

```bash
python run.py post-rename-check --repo "D:/NovelRepo_Test"
```

旧的 `logs/operations.log` 如果已经出现乱码，不影响 SQLite 中的核心数据。后续操作日志统一以 UTF-8 写入，并使用 `ensure_ascii=False` 保留中文。

## 图形界面 GUI

GUI 使用 PySide6，第一版主要用于查看书库、生成报告、执行安全 dry-run 和查看日志。真实 `--confirm` 操作仍建议在命令行人工确认后执行。

安装依赖：

```bash
python -m pip install -r requirements.txt
```

启动：

```bash
python gui.py
```

GUI 布局包括左侧导航栏、顶部工具栏、主内容区和底部状态栏。首次启动后点击“选择仓库”选择 `NovelRepo` 目录；如果目录还没有 `config/db` 结构，GUI 会提示先用 CLI 执行 `init`。

第一版页面：

- 仓库总览：统计卡片、最近报告、最近操作、常用快捷命令；
- 小说列表：搜索、按 area/标签/阅读状态/质量过滤，查看单本书详情；
- 作品分组：查看 work_group 和成员，生成分组报告；
- 重复检测 / 更新检测 / 标签与状态 / 重命名建议：集中在工具执行页；
- 报告中心：查看、打开报告，刷新报告索引；
- 操作日志：查看 `operations.log` 和 apply 日志；
- 设置：保存默认仓库、area、命名风格、Python 路径等。

GUI 第一版不会直接执行危险确认操作。以下命令在 GUI 中只提供 dry-run：

- `apply-renames --dry-run`
- `apply-updates --dry-run`
- `stage-duplicates --dry-run`
- `refresh-metadata --dry-run`
- `auto-tag --dry-run`

如需真实执行 `--confirm` 或 `--apply`，请先在 GUI 中查看 dry-run 输出和报告，再回到命令行执行。

## GUI 易用性流程

GUI 已从单纯命令入口调整为任务流程界面。首次启动时会显示仓库向导：

- 新建小说仓库：选择目录后执行 `init`，创建 `library`、`incoming`、`reports`、`db`、`logs` 等目录；
- 打开已有仓库：选择已经初始化过的 NovelRepo 根目录；
- 导入普通 TXT 文件夹：选择普通 TXT 文件夹和目标仓库，GUI 只复制 TXT 到 `library`，不移动、不删除原文件，同名文件自动加后缀。

左侧流程页用于日常整理：

- 重复处理：运行 exact/near 去重，直接在 GUI 内查看重复组、成员、推荐保留和风险提示；
- 更新处理：查看 incoming 对 library 的更新候选，只能预览更新操作；
- 重命名计划：查看建议文件名、冲突、manual_review，预览改名操作；
- 健康检查：查看改名后的路径、标题元数据和 work_group 引用问题；
- 报告中心：仅作为历史 HTML/JSON/Markdown 报告中心。

GUI 中不提供删除和真实 `--confirm`，因为这些操作会改变文件位置或文件名。普通用户应先在 GUI 中查看结果和 dry-run 日志；真实执行仍需回到命令行确认。

## GUI 中文界面与安全删除

GUI 页面尽量使用中文术语，不直接暴露 `library`、`incoming`、`--dry-run`、`--confirm` 等底层参数：

- `library` 显示为“小说库”；
- `incoming` 显示为“新下载区”；
- `archive` 显示为“归档区”；
- `review_duplicates` 显示为“重复复核区”；
- `trash` 显示为“废弃区”。

GUI 中没有“永久删除”按钮。“删除小说”类操作实现为“移入废弃区”：

- 文件移动到仓库 `trash/`；
- 不永久删除；
- 不覆盖同名文件；
- 不修改 TXT 内容；
- 操作会写入 SQLite `operations` 表和 `logs/operations.log`；
- 同时生成 `logs/move_to_trash_*.json`；
- 可以根据日志手动恢复文件。

小说列表页支持：

- 打开小说；
- 打开所在文件夹；
- 复制路径；
- 添加标签；
- 设置阅读状态；
- 单本小说移入废弃区。

移入废弃区前会弹出中文确认框，默认建议先预览。真实移入废弃区只针对单本小说，并且不是永久删除。

## 第二阶段预留

数据库已预留 `work_groups`、`book_group_members`、`tags`、`book_tags`、`series`、`series_members`、`update_candidates`。第二阶段可继续做本地近似重复、本地版本更新检测、本地作品分组、本地系列管理、本地标签体系、更细的质量规则，以及可选的 Calibre 导出。

## 双端 Web 服务

NovelHub 是电脑端+手机端双端互联的小说管理 Web 服务。电脑端作为主仓库服务器，手机端通过局域网浏览器访问。

### 启动

```bash
python server.py --repo "D:/NovelRepo_Test"                    # 仅本地
python server.py --repo "D:/NovelRepo_Test" --host 0.0.0.0    # 开放局域网
```

手机浏览器访问 `http://<电脑IP>:8765`。

### 功能

- 首页书架（卡片式布局，响应式适配手机/平板/桌面）
- 搜索小说（书名、作者）
- 分组管理（对应 library 子文件夹）
- 在线阅读（点击卡片打开阅读视图）
- 更新候选概览

### 安全

- 默认只监听 127.0.0.1
- `--host 0.0.0.0` 时终端打印安全提示
- 所有文件路径限制在仓库目录下
- 不提供永久删除 API

详见 [docs/dual_end_novel_app_architecture.md](docs/dual_end_novel_app_architecture.md)。
#   n o v e l - m a n a g e r  
 
#   n o v e l - m a n a g e r - c p h  
 