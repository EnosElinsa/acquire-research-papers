# 研究论文获取（Acquire Research Papers）

[English](README.md)

[![CI](https://github.com/EnosElinsa/acquire-research-papers/actions/workflows/test.yml/badge.svg)](https://github.com/EnosElinsa/acquire-research-papers/actions/workflows/test.yml)
[![Release](https://img.shields.io/github/v/release/EnosElinsa/acquire-research-papers)](https://github.com/EnosElinsa/acquire-research-papers/releases/latest)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Acquire Research Papers 是一个公开的 Codex skill 和确定性命令行工具，用来获取论文和管理本地论文库：

- 根据 DOI 或出版社正式页面获取已知论文；
- 按指定期刊/会议、年份、主题和配额建立可审计的论文集；
- 为相近工作、观点证据、Related Work 或创新 gap 分析准备并开展文献调研；
- 审计、更新、导入和整理本地 PDF/BibTeX，使用可审阅的变更计划和备份；
- 按作者查漏论文，明确区分身份、出版日期和来源覆盖证据。

[最新版本](https://github.com/EnosElinsa/acquire-research-papers/releases/latest) · [更新记录](CHANGELOG.md) · [开发指南](CONTRIBUTING.md) · [使用帮助与反馈](SUPPORT.md) · [安全说明](SECURITY.md)

每项完成的获取都必须形成经过身份核验的一对文件：出版社托管的 PDF 和出版社导出的原始 BibTeX。Crossref、OpenAlex 和 Semantic Scholar 可以发现候选并补全元数据，但不能代替正式文件。本项目不使用论文镜像，不让模型生成引用，也不绕过出版社访问控制。

## 选择适合的工作流

| 你的任务 | 工作流 | 最终结果 |
| --- | --- | --- |
| 已有 DOI 或出版社正式链接 | `fetch` | 一对经过核验的 PDF/BibTeX，或明确可操作的访问结果 |
| 需要机构访问或切换学校 | `config setup ieee` → `config ieee login/doctor` | 命名隔离档案、默认人工登录，以及分开的认证和下载诊断 |
| 已有 PDF/BibTeX 文件夹 | `library audit/update/import/organize` → `library apply` | 版本证据、配对文件名、原始引用字节、带哈希的变更计划和备份 |
| 需要作者论文列表或本地查漏 | `discover author` | 正式发表、Early Access 和预印本分组，以及身份歧义和来源覆盖说明 |
| 要从指定 venue、年份和主题中建立论文集 | `discover corpus` → Codex 评审 → `review corpus` → `acquire corpus` | 覆盖证据、冻结选集、正式文件以及人工/重试队列 |
| 出版社要求用户在授权浏览器中操作 | `manual-fetch` | 接管用户下载的正式文件，核验身份后放入预留交付位置 |
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

Codex 是这条工作流的一部分。CLI 负责确定性校验、断点记录、冻结清单和正式文件获取；Codex 负责把用户的自然语言要求转成检索规范，并作出可记录、可复查的语义评审决定。

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

启动器只使用 Python 标准库，根据 `runtime.json` 获取固定版本 wheel、校验 SHA-256，再通过 uv 安装到独立缓存。不会依赖开发 checkout 或把开发工具装进 skill。IEEE 浏览器和 DPAPI 凭据当前需要 Windows、PowerShell、Node.js；公开检索和论文库操作可跨平台运行。

更新时重新运行同一条 Skills 安装命令。注册表、凭据、缓存、院校 profile 和浏览器会话保存在 skill 目录之外；交付文件也应使用独立目录。开发构建可按[开发指南](CONTRIBUTING.md)使用经过摘要校验的本地 wheel 验证。

如果现有 skill 目录本身是 Git 开发 checkout，请保留它，不要让第三方安装器覆盖此目录。先构建导出，再用仓库的安全复制安装器放入新目录；它拒绝含 `.git` 的目标，明确替换旧版纯 skill 时也保留备份。详见[安全迁移](CONTRIBUTING.md#safe-copy-and-checkout-migration)。

### 发布文件与手动安装

[v0.4.0 发布页](https://github.com/EnosElinsa/acquire-research-papers/releases/tag/v0.4.0)提供：

| 文件 | 用途 |
| --- | --- |
| `acquire-research-papers-skill-0.4.0.zip` | 解压后，将其中的 `acquire-research-papers/` 文件夹复制到新的 skill 目录。包含指令、参考资料、schemas、启动器和固定运行版本清单。 |
| `acquire_research_papers-0.4.0-py3-none-any.whl` | 用 `uv tool install <wheel-path>` 单独安装 CLI；也可将其绝对路径设置为 `ARP_LOCAL_WHEEL`，供启动器从本地加载。摘要校验仍然生效。 |
| `SHA256SUMS` | PowerShell 使用 `Get-FileHash <path> -Algorithm SHA256`，Linux 使用 `sha256sum <path>`，与清单核对下载文件。 |

手动安装 skill 需要 Python 3.11+ 和 uv。启动器默认在首次运行时下载固定 wheel；依赖安装仍需网络或已有 uv 缓存。IEEE 浏览器另外需要 Node.js。不要把源码压缩包或开发 checkout 整体复制为 skill。启动和迁移问题见 [SUPPORT.md](SUPPORT.md)。

## 首次使用：只配置当前任务需要的能力

先检查哪些可选能力已经配置：

```powershell
python "$skill/scripts/arp.py" config status
```

该命令默认只返回能力布尔值；`--details` 可附加非敏感 profile/历史验证摘要。它检查本地保存对象的结构，不打印或解密任何值。`true` 表示本地已有配置，不代表远端 API 或出版社权限一定可用。Agent 应只引导配置当前任务真正需要的能力，然后用一项有代表性的实际操作验证它。

| 能力 | 何时配置 | 配置方式 |
| --- | --- | --- |
| 无需配置 | 公开 Crossref 发现、ACL 发现/获取、IJCAI 发现/获取 | 不需要密钥 |
| Semantic Scholar | 需要带 key 的候选搜索、更高额度和第一轮 DOI 摘要补全 | `arp config setup semantic_scholar` |
| OpenAlex | 需要额外候选搜索和第二轮 DOI 摘要补全 | `arp config setup openalex` |
| IEEE | 需要本校 IEEE 访问；默认先人工登录，可另行启用支持的 CARSI 表单 | `arp config setup ieee` |
| Elsevier | ScienceDirect 人工接管前需要解析官方预期身份 | `arp config setup elsevier` |
| MinerU | 需要为内部全文分析解析 PDF，或明确要求导出 Markdown | `arp config setup mineru` |

秘密输入采用交互式、不回显提示；机构名称和官方入口是普通非敏感输入。不要把密码、API key、token 或 Cookie 粘贴到聊天、Agent 消息、命令参数、`.env` 或仓库文件中。各 Provider 独立更新：增加 OpenAlex key 不会覆盖 IEEE、MinerU、Elsevier 或 Semantic Scholar 配置。

## 命名院校、现有论文库与作者论文发现

下列 `arp` 是 `python <skill-directory>/scripts/arp.py` 的简写。

```text
arp config setup ieee --profile my-institution --mode assisted
arp config ieee list
arp config ieee use my-institution
arp config ieee login --profile my-institution
arp config ieee doctor --profile my-institution --reference <IEEE-URL>
arp library audit <library-directory> --output <audit-directory>
arp library update <library-directory> --output <staging-directory>
arp library import <incoming-directory> --destination <library-directory> --output <plan.json>
arp library organize <library-directory> --output <plan.json>
arp library apply --plan <plan.json>
arp library apply --plan <plan.json> --rollback
arp discover author --spec <author.json> --output <discovery-directory>
```

IEEE 支持 `direct`、`assisted` 与明确表单契约下的 `carsi` 命名 profile，各自使用隔离浏览器上下文。已配置、IdP 登录成功、返回 IEEE、核验下载及证明机构权限是不同状态；开放获取论文下载成功不等于订阅权限已验证。详见[配置说明](skills/acquire-research-papers/references/configuration.md)。

论文库审计报告身份、重复、缺失和歧义，分别核验引用出版信息与 PDF 版本。BibTeX 已更新不能证明 PDF 已更新；注册库元数据仍属于发现证据。更新只暂存正式文件，导入和整理只生成带哈希计划；明确执行 apply 后才修改文件，并保留备份。原始 BibTeX 字节、BOM、编码和换行保持不变。`--metadata` 可供离线核验，`update --verify-only` 不获取文件。有界 `--watch` 只观察用户已下载的 ScienceDirect PDF/BIB，使用单一人工队列，绝不自动操作页面。详见[论文库模式](skills/acquire-research-papers/references/library-mode.md)。

作者规范支持身份 ID、机构/合作者、日期范围、主页及本地目录。ORCID、DBLP、主页和数据库记录保留身份歧义及来源错误；只按准确 DOI 去重，区分正式发表、early access 与预印本，期刊卷期日期优先于在线日期，只用明确关系关联不同版本，绝不声称绝对完整。`--records` 可提供离线证据。详见[作者模式](skills/acquire-research-papers/references/author-mode.md)。

## 快速开始

### 获取一篇已知论文

```powershell
python "$skill/scripts/arp.py" fetch `
  --input "https://aclanthology.org/2024.acl-long.1/" `
  --output "C:\Research\papers"
```

只有 JSON 状态为 `delivered` 时才可以使用输出文件。只有题名、没有 DOI 或正式链接时，必须先经过发现流程；`fetch` 不会在多个同名或近似题名之间猜测。

### 建立主题论文集

用户通常只需要用自然语言描述任务，由 Codex 生成论文集规范。下面的精简示例展示系统会明确哪些边界：

```yaml
schema_version: 1
mode: corpus
name: llm-agent-and-evolutionary-computation
target:
  minimum: 20
  preferred: 30
  maximum: 30
scope:
  venues:
    - name: "Proceedings of the 63rd Annual Meeting of the Association for Computational Linguistics (Volume 1: Long Papers)"
      short_name: ACL
      publisher: ACL
      kind: conference
      years: [2025]
    - name: IEEE Transactions on Evolutionary Computation
      short_name: TEVC
      publisher: IEEE TEVC
      kind: journal
      issn: [1089-778X, 1941-0026]
      years: [2024, 2025]
  years:
    include: [2025, 2024]
    priority: [2025, 2024]
  publication_types:
    include: [full, journal-article]
  topics:
    include:
      - large language model multi-agent
      - evolutionary optimization
    synonyms:
      - agent collaboration
      - LLM-guided search
    exclude:
      - editorial
      - correction
quotas:
  groups:
    - name: ACL
      minimum: 10
      venues:
        - "Proceedings of the 63rd Annual Meeting of the Association for Computational Linguistics (Volume 1: Long Papers)"
    - name: TEVC
      minimum: 10
      venues:
        - IEEE Transactions on Evolutionary Computation
delivery:
  require_pdf: true
  require_official_bibtex: true
  export_markdown: false
  profile: numbered
  naming_template: "papers/{publisher}/{number}.{ext}"
```

先运行发现：

```powershell
python "$skill/scripts/arp.py" discover corpus --progress `
  --spec .\corpus.yaml --output C:\Research\corpus-run
```

Codex 随后阅读 `evidence-packets.jsonl`，根据标题和摘要生成绑定哈希的评审决定。导入这些决定并冻结选集：

```powershell
python "$skill/scripts/arp.py" review corpus `
  --run C:\Research\corpus-run `
  --decisions C:\Research\corpus-run\review-decisions.jsonl
```

下载阶段只读取冻结清单：

```powershell
python "$skill/scripts/arp.py" acquire corpus `
  --selection C:\Research\corpus-run\selection-manifest.json `
  --output C:\Research\corpus-delivery
```

### 准备一次文献调研

```yaml
schema_version: 1
mode: research
question_type: gap-analysis
research_question: Has prior work jointly optimized this scenario and mechanism?
work_under_review:
  scenario: multi-agent edge computing
  mechanism: LLM-guided evolutionary optimization
  decisions: [task allocation, agent communication]
  objectives: [latency, solution quality]
  constraints: [limited communication budget]
seed_papers: []
analysis:
  max_full_text_papers: 20
  graph_seed_limit: 3
  graph_neighbors_per_direction: 25
scope:
  years: [2023, 2024, 2025, 2026]
delivery:
  write_narrative: false
  export_markdown: false
```

```powershell
python "$skill/scripts/arp.py" discover research `
  --brief .\research-brief.yaml --output C:\Research\literature-review
```

发现阶段返回 `status: review_required`。随后由 Codex 评审经过哈希绑定的候选，冻结最相近论文，获取正式文件，阅读 MinerU 解析结果并导入证据：

```powershell
python "$skill/scripts/arp.py" review research `
  --run C:\Research\literature-review --decisions .\research-review.jsonl
python "$skill/scripts/arp.py" acquire research `
  --run C:\Research\literature-review
python "$skill/scripts/arp.py" evidence research `
  --run C:\Research\literature-review --records .\evidence-review.jsonl
```

评审和证据 JSONL 由 Codex 根据不可变候选包和解析后的全文生成，并遵守 `schemas/` 中的公开格式。最终 `status: complete` 表示冻结的最相近论文都已完成评审，不表示已经找到世界上所有论文，也不表示创新性得到无条件证明。

## 论文集检索实际如何工作

论文集模式适合“指定这些 venue、这些年份，查找这些主题”的有边界任务，实际经过以下步骤：

1. **定义边界。** Codex 记录准确的期刊/会议、年份、论文类型、主题、排除项、总数和配额。
2. **先枚举再筛选。** ACL 和 IJCAI 使用官方 proceedings；期刊和已知会议集通过 ISSN、collection DOI、venue 和年份分页读取 Crossref；OpenAlex 和 Semantic Scholar 可以补充基于查询的候选。
3. **记录覆盖状态。** 每个“venue × 年份”都会标记为 complete、partial 或 failed。缺少 proceedings 页面或准确标识符时，会生成诊断信息，不会把空结果伪装成完整覆盖。
4. **合并并补全。** 优先按 DOI 去重。缺少摘要时，先按 DOI 查询 Semantic Scholar，配置 OpenAlex 后再进行第二轮补全；每个字段保留来源记录。
5. **依据证据评审。** 确定性规则排除错误年份、venue、track、论文类型和明显的目录/封面信息。关键词只负责提出候选；正式接受必须由 Codex 同时判断标题和摘要，并记录理由。
6. **满足配额后冻结。** 最终清单和规范都会绑定哈希。进入下载阶段后不能再添加、删除或替换论文。

两种 pending 状态是正常工作流的一部分：

- `pending_abstract` 表示仍未获得可信摘要。论文会保留等待后续补全，但不能只根据题名自动接受。
- `ready_unreviewed`（经常表现为 `decision_missing`）表示元数据足够，但尚未完成语义评审；常见原因是首选数量和全部配额已经满足。它不能进入冻结选集。

发现产物同时也是断点。对同一目录重新运行时，会复用已经完成的切片，只重试不完整来源。

## 文献调研实际如何工作

可靠的文献调研不能只运行一次完整句子搜索。设计中的 skill 工作流包含四轮互补检索：

1. **直接术语：**研究问题本身、近义词、缩写和旧称。
2. **机制拆解：**分别搜索并重新组合场景、机制、决策变量、目标和约束。
3. **引用扩展：**从高相关种子论文查看后向参考文献、前向引用、Related Work 和引用图近邻。
4. **主动证伪：**专门寻找可能推翻 gap 的早期工作、等价机制或反例。

标题和摘要足以提出候选并做初筛。若要判断某篇论文直接支持、反驳或已经解决某个研究问题，必须阅读正文，记录章节或页码，并保留简短摘录。Gap 结论必须限定在已经搜索的范围内，并列出最接近的反例。

Research mode 是明确分阶段、可恢复的流程，不是无人参与的一键系统综述：

- `discover research` 使用 Crossref 以及已配置的 Semantic Scholar/OpenAlex 搜索，按 DOI 去重，并执行有边界的后向参考文献、前向引用和 related-paper 扩展。可选来源可以独立失败，只留下脱敏诊断，不会抹掉其他来源的结果。
- `review research` 要求 Codex 对每个哈希绑定候选明确给出 include/exclude 决定，然后只冻结需要全文核验的最相近论文。规范化决定和审核清单也会通过哈希绑定到选集。
- `acquire research` 复用正式出版社获取流程，保留人工和重试队列，并通过内容寻址的 MinerU 缓存解析已核验 PDF。获取待办和解析待办分别计数；顶层状态指向最早尚未完成的关口，混合失败也不会互相遮蔽。
- `evidence research` 校验论文 ID、PDF 和 Markdown 哈希、claim ID、阅读范围、位置和摘录，之后填充证据图、最相近工作矩阵、claim 覆盖表和有边界的 gap 报告。

标题和摘要仍然只能用于提出和初筛候选。直接支持或反驳必须有正文摘录以及章节或页码。因出版社访问或 MinerU 失败而未完成的论文会继续保留在同一个冻结任务中，不会被静默删除或替换。

## 自动获取实际如何工作

自动获取从 DOI、准确的正式页面或经过哈希验证的冻结选集开始。每个出版社 adapter 必须把请求限制在批准的准确域名内。成功交付要求：

- 有效的出版社正式 PDF；
- 原样保留的出版社原始 BibTeX；
- DOI、题名、年份、venue 和作者范围一致；
- provenance 和 SHA-256 哈希能够证明两份文件属于同一论文。

Crossref、OpenAlex、Semantic Scholar、普通仓库和镜像都不能满足最终交付。无法访问的论文继续留在冻结清单中，并写入 `manual-download.csv`；临时网络或限流问题写入 `retryable-downloads.csv`。单篇失败不会中断其他论文。

在首次访问出版社前，输出目录会绑定一个冻结选集。重新运行时，只有全部记录路径和哈希仍匹配才会跳过已交付论文。为了避免覆盖，包含未绑定 PDF、BibTeX 或 acquisition ledger 的旧目录会被拒绝；应使用干净目录或明确的迁移/导入流程。

## 来源支持与成熟度

“支持”必须区分发现、正式文件获取和真实成熟度：

| 来源 | 论文发现 | PDF/BibTeX 获取 | 当前成熟度与失败处理 |
| --- | --- | --- | --- |
| Crossref | 主要 venue/year 枚举和 research 搜索 | 不支持 | 稳定的公开元数据来源，但字段完整度仍取决于出版社 |
| ACL Anthology | 官方 proceedings 枚举 | 自动 | 成熟，已经用于真实批量任务 |
| IJCAI proceedings | 官方 proceedings 和 track 解析 | 自动 | 成熟，已经用于真实批量任务 |
| IEEE Xplore | 候选主要来自 Crossref/OpenAlex/Semantic Scholar | 配置 CARSI 院校档案后自动 | 使用通用 profile；已在一个 CARSI 院校完成端到端真实验证。每个新增院校都需要首次适配和一篇代表论文冒烟测试 |
| ACM Digital Library | 通常由 Crossref collection 枚举和可选查询 API 发现 | 条件式 HTTP adapter | 只有正式页面和文件接口允许独立客户端访问时才能自动完成；目前没有生产级 ACM 浏览器 adapter，被拦截时转人工 |
| ScienceDirect | Crossref/OpenAlex/Semantic Scholar 发现；Elsevier API 可解析预期身份 | 仅人工 | 用户在正常授权浏览器中下载，CLI 核验并接管本地文件；不自动登录或操作 ScienceDirect |
| Semantic Scholar | 可选带 key 候选搜索、DOI 补全以及引用/related 图扩展 | 不支持 | 只提供发现和图证据；来源失败会保留为诊断 |
| OpenAlex | 可选候选搜索、DOI 补全和引用图扩展 | 不支持 | 需要可选 API key；只提供发现和图证据 |
| MinerU | 不负责发现 | 不负责下载 | 可选七天全文解析缓存，只服务分析，不是论文来源 |
| 通用出版社 adapter | 内部已有受域名约束的实现 | 未作为公开生产默认入口启用 | 需要把批准域名和配置流程产品化后，才能宣称通用支持 |

## IEEE 机构访问

IEEE 使用独立、可见的 Chrome profile，因为机构认证和 PDF 请求必须共享同一个隔离浏览器上下文。流程会先尝试直接读取论文，不会一开始就读取凭据；缺少权限时才会：

1. 进入院校档案中配置的准确 CARSI IEEE 资源入口；
2. 选择准确的院校候选，并写入、校验 IdP entity ID；
3. 只有当前域名与配置的 IdP 域名完全一致时，才读取 DPAPI 凭据，并且最多提交一次；
4. 处理单“继续”按钮或“接受/拒绝”属性释放页，永远不点击拒绝；
5. CARSI 返回但尚未获得 IEEE 权限时，只重新访问配置的同一资源入口；
6. 必须确认同一上下文已经返回准确的 `ieeexplore.ieee.org`，才请求 PDF 和 BibTeX。

配置的接受/继续控件默认自动点击。传入 `--no-accept-ieee-attribute-release` 可以把可见页面留给用户手动完成。

### 适配新院校

公共脚本中不包含院校名称分支或共享凭据。新院校应优先通过 profile 适配：准确的 CARSI 候选、entity ID、IdP 域名、可访问表单标签、资源入口和继续/接受控件。保持浏览器可见，只使用脱敏后的阶段/域名诊断；每次修正后先用一篇代表论文测试。

只有可见页面证明出现了 profile 无法表达、而且可以复用的新页面形态时，才修改通用浏览器脚本，并先添加回归 fixture。整个过程必须保留准确域名凭据释放、一次凭据提交、三次资源入口上限、共享 Cookie、禁止点击拒绝和查询参数脱敏。

## ScienceDirect 人工接管

ScienceDirect 按设计保持人工模式。需要解析官方预期身份时，先配置 Elsevier API key：

```powershell
& "$skill\scripts\setup-discovery-api-keys.ps1" -Provider elsevier
```

下载前先启动监听：

```powershell
python "$skill/scripts/arp.py" manual-fetch `
  --input "10.1016/j.asieco.2024.101746" `
  --watch "$HOME\Downloads" --output C:\Research\papers
```

CLI 只打开规范的论文页面。用户在正常 Chrome（或其他授权浏览器）中完成 organization login，并下载正式 PDF 和原始 BibTeX。CLI 只观察稳定的新文件或变更文件，核验后交付。它不会控制 ScienceDirect，不会读取用户 Chrome profile，不会导出 Cookie，也不会把 Article Retrieval API 的 403 转成脚本化网站登录。

如果两个文件已经存在：

```powershell
python "$skill/scripts/arp.py" manual-fetch --input <DOI> `
  --pdf .\paper.pdf --bibtex .\citation.bib --output C:\Research\papers
```

冻结论文集中的人工条目应使用不可变 selection ID：

```powershell
python "$skill/scripts/arp.py" manual-fetch `
  --selection C:\Research\corpus-run\selection-manifest.json `
  --key <selection-id> --output C:\Research\corpus-delivery `
  --watch "$HOME\Downloads"
```

## 如何理解输出文件

| 文件 | 含义 |
| --- | --- |
| `coverage.jsonl` | 每个来源对请求的 venue/year 切片覆盖到什么程度 |
| `candidates.jsonl` | 去重后的发现账本，不是最终引用库 |
| `evidence-packets.jsonl` | Codex 实际评审的不可变标题/摘要证据 |
| `pending-metadata.csv` | 因缺少摘要等证据而暂时无法评审的候选 |
| `pending-review.csv` | 元数据足够但尚无语义决定的候选 |
| `selected-papers.jsonl` | 唯一允许进入获取阶段的冻结论文 |
| `selection-manifest.json` | 规范和冻结清单的哈希绑定 |
| `acquisition-manifest.jsonl` | 每篇入选论文的持久交付状态 |
| `manual-download.csv` | 需要授权用户操作或尚无安全 adapter 的冻结论文 |
| `retryable-downloads.csv` | 不改变选集即可重试的临时故障 |
| `delivery-manifest.json` | 获取数量、选集绑定和完成状态 |
| `research-candidates.jsonl` | 用于明确评审最相近论文的哈希绑定候选 |
| `citation-graph.json` | 有边界的后向、前向和 related-paper 边、已使用/被截断的种子边界，以及脱敏来源诊断 |
| `full-text-manifest.jsonl` | 冻结论文、正式 PDF 哈希、MinerU Markdown 哈希、解析模式和 pending 状态 |
| `validated-evidence-reviews.jsonl` | 绑定到准确 PDF 和解析 Markdown 的 Codex 证据评审 |
| `claim-coverage.csv` | 每个 claim 的关系、证据论文和未解决状态 |
| `evidence-map.md` / `gap-analysis.md` | 可审计的证据位置和限定在检索范围内的结论 |

某次运行中不应访问指定出版社时，可以重复使用 `--defer-host <准确主机名>`。延后的论文仍保留在选集中并进入人工队列；已经通过哈希验证的交付仍会复用。

## 准确性与可信边界

项目从三个不同层面提高可靠性：

- **覆盖可追溯：**按 venue/year 枚举并记录覆盖状态，比只相信关键词搜索首页更可靠，但不能保证上游索引包含世界上每一篇论文。
- **相关性可复查：**确定性 hard gate 和预筛选降低噪声，正式接受还必须由 Codex 根据标题和摘要作出有理由的判断。这比纯关键词接受更可审计，但不是语义判断永远正确的证明。
- **文件身份可靠：**正式域名边界、出版社原始 BibTeX、元数据比较、provenance 和哈希提供系统中最强的保证：交付文件确实对应冻结论文。

仓库为这些行为提供回归测试，也已经完成真实的跨 venue 批量任务。但目前没有大型、独立人工标注的跨领域基准，因此不能宣传经过测量的 precision/recall 数字。缺少摘要、当年索引不完整、身份歧义和边界相关性都会明确报告，不会通过猜测隐藏。

## 当前限制

- 完整 IEEE/CARSI 流程目前已在一个 CARSI 院校完成真实验证；每个新增院校虽然由通用 profile 驱动，仍需要首次观察和适配。
- 安全机构凭据和当前引导式配置主要面向 Windows、PowerShell 和 DPAPI。
- IEEE 期刊发现主要依赖 Crossref 和可选元数据 API；当前版本没有 IEEE 官方 venue 枚举器。
- ACM 自动获取没有生产级浏览器 adapter；HTTP 客户端被正式页面拦截时转人工。
- ScienceDirect 只支持人工获取；项目有意不自动操作 organization login 或文章页面。
- Research mode 分阶段运行，并要求 Codex 明确给出候选评审和证据决定；它不是无人参与的一键系统综述。
- 引用图覆盖受到种子、邻居上限、来源覆盖和 API 可用性的共同限制，不能据此宣称普遍召回率。
- 没有可信摘要的论文保持 `pending_abstract`，禁止只按题名接受。
- 尚未发布的 proceedings 和上游元数据不一致会造成覆盖不完整。
- `arp config status: true` 只说明本地配置结构存在，不代表凭据、额度、订阅或 API entitlement 实时有效。
- 大批量认证下载采取保守顺序执行，可能耗时较长。
- 现有目录的导入和整理要求明确评审带哈希计划；PDF/引用身份不明的记录仍需人工核验。
- 内部通用出版社 adapter 尚未成为公开插件系统。
- 目前没有跨领域标注基准支持数值化 precision/recall 声明。

## 后续路线图

以下是改进优先级，不代表当前已经支持。

### 近期

1. **量化 research 检索饱和度。**增加可重复的停止诊断，报告新机制、引用前沿增长、经典/近期工作覆盖和未解决边界论文，同时避免把这些指标误写成普遍召回率证明。
2. **改善 IEEE 院校诊断。**在现有命名 profile 和 doctor 基础上改进首次适配及实时访问诊断，继续保护凭据。
3. **产品化 ACM 授权访问。**设计独立、可见、隔离并限制准确域名的浏览器契约，采用与 IEEE 相同的 fail-closed 原则；访问或页面形态未知时继续转人工。
4. **扩展安全增量获取。**在现有论文库导入、更新计划基础上让新冻结选集复用已验证用户文件。
5. **提供可复制模板。**增加 `arp init corpus`、`arp init research`、示例规范和面向用户的运行摘要。

### 中期

6. **量化发现质量。**建立标注过的 venue/topic fixture，按来源和领域统计覆盖率、precision、recall、摘要缺失率和评审分歧。
7. **扩展官方枚举。**在存在官方索引或 API 时增加准确、可审计的 venue adapter，优先考虑 IEEE 和 ACM collection，同时保留严格标识符要求。
8. **改善批量操作。**增加遵守出版社限制的安全并发、进度快照、重试调度和人工队列批量接管，同时保护限流和共享会话。
9. **提高可移植性。**把 secret store 抽象到不同操作系统 keychain，保留 Windows DPAPI 兼容，绝不退回明文文件。
10. **开放出版社插件契约。**允许用户为通用 adapter 注册准确批准域名和经过测试的页面契约，同时继续拒绝任意跳转和模型生成引用。

除非出版社政策和安全的官方集成条件发生变化，否则 ScienceDirect 浏览器自动化不会进入路线图。

## 可选 Markdown 规则

`acquire research` 会把选定 PDF 解析到七天 SHA-256 MinerU 缓存，用于内部证据评审。缓存 Markdown 属于分析状态，不是交付文件。普通 fetch、manual fetch 和论文集流程不会产生 Markdown。只有用户明确指定目标目录时才导出：

```powershell
python "$skill/scripts/arp.py" export-md `
  --pdf .\paper.pdf --output C:\Research\markdown
```

## 开发与验证

开发安装、Python/Node/PowerShell 测试、wheel/skill 构建、隔离安装及发布校验见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 负责任使用

机构访问只能用于当前账号和许可条款授权的材料。本项目不会绕过出版社控制、重新分发获取到的论文、自动化禁止的出版社交互，也不会削弱机构认证流程。

本项目采用 [MIT License](LICENSE)。
