# 研究论文获取（Acquire Research Papers）

Acquire Research Papers 是一个 Agent skill 和确定性命令行工具，用来获取论文和管理本地论文库。Codex、Claude Code、Kiro IDE 和 Kiro CLI 共用同一个 skill：

- 根据 DOI 或出版社正式页面获取已知论文；
- 按指定期刊/会议、年份、主题和配额建立可审计的论文集；
- 为相近工作、观点证据、Related Work 或创新 gap 分析准备并开展文献调研；
- 审计、更新、导入和整理本地 PDF/BibTeX，使用可审阅的变更计划和备份；
- 按作者查漏论文，明确区分身份、出版日期和来源覆盖证据。

每项完成的获取都必须形成经过身份核验的一对文件：出版社托管的 PDF 和出版社导出的原始 BibTeX。Crossref、OpenAlex 和 Semantic Scholar 可以发现候选并补全元数据，但不能代替正式文件。本项目不使用论文镜像，不让模型生成引用，也不绕过出版社访问控制。

[安装](install.md){ .md-button .md-button--primary } [快速开始](quick-start.md){ .md-button } [最新版本](https://github.com/EnosElinsa/acquire-research-papers/releases/latest){ .md-button }

## 选择适合的工作流

| 你的任务 | 工作流 | 最终结果 |
| --- | --- | --- |
| 已有 DOI 或出版社正式链接 | `fetch` | 一对经过核验的 PDF/BibTeX，或明确可操作的访问结果 |
| 需要机构访问或切换学校 | `config setup ieee` → `config ieee login/doctor` | 命名隔离档案、默认人工登录，以及分开的认证和下载诊断 |
| 已有 PDF/BibTeX 文件夹 | `library audit/update/import/organize` → `library apply` | 版本证据、配对文件名、原始引用字节、带哈希的变更计划和备份 |
| 需要作者论文列表或本地查漏 | `discover author` | 正式发表、Early Access 和预印本分组，以及身份歧义和来源覆盖说明 |
| 要从指定 venue、年份和主题中建立论文集 | `discover corpus` → Agent 评审 → `review corpus` → `acquire corpus` | 覆盖证据、冻结选集、正式文件以及人工/重试队列 |
| 出版社要求用户在授权浏览器中操作 | `manual-fetch`（整个人工下载队列用 `--queue`） | 接管用户下载的正式文件，核验身份后放入预留交付位置 |
| 命令运行时间超过 Agent 的命令超时 | `--background <任务目录>` → `job status`（`job list` 查看全部任务） | 命令在独立进程中运行；status 报告进度和最终结果 |
| 要找相近工作、观点引用、Related Work 或验证 gap | `discover research` → `review research` → `acquire research` → `evidence research` | 引用图、冻结的最相近论文、经过核验的全文和 claim 级证据报告 |
| 明确需要把 PDF 转成 Markdown | `export-md` | 按要求导出成功的 MinerU 结果；普通论文获取不会产生 Markdown |

论文集流程被明确分成四个阶段：

```text
检索范围与配额
    → 枚举期刊/会议 × 年份
    → 补全元数据并评审标题 + 摘要
    → 冻结最终论文清单
    → 获取正式 PDF/BibTeX
        ├─ delivered
        ├─ manual_required
        └─ retryable
```

当前执行 Agent 是这条工作流的一部分。CLI 负责确定性校验、断点记录、冻结清单和正式文件获取；Agent 负责把用户要求转成显式输入，并作出可记录、可复查的语义评审决定。

## 独立能力与组合

身份解析、发现、元数据补全、精确集合合并/比较、Agent 评审、冻结选集、获取、本地核验、独立 PDF 解析、全文证据验证、论文库操作与结构化导出可独立运行。原 corpus/research/author 入口继续兼容。参见[能力契约](https://github.com/EnosElinsa/acquire-research-papers/blob/main/skills/acquire-research-papers/references/capabilities.md)及[组合示例](https://github.com/EnosElinsa/acquire-research-papers/blob/main/skills/acquire-research-papers/examples/README.md)：已知列表、主题论文集、作者查漏、本地库维护、Related Work、gap 分析、显式章节。每个示例附输入、预期结果、恢复与限制；不增加内核任务类型或 Agent 编排器。

新评审使用 `schema_version: 2`，`reviewer` 与 `executor.host` 记录实际宿主，模型/版本仅在已知时记录。旧 Codex v1 记录仍可读取，原字节和哈希不变。能力命令可用 `--run`，`arp run status --run <目录>` 汇总状态；旧工作流继续使用原清单及恢复命令。独立 `parse` 无需 BibTeX，但保留用户文件的来源可信度；结构化 `export --format markdown` 与全文 `export-md` 区分。

## 下一步

- 第一次使用：先[安装](install.md)，再[只配置当前任务需要的能力](configuration.md)，然后按[快速开始](quick-start.md)操作。
- 要建立有边界的论文集：阅读[论文集检索](corpus.md)和[自动获取](acquisition.md)。
- 要核查相关工作或创新性：阅读[文献调研](research.md)。
- 要判断某个来源是否适合当前任务：阅读[来源支持](sources.md)和[可信边界与限制](trust.md)。
