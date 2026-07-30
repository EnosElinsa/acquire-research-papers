# 研究论文获取（Acquire Research Papers）

[English](README.md)

[![CI](https://github.com/EnosElinsa/acquire-research-papers/actions/workflows/test.yml/badge.svg)](https://github.com/EnosElinsa/acquire-research-papers/actions/workflows/test.yml)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Acquire Research Papers 是一个公开的 Codex skill 和确定性命令行工具，用来完成三类相互关联的任务：

- 根据 DOI 或出版社正式页面获取已知论文；
- 按指定期刊/会议、年份、主题和配额建立可审计的论文集；
- 为相近工作、观点证据、Related Work 或创新 gap 分析准备并开展文献调研。

每项完成的获取都必须形成经过身份核验的一对文件：出版社托管的 PDF 和出版社导出的原始 BibTeX。Crossref、OpenAlex 和 Semantic Scholar 可以发现候选并补全元数据，但不能代替正式文件。本项目不使用论文镜像，不让模型生成引用，也不绕过出版社访问控制。

## 选择适合的工作流

| 你的任务 | 工作流 | 最终结果 |
| --- | --- | --- |
| 已有 DOI 或出版社正式链接 | `fetch` | 一对经过核验的 PDF/BibTeX，或明确可操作的访问结果 |
| 要从指定 venue、年份和主题中建立论文集 | `discover corpus` → Codex 评审 → `review corpus` → `acquire corpus` | 覆盖证据、冻结选集、正式文件以及人工/重试队列 |
| 出版社要求用户在授权浏览器中操作 | `manual-fetch` | 接管用户下载的正式文件，核验身份后放入预留交付位置 |
| 要找相近工作、观点引用、Related Work 或验证 gap | `discover research`，随后由 Codex 继续评审和全文取证 | 先得到检索计划和候选包；只有阅读最相近论文后才形成可靠证据 |
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

公开数据发现和非浏览器流程需要 Git、[uv](https://docs.astral.sh/uv/) 和 Python 3.11+。IEEE 浏览器自动化还需要 Node.js、Windows PowerShell 和固定版本的 Playwright。目前安全凭据集成使用 Windows DPAPI。

```powershell
$skill = Join-Path $env:USERPROFILE ".codex\skills\acquire-research-papers"
git clone https://github.com/EnosElinsa/acquire-research-papers.git $skill
uv sync --project $skill --locked --all-groups
& "$skill\scripts\install-playwright.ps1"
uv run --project $skill arp --help
```

更新已有安装：

```powershell
git -C $skill pull --ff-only
uv sync --project $skill --locked --all-groups
```

交付目录必须位于本仓库之外。运行注册表、加密密钥、缓存和独立浏览器 profile 均保存在 `%LOCALAPPDATA%\Codex` 下。

## 首次使用：只配置当前任务需要的能力

先检查哪些可选能力已经配置：

```powershell
uv run --project $skill arp config status
```

该命令只返回布尔值。它检查本地保存对象的结构，不打印或解密任何值。`true` 表示本地已有配置，不代表远端 API 或出版社权限一定可用。Agent 应只引导配置当前任务真正需要的能力，然后用一项有代表性的实际操作验证它。

| 能力 | 何时配置 | 配置方式 |
| --- | --- | --- |
| 无需配置 | 公开 Crossref 发现、ACL 发现/获取、IJCAI 发现/获取 | 不需要密钥 |
| Semantic Scholar | 需要带 key 的候选搜索、更高额度和第一轮 DOI 摘要补全 | `& "$skill\scripts\setup-discovery-api-keys.ps1" -Provider semantic_scholar` |
| OpenAlex | 需要额外候选搜索和第二轮 DOI 摘要补全 | `& "$skill\scripts\setup-discovery-api-keys.ps1" -Provider openalex` |
| IEEE | 需要通过本校和 CARSI 自动获取订阅的 IEEE PDF | `& "$skill\scripts\setup-ieee-institution.ps1"` |
| Elsevier | ScienceDirect 人工接管前需要解析官方预期身份 | `& "$skill\scripts\setup-discovery-api-keys.ps1" -Provider elsevier` |
| MinerU | 需要为内部全文分析解析 PDF，或明确要求导出 Markdown | `& "$skill\scripts\setup-mineru-token.ps1"` |

所有配置提示均为交互式且不回显。不要把密码、API key、token 或 Cookie 粘贴到聊天、Agent 消息、命令参数、`.env` 或仓库文件中。各 Provider 独立更新：增加 OpenAlex key 不会覆盖 IEEE、MinerU、Elsevier 或 Semantic Scholar 配置。

## 快速开始

### 获取一篇已知论文

```powershell
uv run --project $skill arp fetch `
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
uv run --project $skill arp discover corpus --progress `
  --spec .\corpus.yaml --output C:\Research\corpus-run
```

Codex 随后阅读 `evidence-packets.jsonl`，根据标题和摘要生成绑定哈希的评审决定。导入这些决定并冻结选集：

```powershell
uv run --project $skill arp review corpus `
  --run C:\Research\corpus-run `
  --decisions C:\Research\corpus-run\review-decisions.jsonl
```

下载阶段只读取冻结清单：

```powershell
uv run --project $skill arp acquire corpus `
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
scope:
  years: [2023, 2024, 2025, 2026]
delivery:
  write_narrative: false
  export_markdown: false
```

```powershell
uv run --project $skill arp discover research `
  --brief .\research-brief.yaml --output C:\Research\literature-review
```

该命令当前返回 `status: planned`：它准备四类检索和候选包，不代表引用扩展、全文阅读或 gap 验证已经完成。

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

当前实现是调研基础设施，不是一条命令完成系统综述。默认 `discover research` 目前会：

- 生成四类查询；
- 使用 Crossref 搜索并对有限候选去重；
- 写出调研计划、候选清单、待评审清单、最相近工作矩阵、证据图框架和 gap 报告框架；
- 在尚未完成全文验证时明确拒绝给出创新性结论。

它目前**不会**真正执行规划好的引用图，不会默认使用 OpenAlex/Semantic Scholar 作为 research searcher，不会自动获取并阅读最相近论文，也不会自行填充 claim 级全文证据。在完整 Codex skill 工作流中，Agent 必须继续完成出版社获取、可选 MinerU 解析、人工证据评审和有边界的综合判断。README 不再把空框架描述成已经完成的文献调研。

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
| Semantic Scholar | 可选带 key 候选搜索；DOI 摘要补全可使用更低的无 key 额度 | 不支持 | 只作为发现证据 |
| OpenAlex | 可选候选搜索和 DOI 摘要补全 | 不支持 | 只作为发现证据 |
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
uv run --project $skill arp manual-fetch `
  --input "10.1016/j.asieco.2024.101746" `
  --watch "$HOME\Downloads" --output C:\Research\papers
```

CLI 只打开规范的论文页面。用户在正常 Chrome（或其他授权浏览器）中完成 organization login，并下载正式 PDF 和原始 BibTeX。CLI 只观察稳定的新文件或变更文件，核验后交付。它不会控制 ScienceDirect，不会读取用户 Chrome profile，不会导出 Cookie，也不会把 Article Retrieval API 的 403 转成脚本化网站登录。

如果两个文件已经存在：

```powershell
uv run --project $skill arp manual-fetch --input <DOI> `
  --pdf .\paper.pdf --bibtex .\citation.bib --output C:\Research\papers
```

冻结论文集中的人工条目应使用不可变 selection ID：

```powershell
uv run --project $skill arp manual-fetch `
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
- `discover research` 当前负责规划和搭建调研框架，不会一条命令完成引用图、最相近论文获取和 claim 级全文证据。
- 没有可信摘要的论文保持 `pending_abstract`，禁止只按题名接受。
- 尚未发布的 proceedings 和上游元数据不一致会造成覆盖不完整。
- `arp config status: true` 只说明本地配置结构存在，不代表凭据、额度、订阅或 API entitlement 实时有效。
- 大批量认证下载采取保守顺序执行，可能耗时较长。
- acquisition 需要干净或已经绑定的交付根目录；导入现有人工整理目录还不是一等命令。
- 内部通用出版社 adapter 尚未成为公开插件系统。
- 目前没有跨领域标注基准支持数值化 precision/recall 声明。

## 后续路线图

以下是改进优先级，不代表当前已经支持。

### 近期

1. **让 research mode 真正端到端执行。**接入 OpenAlex 和 Semantic Scholar research searcher，执行真实前向/后向引用遍历，获取最相近论文，支持可恢复全文评审，并导入经过校验的 claim 级证据。
2. **增加 IEEE 院校诊断器。**探测非敏感 profile 字段，显示脱敏阶段跳转，校验资源入口、entity ID 和表单契约，并在不泄露凭据的情况下运行一篇代表论文冒烟测试。
3. **产品化 ACM 授权访问。**设计独立、可见、隔离并限制准确域名的浏览器契约，采用与 IEEE 相同的 fail-closed 原则；访问或页面形态未知时继续转人工。
4. **支持安全增量获取和现有目录导入。**让新的冻结选集能够复用已验证用户文件，提供明确迁移命令，不再依赖临时复制。
5. **提供可复制模板。**增加 `arp init corpus`、`arp init research`、示例规范和面向用户的运行摘要。

### 中期

6. **量化发现质量。**建立标注过的 venue/topic fixture，按来源和领域统计覆盖率、precision、recall、摘要缺失率和评审分歧。
7. **扩展官方枚举。**在存在官方索引或 API 时增加准确、可审计的 venue adapter，优先考虑 IEEE 和 ACM collection，同时保留严格标识符要求。
8. **改善批量操作。**增加遵守出版社限制的安全并发、进度快照、重试调度和人工队列批量接管，同时保护限流和共享会话。
9. **提高可移植性。**把 secret store 抽象到不同操作系统 keychain，保留 Windows DPAPI 兼容，绝不退回明文文件。
10. **开放出版社插件契约。**允许用户为通用 adapter 注册准确批准域名和经过测试的页面契约，同时继续拒绝任意跳转和模型生成引用。

除非出版社政策和安全的官方集成条件发生变化，否则 ScienceDirect 浏览器自动化不会进入路线图。

## 可选 Markdown 规则

文献调研可以通过七天 SHA-256 MinerU 缓存解析选定 PDF，用于内部阅读。普通 fetch、manual fetch、论文集发现、评审和获取都不会产生 Markdown。只有用户明确指定目标目录时才导出：

```powershell
uv run --project $skill arp export-md `
  --pdf .\paper.pdf --output C:\Research\markdown
```

## 开发与验证

```powershell
uv sync --locked --all-groups
uv run ruff check src tests scripts/validate_skill.py
uv run pytest -q
uv run python scripts/validate_skill.py .
node --test tests/node/test-ieee-playwright.mjs
./tests/powershell/test-secret-store.ps1
./tests/powershell/test-install-playwright.ps1
```

规范性契约见 [references/corpus-mode.md](references/corpus-mode.md)、[references/research-mode.md](references/research-mode.md)、[references/source-policies.md](references/source-policies.md)、[references/credentials-and-cache.md](references/credentials-and-cache.md) 和 [SECURITY.md](SECURITY.md)。

## 负责任使用

机构访问只能用于当前账号和许可条款授权的材料。本项目不会绕过出版社控制、重新分发获取到的论文、自动化禁止的出版社交互，也不会削弱机构认证流程。

本项目采用 [MIT License](LICENSE)。
