# 研究论文获取（Acquire Research Papers）

[English](https://github.com/EnosElinsa/acquire-research-papers/blob/main/README.md)

[![CI](https://github.com/EnosElinsa/acquire-research-papers/actions/workflows/test.yml/badge.svg)](https://github.com/EnosElinsa/acquire-research-papers/actions/workflows/test.yml)
[![Weekly source check](https://github.com/EnosElinsa/acquire-research-papers/actions/workflows/source-check.yml/badge.svg)](https://github.com/EnosElinsa/acquire-research-papers/actions/workflows/source-check.yml)
[![Docs](https://github.com/EnosElinsa/acquire-research-papers/actions/workflows/docs.yml/badge.svg)](https://enoselinsa.github.io/acquire-research-papers/zh/)
[![Release](https://img.shields.io/github/v/release/EnosElinsa/acquire-research-papers)](https://github.com/EnosElinsa/acquire-research-papers/releases/latest)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/EnosElinsa/acquire-research-papers/blob/main/LICENSE)

Acquire Research Papers 是一个 Agent skill 和确定性命令行工具，用来获取论文和管理本地论文库。Codex、Claude Code、Kiro IDE 和 Kiro CLI 共用同一个 skill：

- 根据 DOI 或出版社正式页面获取已知论文；
- 按指定期刊/会议、年份、主题和配额建立可审计的论文集；
- 为相近工作、观点证据、Related Work 或创新 gap 分析准备并开展文献调研；
- 审计、更新、导入和整理本地 PDF/BibTeX，使用可审阅的变更计划和备份；
- 按作者查漏论文，明确区分身份、出版日期和来源覆盖证据。

**[文档站点](https://enoselinsa.github.io/acquire-research-papers/zh/)** · [最新版本](https://github.com/EnosElinsa/acquire-research-papers/releases/latest) · [更新记录](https://github.com/EnosElinsa/acquire-research-papers/blob/main/CHANGELOG.md) · [开发指南](https://github.com/EnosElinsa/acquire-research-papers/blob/main/CONTRIBUTING.md) · [使用帮助与反馈](https://github.com/EnosElinsa/acquire-research-papers/blob/main/SUPPORT.md) · [安全说明](https://github.com/EnosElinsa/acquire-research-papers/blob/main/SECURITY.md)

每项完成的获取都必须形成经过身份核验的一对文件：出版社托管的 PDF 和出版社导出的原始 BibTeX。Crossref、OpenAlex 和 Semantic Scholar 可以发现候选并补全元数据，但不能代替正式文件。本项目不使用论文镜像，不让模型生成引用，也不绕过出版社访问控制。

本 README 只是概要。完整指南、规范示例和输出说明见[文档站点](https://enoselinsa.github.io/acquire-research-papers/zh/)（另有 [English](https://enoselinsa.github.io/acquire-research-papers/) 版本）。

## 目录

- **开始使用：**[选择工作流](#选择适合的工作流) · [安装](#安装) · [首次使用](#首次使用只配置当前任务需要的能力) · [快速开始](#快速开始)
- **工作原理：**[论文集检索](#论文集检索实际如何工作) · [文献调研](#文献调研实际如何工作) · [来源支持](#来源支持与成熟度)
- **范围与项目：**[可信边界](#准确性与可信边界) · [当前限制](#当前限制) · [路线图](#后续路线图) · [开发](#开发与验证) · [引用](#引用)

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

当前执行 Agent 是这条工作流的一部分。CLI 负责确定性校验、断点记录、冻结清单和正式文件获取；Agent 负责把用户要求转成显式输入，并作出可记录、可复查的语义评审决定。

## 安装

普通用户通过标准 Skills 安装器安装，需要 Node.js/npm，无需克隆开发仓库或运行开发依赖同步：

```text
npx skills add EnosElinsa/acquire-research-papers --skill acquire-research-papers -a codex -g
```

需要 Python 3.11+ 和 [uv](https://docs.astral.sh/uv/)。使用安装器返回的实际 skill 目录；默认共享目录通常是 `~/.agents/skills/acquire-research-papers`：

```powershell
$skill = Join-Path $env:USERPROFILE ".agents/skills/acquire-research-papers"
python "$skill/scripts/arp.py" --help
python "$skill/scripts/arp.py" config status
```

启动器只使用 Python 标准库，根据 `runtime.json` 获取固定版本 wheel、校验 SHA-256，再通过 uv 安装到独立缓存。文件配置与核心命令支持 Windows/macOS/Linux；当前 IEEE 浏览器和旧 DPAPI 仍需要 Windows、PowerShell、Node.js，在 macOS 和 Linux 上 IEEE 论文进入人工下载队列。更新时重新运行同一条安装命令。从 v0.16.0 起，也可以用 `uv tool install acquire-research-papers` 从 PyPI 单独安装 CLI。其他宿主、`arp doctor`、用 `gh attestation verify` 核验发布文件以及从开发 checkout 迁移的方法见[安装](https://enoselinsa.github.io/acquire-research-papers/zh/install/)。

### 发布文件与手动安装

[v0.16.0 发布页](https://github.com/EnosElinsa/acquire-research-papers/releases/tag/v0.16.0)提供：

| 文件 | 用途 |
| --- | --- |
| `acquire-research-papers-skill-0.16.0.zip` | 解压后，将其中的 `acquire-research-papers/` 文件夹复制到新的 skill 目录。包含指令、参考资料、schemas、启动器和固定运行版本清单。 |
| `acquire_research_papers-0.16.0-py3-none-any.whl` | 用 `uv tool install <wheel-path>` 单独安装 CLI；也可将其绝对路径设置为 `ARP_LOCAL_WHEEL`，供启动器从本地加载。摘要校验仍然生效。 |
| `SHA256SUMS` | PowerShell 使用 `Get-FileHash <path> -Algorithm SHA256`，Linux 使用 `sha256sum <path>`，与清单核对下载文件。 |

不要把源码压缩包或开发 checkout 整体复制为 skill。启动和迁移问题见 [SUPPORT.md](https://github.com/EnosElinsa/acquire-research-papers/blob/main/SUPPORT.md)。

## 首次使用：只配置当前任务需要的能力

先检查哪些可选能力已经配置：

```powershell
python "$skill/scripts/arp.py" config status
```

该命令默认只返回能力布尔值，不会输出秘密值。`true` 表示本地已有配置，不代表远端 API 或出版社权限一定可用。Agent 应只引导配置当前任务真正需要的能力，再用有代表性的实际操作验证。

| 能力 | 何时配置 | 配置方式 |
| --- | --- | --- |
| 无需配置 | 公开 Crossref 发现；从 ACL、IJCAI、AAAI、NeurIPS、ICLR（2024 年起）、PMLR、CVF 和 USENIX 官方归档发现并获取；Springer 开放获取论文 | 不需要密钥 |
| Semantic Scholar | 需要带 key 的候选搜索、更高额度和第一轮 DOI 摘要补全 | `arp config setup semantic_scholar` |
| OpenAlex | 需要通过 OpenAlex 系列枚举 IEEE 或 ACM 会议（INFOCOM、ICC、GLOBECOM、SIGCOMM 等）、额外候选搜索或第二轮 DOI 摘要补全 | `arp config setup openalex` |
| IEEE | 需要本校 IEEE 访问；默认先人工登录，可另行启用支持的 CARSI 表单 | `arp config setup ieee` |
| Elsevier | ScienceDirect 人工接管前需要解析官方预期身份 | `arp config setup elsevier` |
| MinerU | 需要为内部全文分析解析 PDF，或明确要求导出 Markdown | `arp config setup mineru` |

秘密输入采用交互式、不回显提示。不要把密码、API key、token 或 Cookie 粘贴到聊天、Agent 消息、命令参数或仓库文件中。可编辑凭据文件和命名院校档案见[配置](https://enoselinsa.github.io/acquire-research-papers/zh/configuration/)。

## 快速开始

获取一篇已知论文：

```powershell
python "$skill/scripts/arp.py" fetch `
  --input "https://aclanthology.org/2024.acl-long.1/" `
  --output "C:\Research\papers"
```

只有 JSON 状态为 `delivered` 时才可以使用输出文件。只有题名、没有 DOI 或正式链接时，必须先经过发现流程；`fetch` 不会在多个同名或近似题名之间猜测。

论文集和文献调研从规范或 brief 开始，由当前 Agent 根据你的要求编写。`arp` 是 `python "$skill/scripts/arp.py"` 的简写：

```text
arp discover corpus --progress --spec corpus.yaml --output <corpus-run>
arp review corpus --run <corpus-run> --decisions <review-decisions.jsonl>
arp acquire corpus --selection <corpus-run>/selection-manifest.json --output <delivery>

arp discover research --brief research-brief.yaml --output <research-run>
arp review research --run <research-run> --decisions <research-review.jsonl>
arp acquire research --run <research-run>
arp evidence research --run <research-run> --records <evidence-review.jsonl>
```

可直接复制的完整论文集规范和调研 brief 见[快速开始](https://enoselinsa.github.io/acquire-research-papers/zh/quick-start/)。

## 论文集检索实际如何工作

论文集模式适合“指定这些 venue、这些年份，查找这些主题”的有边界任务。它先记录边界，再读取官方索引（ACL、IJCAI、NeurIPS、ICLR、PMLR、CVF、USENIX）或按 ISSN、collection DOI、venue 和年份分页读取 Crossref，并把每个“venue × 年份”标记为 complete、partial 或 failed。记录按 DOI 去重并补全摘要。关键词只负责提出候选；正式接受必须由当前 Agent 同时判断标题和摘要，并记录理由。选集在获取前绑定哈希并冻结，获取阶段不能添加、删除或替换论文。

两种 pending 状态是正常工作流的一部分：

- `pending_abstract` 表示仍未获得可信摘要。论文会保留等待后续补全，但不能只根据题名自动接受。
- `ready_unreviewed`（经常表现为 `decision_missing`）表示元数据足够，但尚未完成语义评审；常见原因是首选数量和全部配额已经满足。它不能进入冻结选集。

无法访问的论文继续留在冻结选集中，并写入 `manual-download.csv`；临时失败写入 `retryable-downloads.csv`。重跑会从断点继续。详见[论文集检索](https://enoselinsa.github.io/acquire-research-papers/zh/corpus/)和[自动获取](https://enoselinsa.github.io/acquire-research-papers/zh/acquisition/)。

## 文献调研实际如何工作

可靠的文献调研不能只运行一次关键词搜索。skill 使用四轮互补检索（直接术语、机制拆解、引用扩展和主动证伪），并组织成明确分阶段、可恢复的流程：

- `discover research` 使用 Crossref 以及已配置的 Semantic Scholar/OpenAlex 搜索，并把有边界的引用图扩展写入 `citation-graph.json`。`search-saturation.json` 记录最后几轮查询和引用图步骤是否仍在新增论文，其中的信号说明是否需要扩大 brief 或引用图。发现阶段返回 `status: review_required`。
- `review research` 要求当前 Agent 对每个哈希绑定候选明确给出 include/exclude 决定，然后冻结需要全文核验的最相近论文。
- `acquire research` 复用正式出版社获取流程，并通过 MinerU 缓存解析已核验 PDF。
- `evidence research` 校验论文 ID、哈希、claim、位置和摘录后写出报告；`--export-csv` 增加 `papers.csv` 和 `claim-coverage.csv`。

标题和摘要只能用于提出候选。直接支持或反驳必须有正文摘录以及章节或页码，gap 结论必须限定在已检索范围内。详见[文献调研](https://enoselinsa.github.io/acquire-research-papers/zh/research/)。

## 来源支持与成熟度

| 来源 | 论文发现 | PDF/BibTeX 获取 |
| --- | --- | --- |
| Crossref | venue/year 枚举和 research 搜索 | 不支持 |
| ACL Anthology、IJCAI、NeurIPS、ICLR（2024 年起）、PMLR、CVF Open Access、USENIX | 带摘要的官方索引 | 自动 |
| AAAI | 用 AAAI ISSN 读取 Crossref | 自动；2026 年 11 月初起 AAAI 引用导出接口返回 HTTP 520 |
| Springer Link | Crossref/OpenAlex/Semantic Scholar | 本网络有权限时自动 |
| IEEE Xplore | 期刊经 Crossref，会议经 OpenAlex | 配置 CARSI 院校档案后自动 |
| ACM Digital Library | Crossref collection | ACM 拦截非浏览器客户端期间转人工 |
| ScienceDirect | Crossref/OpenAlex/Semantic Scholar | 仅人工，由 CLI 核验并接管 |
| Semantic Scholar、OpenAlex | 可选搜索、补全和引用图 | 不支持 |
| MinerU | 不负责发现 | 不负责下载；可选全文解析缓存 |

IEEE 流程使用通用 profile，已在一个 CARSI 院校完成端到端真实验证；每个新增院校都需要首次适配。运行 `arp sources --spec <corpus.yaml>` 可离线查看逐 venue/年份缺口。含真实验证结果的完整表格和 venue 预设见[来源支持](https://enoselinsa.github.io/acquire-research-papers/zh/sources/)。

## 准确性与可信边界

项目从三个不同层面提高可靠性：

- **覆盖可追溯：**按 venue/year 枚举并记录覆盖状态，比只相信关键词搜索首页更可靠，但不能保证上游索引包含世界上每一篇论文。
- **相关性可复查：**确定性 hard gate 和预筛选降低噪声，正式接受还必须由当前 Agent 根据标题和摘要作出有理由的判断。这比纯关键词接受更可审计，但不是语义判断永远正确的证明。
- **文件身份可靠：**正式域名边界、出版社原始 BibTeX、元数据比较、provenance 和哈希提供系统中最强的保证：交付文件确实对应冻结论文。

仓库为这些行为提供回归测试，也已经完成真实的跨 venue 批量任务。但目前没有大型、独立人工标注的跨领域基准，因此不能宣传经过测量的 precision/recall 数字。缺少摘要、当年索引不完整、身份歧义和边界相关性都会明确报告，不会通过猜测隐藏。

## 当前限制

- 完整 IEEE/CARSI 流程目前只在一个 CARSI 院校完成真实验证；IEEE 浏览器集成仅支持 Windows。
- ACM 和 ScienceDirect 论文需要人工下载；项目不自动操作 organization login。
- Research mode 分阶段运行，并要求当前 Agent 明确作出决定；它不是无人参与的一键系统综述。
- 引用图覆盖受种子、邻居上限和来源覆盖限制；引用图和检索饱和度记录都不能证明普遍召回率。
- 新 proceedings 和不一致的上游元数据会造成覆盖不完整。
- `arp config status: true` 只说明本地配置结构存在，不代表凭据、额度、订阅或 API entitlement 实时有效。
- Claude Code、Kiro 的交互执行尚未实机验证。

全部已知限制见[可信边界与限制](https://enoselinsa.github.io/acquire-research-papers/zh/trust/)。

## 后续路线图

近期优先级（不代表当前已经支持）：复用已完成调研运行的后续发现、更清楚的 IEEE 院校诊断、专门的 ACM 授权访问契约、向现有论文库安全增量获取，以及更多组合指南。详见[路线图](https://enoselinsa.github.io/acquire-research-papers/zh/roadmap/)。

## 开发与验证

开发安装、Python/Node/PowerShell 测试、wheel/skill 构建、隔离安装、发布校验和文档站点见 [CONTRIBUTING.md](https://github.com/EnosElinsa/acquire-research-papers/blob/main/CONTRIBUTING.md)。参与项目请遵守[行为准则](https://github.com/EnosElinsa/acquire-research-papers/blob/main/CODE_OF_CONDUCT.md)；使用问题和缺陷报告见 [SUPPORT.md](https://github.com/EnosElinsa/acquire-research-papers/blob/main/SUPPORT.md)，安全漏洞见 [SECURITY.md](https://github.com/EnosElinsa/acquire-research-papers/blob/main/SECURITY.md)。

## 引用

如果本工具支撑了已发表的研究，请引用所用的发布版本。引用元数据在 [CITATION.cff](https://github.com/EnosElinsa/acquire-research-papers/blob/main/CITATION.cff) 中，GitHub 仓库页面会显示为“Cite this repository”。

## 负责任使用

机构访问只能用于当前账号和许可条款授权的材料。本项目不会绕过出版社控制、重新分发获取到的论文、自动化禁止的出版社交互，也不会削弱机构认证流程。

本项目采用 [MIT License](https://github.com/EnosElinsa/acquire-research-papers/blob/main/LICENSE)。
