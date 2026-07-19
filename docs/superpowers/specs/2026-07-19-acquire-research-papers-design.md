# Acquire Research Papers 全局 Skill 设计

日期：2026-07-19

状态：已由用户确认，等待设计文档复核

目标仓库：`EnosElinsa/acquire-research-papers`（公开）
本地安装与仓库路径：`%USERPROFILE%\.codex\skills\acquire-research-papers`

## 1. 概述

`acquire-research-papers` 是一个与具体项目无关的全局 Codex skill，用于发现、筛选、获取、核验和交付学术论文。它同时支持：

1. 用户指定 DOI、官方 URL、标题或清单时直接下载。
2. 用户用自然语言或任务文件描述刊会、主题、年份和数量要求时，自动发现并收集论文语料。
3. 用户提出研究 gap、相似工作、claim 引用或 Related Work 问题时，进行证据驱动的文献调研。

默认交付物是官方 PDF 与同一官方出版页面提供的 BibTeX。Markdown 不是默认交付物：只有用户明确要求时才长期输出。在研究模式中，为核验全文证据，可以把最终候选 PDF 临时交给 MinerU 解析；解析结果进入七天过期的内部缓存，不自动进入交付目录。

Skill 对开放论文使用受控的官方页面下载，对需要订阅权限的平台使用来源专用的机构访问适配器。首批机构访问包括：

- IEEE Xplore：广西大学 CARSI。
- Elsevier ScienceDirect：先使用华南农业大学校园网/IP 权限，必要时使用独立 DPAPI scope 与学校 WebVPN；WebVPN 不支持 Elsevier 全文时显式要求 aTrust。

所有凭据、Cookie、浏览器 profile、缓存、注册表和下载结果均位于 Git 仓库之外。

## 2. 目标

### 2.1 功能目标

- 以一个 skill 暴露 `fetch`、`discover corpus` 和 `discover research` 三种意图。
- 支持自然语言、DOCX/Markdown/TXT、YAML/JSON、CSV 以及 DOI/URL/标题清单。
- 将所有批量收集要求归一化为通用 `CorpusSpec`，不绑定特定任务、角色或项目目录。
- 将所有研究型请求归一化为 `ResearchBrief`，支持 gap、相似工作、claim 引用和 Related Work。
- 使用统一 `PaperRecord` 跟踪身份、来源、筛选、下载、核验、证据和交付状态。
- 高置信度候选自动获取；边界候选进入待确认清单。
- 只从官方出版页面获取最终 PDF 和 BibTeX。
- 核对 PDF、BibTeX 与官方元数据的题名、作者、年份、刊会和 DOI。
- 通过 SQLite 全局注册表跨任务去重并复用已验证文件。
- 支持断点恢复、原子写入、稳定连续编号和可审计清单。
- 为公开 GitHub 仓库提供测试、CI、许可证和安全默认值。

### 2.2 自动化目标

- 普通成功路径由 Agent 调用一个入口完成，不要求用户手动点击网页。
- 已存在任务自动恢复，不重复解析或下载。
- 开放来源按域名限速并允许小规模并发。
- 机构认证会话串行执行，凭据最多提交一次。
- 页面漂移以命名阶段失败呈现，便于只修复受影响适配器。

### 2.3 质量目标

- BibTeX 必须来自官方页面的 Export Citation/BibTeX 功能或官方 `.bib` 资源。
- 禁止从 PDF 自动生成 BibTeX，禁止由 LLM 编造，禁止把第三方聚合站条目当作最终引用。
- 研究结论必须区分摘要判断与全文证据。
- Gap 必须限定检索范围和证据覆盖，不宣称不可证明的“从未有人研究”。
- 所有自动纳入决定必须包含可追溯理由，不使用不透明的单一模型分数替代硬规则。

## 3. 非目标

- 不绕过出版社或机构访问控制。
- 不处理 CAPTCHA、OTP 或安全质询；遇到这些情况安全停止。
- 不把 Google Scholar、Semantic Scholar、OpenAlex 或 Crossref 当作最终 PDF/BibTeX 来源。
- 不默认批量下载仅因关键词命中而产生的低置信度论文。
- 不自动修改用户论文正文；研究模式默认生成证据包，只有用户明确要求时才生成论文叙述文本。
- 不自动把下载结果放入当前项目的 `raw/sources`、知识库或其他发布目录。
- 不在仓库中保存真实任务输出、浏览器状态、凭据或 API key。
- 第一版不建立长期运行的服务器或后台守护进程。

## 4. 用户入口

### 4.1 自然语言路由

Skill 根据用户请求选择模式：

| 用户意图 | 模式 |
|---|---|
| 下载指定 DOI、URL、标题或列表 | `fetch` |
| 按刊会、主题、年份、数量或任务说明收集论文 | `discover corpus` |
| 查找 gap、相似工作、claim 引用或 Related Work | `discover research` |
| 导出已经下载论文的 Markdown | `export-md` |
| 继续、查看或复核任务 | `resume` / `status` / `review` |

### 4.2 CLI

实现一个 Python console script `arp`，供 Agent 确定性调用：

```text
arp fetch --input <doi-url-title-or-file> --output <directory>
arp discover corpus --spec <corpus-spec.yaml> --output <directory>
arp discover research --brief <research-brief.yaml> --output <directory>
arp status --task <task-id>
arp resume --task <task-id>
arp review --task <task-id> --decisions <csv-or-json>
arp export-md --task <task-id> [--paper <paper-id>]
arp cache purge [--expired | --all]
```

用户通常不直接编写 schema 或执行 CLI。Agent 读取用户描述或附件，生成并验证 spec/brief，然后调用 CLI。CLI 不内嵌第三方 LLM API，也不要求额外模型凭据。

### 4.3 默认输出位置

- 用户指定路径时严格使用该路径。
- 请求明确属于某个项目时，由用户或 Agent 把项目路径显式传给 CLI。
- 未指定且不属于项目时，使用 `%USERPROFILE%\Downloads\papers\<task-name>`。
- 输出目录不得位于 skill Git 仓库内。

## 5. 通用输入模型

### 5.1 `CorpusSpec`

`CorpusSpec` 表达任意配额型论文收集任务，核心字段包括：

```yaml
schema_version: 1
mode: corpus
name: llm-assisted-evolutionary-optimization
target:
  preferred: 80
  minimum: 60
  maximum: 100
scope:
  venues:
    - name: IEEE Transactions on Evolutionary Computation
      aliases: [IEEE TEVC, TEVC]
      kind: journal
  years:
    include: [2026, 2025, 2024]
    priority: [2026, 2025, 2024]
  publication_types:
    include: [full, regular, research-article]
    exclude: [workshop, demo, poster, short, tutorial, editorial]
  topics:
    include:
      - LLM-assisted evolutionary optimization
      - evolutionary optimization for LLM
    exclude:
      - LLM used only for prose editing
quotas:
  recent_window:
    from: 2025-07-19
    minimum_ratio: 0.40
delivery:
  require_pdf: true
  require_official_bibtex: true
  export_markdown: false
  profile: generic
```

字段均可省略非必要细节，但 schema 必须能表达：

- 目标、最小值与最大值。
- 刊会、刊会类别、别名、ISSN/ISBN 等可选标识。
- 年份范围、优先级和最近窗口比例。
- 正向主题、同义词、排除主题。
- 论文类型与轨道限制。
- 总量、分组、刊会和年份配额。
- 官方来源、PDF/BibTeX 和 Markdown 要求。
- 输出命名、编号和清单 profile。

当用户只给范围而没有 preferred target 时，默认以范围中点为 preferred target；达到 preferred target 后停止。若高质量结果不足，则报告缺口，不降低纳入标准。

### 5.2 输入适配器

- 自然语言：Agent 直接映射到 `CorpusSpec`。
- DOCX/Markdown/TXT：提取任务文本和表格，再由 Agent 映射。
- YAML/JSON：按 schema 验证后直接执行。
- CSV/DOI/URL/标题清单：如果没有发现约束，直接路由到 `fetch`；如果同时含筛选字段，则转换为 corpus 种子。
- 多角色任务文件：可选 `scope_selector` 指向姓名、章节或标签；它不是必填字段，也不会进入默认提示词。

“任务 DOCX + 学生 2”只作为真实验收样例，不写入通用模型或业务逻辑。

### 5.3 `ResearchBrief`

`ResearchBrief` 表达问题驱动调研：

```yaml
schema_version: 1
mode: research
question_type: gap-analysis
research_question: <用户的问题>
work_under_review:
  scenario: <场景>
  mechanism: <方法>
  decisions: []
  objectives: []
  constraints: []
claims: []
seed_papers: []
scope:
  years: null
  venues: []
  include_terms: []
  exclude_terms: []
delivery:
  write_narrative: false
  export_markdown: false
```

支持 `gap-analysis`、`similar-work`、`claim-citation` 和 `related-work`。默认输出证据包，不默认写入用户论文。

## 6. 架构

### 6.1 Agent 与代码边界

Agent 负责：

- 理解自然语言和任务附件。
- 生成 `CorpusSpec` 或 `ResearchBrief`。
- 扩展同义词、相邻概念和反向证伪查询。
- 对候选进行语义筛选并给出理由。
- 阅读临时全文解析，判断证据关系。
- 在用户明确要求时撰写 gap、Related Work 或引用文本。

确定性代码负责：

- schema 验证。
- API/网页元数据获取。
- 适配器路由和机构访问。
- PDF/BibTeX 下载和格式校验。
- DOI、版本、文件哈希去重。
- SQLite 注册表和任务状态。
- 原子保存、断点恢复、编号和输出清单。
- MinerU 调用、缓存和清理。
- 日志脱敏、限流、重试和错误分类。

### 6.2 组件

```text
Intent Router
  -> Spec/Brief Validator
  -> Discovery Planner
  -> Candidate Registry
  -> Screening Gate
  -> Canonical Resolver
  -> Source Adapter Router
  -> PDF + BibTeX Acquisition
  -> Pair Validator
  -> Optional Full-text Cache
  -> Delivery Profile
```

每个组件以数据模型而非隐式文件状态通信，便于独立测试和替换。

### 6.3 仓库结构

```text
acquire-research-papers/
|-- SKILL.md
|-- agents/openai.yaml
|-- pyproject.toml
|-- LICENSE
|-- .gitignore
|-- .github/workflows/test.yml
|-- schemas/
|   |-- corpus-spec.schema.json
|   |-- research-brief.schema.json
|   `-- paper-record.schema.json
|-- src/acquire_research_papers/
|   |-- cli.py
|   |-- config.py
|   |-- models.py
|   |-- registry.py
|   |-- discovery/
|   |-- screening/
|   |-- acquisition/
|   |   `-- adapters/
|   |-- bibliography/
|   |-- research/
|   |-- mineru/
|   `-- delivery/
|-- scripts/
|   |-- ieee-playwright.mjs
|   `-- setup-secrets.ps1
|-- references/
|-- tests/
|   |-- fixtures/
|   |-- unit/
|   `-- integration/
`-- docs/superpowers/specs/
```

根据 skill 规范，`SKILL.md` 是唯一 agent-facing 主文档；详细模式和来源规则放入 `references/`。仓库不添加重复的安装指南、快速参考或变更日志。公开仓库使用 MIT License。

## 7. 发现策略

### 7.1 来源层级

候选发现与最终交付来源严格分离：

1. 刊会官方索引：适合年份/轨道完整枚举。
2. Crossref：DOI、出版商、年份和刊会基础元数据。
3. OpenAlex：检索、引用网络、相关工作和开放位置线索。
4. Semantic Scholar：相似论文推荐补充。
5. 出版商搜索页面：精确核验和补漏。

Crossref、OpenAlex 和 Semantic Scholar 只能产生候选或验证线索。它们提供的 BibTeX、PDF 镜像或非官方文件不能直接交付。

### 7.2 `discover corpus`

处理顺序：

1. 按刊会、年份和轨道枚举候选。
2. 运行 DOI/正式版本去重。
3. 应用年份、文献类型和排除主题硬规则。
4. Agent 对标题、摘要和关键词进行主题筛选。
5. 高置信度候选进入获取队列；边界候选进入 `pending-review`。
6. 先满足 minimum 及最近窗口约束，再补到 preferred target。
7. 达到 preferred target 后停止；不为达到 maximum 降低标准。

默认高置信度门槛：

- 所有硬规则通过。
- 没有轨道、年份、正式版本或主题边界歧义。
- 语义相关度默认不低于 `0.85`。
- 至少有两个正向信号，例如题名/摘要机制匹配、关键词匹配、种子引用关系或刊会专题匹配。

`0.60-0.85`、缺少摘要、轨道不明或只有单一弱信号的候选进入待确认；低于 `0.60` 或命中排除规则的候选拒绝。阈值可由 spec 提高，但不能绕过硬规则。

### 7.3 `discover research`

执行四轮互补检索：

1. 直接术语与同义词检索。
2. 场景、机制、变量、目标和约束拆解检索。
3. 种子论文的前向、后向引用和相关工作扩展。
4. 主动寻找最相似工作和反例的证伪检索。

元数据高置信度候选可以自动获取 PDF/BibTeX 并进入临时全文解析。最终来源集要求全文证据与研究问题确实相关。

停止条件是证据饱和：

- 多轮检索不再产生新的高相关机制。
- 最近工作与经典种子均得到覆盖。
- 最相似工作已经全文核验。
- 重要 claim 已有直接证据，或明确记录证据不足。
- 剩余待确认候选不会改变主要判断。

研究输出包括：

- `research-manifest.csv`
- `pending-review.csv`
- `evidence-map.md`
- `nearest-work-matrix.csv`（适用时）
- `gap-analysis.md`（适用时）
- 用户明确要求时的叙述文本

每条证据记录 claim/比较维度、支持关系、强度、章节、页码、短摘录、解释、不确定性以及是否阅读全文。

## 8. 论文身份与状态

### 8.1 `PaperRecord`

核心字段：

- `paper_id`：稳定内部 ID。
- `doi`：小写规范化 DOI，可空。
- `canonical_title`、作者、年份、刊会、出版商。
- 正式 landing page、官方 PDF URL、官方 BibTeX URL。
- 发现来源与最终来源。
- 任务 ID、检索问题、主题标签、筛选分数和理由。
- 当前状态、错误代码和下一步建议。
- PDF/BibTeX/Markdown 路径与 SHA-256。
- 下载、验证、解析、交付和最后访问时间。

DOI 是首选去重键。没有 DOI 时使用规范化题名、年份、首位作者和刊会组合；所有无 DOI 自动匹配都保留可审计依据。

### 8.2 状态机

```text
discovered
  -> auto_accepted | pending_review | rejected
  -> resolving
  -> pdf_partial + bib_partial
  -> downloaded
  -> pair_verified
  -> temporarily_parsed (research only)
  -> numbered
  -> delivered
```

失败状态不覆盖最近一次成功状态，而是附加错误事件。恢复操作从最后一个已提交状态继续。

## 9. 获取适配器

### 9.1 通用规则

- 从确认的官方 landing page 开始。
- 只跟随适配器允许的域名和路径。
- PDF 请求禁止把敏感请求头自动转发到外部域名。
- 验证状态码、MIME、`%PDF-` 文件头和最小文件大小。
- 文件先写 `.partial`，验证后原子重命名。
- BibTeX 保存官方原始响应，并解析为核验模型。
- 第三方镜像只能作为发现线索，不能成为交付文件。

### 9.2 首批适配器

- `direct-official`：通用官方页面与开放 PDF/BibTeX。
- `acl-anthology`：ACL 官方论文、PDF 和 `.bib`。
- `ijcai-proceedings`：IJCAI 官方论文、轨道、PDF 和 BibTeX。
- `ieee-xplore`：IEEE 元数据、citation export、PDF 与机构访问。
- `acm-dl`：ACM/KDD 官方页面、PDF 与 citation export。
- `sciencedirect`：Elsevier 官方页面、PDF 与 citation export。

新来源只有在通用适配器不能稳定处理时才增加专用代码。

### 9.3 IEEE/广西大学

- 使用独立 Playwright persistent Chrome profile。
- 未授权 PDF 首次失败后，执行一次广西大学 CARSI 登录。
- 凭据只允许释放给配置中精确批准的广西大学 IdP 主机。
- 使用浏览器上下文共享 Cookie 的请求通道下载 PDF，不导出 Cookie。
- 禁止连接或检查用户普通 Chrome profile。
- CAPTCHA、OTP、未知认证主机或登录未完成时硬停止。
- IEEE Metadata API key 是可选增强，不是第一版依赖。

### 9.4 Elsevier/华南农业大学

- `v0.1.0` 使用 ScienceDirect 官方网页和当前校园网/IP entitlement。
- `v0.2.0` 可选保存华南农业大学统一身份认证凭据到仓库外的 DPAPI scope `sciencedirect_scau`，只在精确主机 `vpn.scau.edu.cn` 释放一次。
- WebVPN 产物只允许精确代理主机 `www-sciencedirect-com-s.vpn.scau.edu.cn`；当前网络和 WebVPN 均无权限时返回 `access_required` 或 `atrust_required`，不尝试绕过。
- Elsevier API 需要独立 API key；将来可配置，但不作为校园网网页下载的前提。

## 10. BibTeX 与配对核验

最终 `.bib` 必须来自同一官方出版页面或该平台官方 citation endpoint。流程：

1. 保存原始 BibTeX 响应。
2. 解析 entry type、key、题名、作者、年份、刊会和 DOI。
3. 与官方 landing metadata 比较。
4. 与 PDF 可验证信息进行一致性检查，但绝不从 PDF 生成 BibTeX。
5. 任一关键字段明显不一致时标记 `metadata_mismatch`。
6. 只有 PDF 与 BibTeX 均验证成功后才进入 `pair_verified`。

若官方页面没有 BibTeX，标记 `bib_missing` 并进入待确认。除非用户明确改变任务要求，该论文不计入“PDF + 官方 BibTeX”配额。

## 11. 注册表、缓存与文件系统

### 11.1 全局注册表

路径：

```text
%LOCALAPPDATA%\Codex\paper-acquisition\registry.sqlite
```

SQLite 使用事务和 WAL，至少包含：

- `papers`
- `artifacts`
- `tasks`
- `task_candidates`
- `provenance`
- `evidence`
- `number_allocations`
- `events`

注册表保存元数据、URL、哈希、状态和本地路径，不保存凭据、Cookie、PDF 正文或 Markdown 正文。

### 11.2 MinerU 缓存

路径：

```text
%LOCALAPPDATA%\Codex\cache\acquire-research-papers\<pdf-sha256>\
```

- 研究模式可以自动创建。
- 最后访问七天后清理。
- 同一 PDF 在缓存有效期内只解析一次。
- `arp cache purge --expired` 清理过期项。
- `arp cache purge --all` 需要明确调用。
- 只有 `export-md` 才把 Markdown 和图片复制到交付目录。

### 11.3 凭据与运行目录

```text
%LOCALAPPDATA%\Codex\secrets\acquire-research-papers\
%LOCALAPPDATA%\Codex\browser-profiles\acquire-research-papers\<provider>\
%LOCALAPPDATA%\Codex\deps\acquire-research-papers\
%LOCALAPPDATA%\Codex\paper-acquisition\runs\<task-id>\
```

Windows 上的秘密值使用 DPAPI。每个 secret 记录用途和允许的精确主机。日志只记录 secret 名称，不记录值。

## 12. 交付 profile

### 12.1 通用 profile

```text
<output>/
|-- papers/
|   `-- <safe-title>/
|       |-- paper.pdf
|       |-- citation.bib
|       `-- provenance.json
|-- papers.csv
|-- pending-review.csv
`-- collection-report.md
```

只有用户要求时才增加 Markdown 和 `images/`。

### 12.2 编号 profile

Schema 支持刊会文件夹、日期、前缀和连续数字编号。例如：

```text
2026.7.18 IEEE TEVC/
|-- 1.pdf
|-- 1.bib
|-- 2.pdf
`-- 2.bib
```

编号以 SQLite 事务分配，只在 `pair_verified` 后产生。失败、待确认和拒绝记录不占号。恢复任务不得改变已交付编号。

### 12.3 自定义 profile

输出 profile 只能改变目录、文件名、编号和清单格式，不能降低官方来源、配对核验和安全要求。

## 13. 错误处理与限流

标准错误代码：

- `not_found`
- `not_official`
- `access_required`
- `auth_interactive`
- `rate_limited`
- `pdf_invalid`
- `bib_missing`
- `metadata_mismatch`
- `duplicate`
- `screening_ambiguous`
- `page_contract_changed`
- `network_transient`

策略：

- 普通网络瞬时错误最多重试两次，指数退避。
- `429`、配额或明确限流立即暂停对应来源。
- 机构认证凭据最多提交一次。
- 开放域名允许小规模并发；每个域名独立限速。
- IEEE、Elsevier 等机构会话每个 profile 同时只运行一个任务。
- 一篇论文失败不终止其他独立论文，但任务报告必须显示缺口。
- 所有错误均写入事件表并给出可恢复的下一步。

## 14. 安全与公开仓库

- Git 仓库位于 `%USERPROFILE%\.codex\skills\acquire-research-papers`。
- 远端完成实现和实测后创建为 `EnosElinsa/acquire-research-papers` public repository。
- `.gitignore` 覆盖 `.env`、secret 文件、DPAPI payload、浏览器 profile、缓存、注册表、runs、下载和测试实链路输出。
- CI 只使用合成 fixture 和本地测试服务器，不使用真实凭据或机构访问。
- 禁止在 issue、日志、测试快照和失败 JSON 中输出秘密值。
- 重定向、Referer、Cookie 和凭据释放均受精确主机边界约束。
- 不批量下载不相关候选，不规避 publisher/机构控制，不自动处理 CAPTCHA/OTP。
- 提交和发布前运行敏感值扫描、`git diff --check` 和完整测试。

## 15. 测试策略

### 15.1 单元测试

- Schema 合法/非法输入。
- DOI、标题和版本规范化及去重。
- 状态机和非法跃迁。
- 高置信度、边界和拒绝决策。
- BibTeX 解析和字段错配。
- 输出命名、连续编号和路径边界。
- 错误分类、重试、限流和日志脱敏。
- 缓存命中、七天过期和清理。
- SQLite 事务、恢复和并发编号。

### 15.2 适配器 contract 测试

- 保存最小官方页面 fixture。
- 验证唯一 PDF/BibTeX 定位、允许主机和重定向边界。
- 页面缺失、重复元素、登录页面和非 PDF 响应必须失败。
- 适配器只返回标准化结果，不直接决定交付路径。

### 15.3 集成测试

- 使用本地 HTTP 测试服务器模拟开放、重定向、限流和无权限场景。
- 使用合成 PDF 与 BibTeX 完成 `fetch`、配对、注册和交付。
- 模拟任务中断并验证恢复后不重复下载或改变编号。
- 模拟研究模式 MinerU 成功、失败、缓存复用和不导出 Markdown。

### 15.4 真实冒烟

发布前分别验证：

- 一个 ACL 或 IJCAI 开放论文。
- 一个需要广西大学 CARSI 的 IEEE 论文。
- 一个华南农业大学校园网可访问的 Elsevier 论文。
- 一个官方 BibTeX 缺失或元数据不匹配的负面案例。
- 一个自然语言 corpus 小样本。
- 一个 gap/claim 研究小样本。
- 用户提供的学生 2 任务先运行小规模 profile，再进入正式 200-300 篇执行。

真实测试不会提交下载文件、凭据、浏览器 profile、缓存或注册表。

### 15.5 Skill forward test

实现完成后使用不泄露设计答案的新任务进行独立 forward test，至少覆盖：

- 指定 DOI 直接下载。
- 自然语言刊会/主题/数量任务。
- DOCX 多角色任务中的可选 scope 选择。
- claim 引用与相似工作检索。

只有在真实实链路和 forward test 均通过后才发布公开仓库。

## 16. 实施阶段

1. 初始化 skill、Python package、schemas、测试和 CI。
2. 实现模型、SQLite 注册表、状态机、路径和安全基础设施。
3. 实现 `fetch`、通用开放适配器、ACL 和 IJCAI。
4. 迁移并泛化现有 IEEE/CARSI 适配器。
5. 实现 BibTeX 核验、交付 profile、连续编号和断点恢复。
6. 实现 Crossref/OpenAlex/Semantic Scholar 候选发现和通用 `discover corpus`。
7. 实现 `discover research`、证据模型和临时 MinerU 缓存。
8. 实现 ACM/KDD 与 ScienceDirect/华南农业大学校园网适配器。
9. 完成离线、集成、真实冒烟和 forward tests。
10. 执行学生 2 小规模验收，修复问题后运行正式任务。
11. 完成代码审查、安全扫描、版本 `v0.1.0`、创建公开 GitHub 仓库并推送。

阶段之间以测试和可运行垂直切片为门禁，不一次性实现所有适配器后再验证。

## 17. 验收标准

### 17.1 Skill

- 全局 Codex 能从自然语言触发正确模式。
- `SKILL.md` 通过 skill validator。
- Skill 不依赖当前 `mec-research-wiki` 仓库。
- 公共仓库 clone 后可以安装核心开放获取功能。
- 未配置机构访问时仍能使用开放来源，并明确报告受限论文。

### 17.2 `fetch`

- 给定 DOI/URL/标题/清单能解析正式版本。
- 能获取并核验官方 PDF + BibTeX。
- 已有 DOI 能复用，任务可恢复。
- Markdown 只在明确请求时交付。

### 17.3 `discover corpus`

- 自然语言、结构化文件和任务附件都能生成等价 `CorpusSpec`。
- 高置信度自动获取，边界论文保留理由。
- 配额、年份、轨道和排除约束可审计。
- 达到 preferred target 后停止；不足时报告缺口而不降标。
- DOCX/执行人不是必需输入。

### 17.4 `discover research`

- 能生成检索计划、相似工作矩阵和证据映射。
- 能主动查找反例并限定 gap 表述。
- 全文证据与摘要判断明确区分。
- MinerU 结果只进七天临时缓存，除非显式导出。
- 默认不自动写入用户论文。

### 17.5 安全和发布

- IEEE、Elsevier 和开放来源真实冒烟通过。
- 凭据精确主机门禁、进程范围注入和日志脱敏通过。
- 仓库敏感值扫描为零。
- Git 工作树只包含 skill 源码、测试和必要文档。
- 本地提交、GitHub `main` 和发布 tag SHA 可验证一致。

## 18. 已锁定决策

- 使用一个全局 skill，内部模块化，不拆成多个需要手动编排的 skill。
- 全局安装目录与 Git 仓库是 `%USERPROFILE%\.codex\skills\acquire-research-papers`。
- 公开 GitHub 仓库名为 `acquire-research-papers`，所有者使用当前已认证账户。
- 支持完整发现，也支持指定目标直接下载。
- `discover corpus` 使用通用 `CorpusSpec`；任务 DOCX 和角色选择仅为可选适配器。
- 高置信度候选自动获取，边界候选进入待确认清单。
- 研究模式默认交付证据包，叙述文本需要用户明确要求。
- 研究模式可自动创建临时 MinerU 缓存，最后访问七天后清理。
- 长期 Markdown 输出必须由用户明确要求。
- 全局 SQLite 注册表被允许，只保存元数据、来源、状态、哈希和路径。
- OpenAlex、Semantic Scholar 和 Crossref 可用于发现，不可替代官方 PDF/BibTeX。
- IEEE 使用广西大学 CARSI；Elsevier 使用华南农业大学校园网/IP 权限。
- 默认在 preferred target 停止，数量不足时不降低质量标准。
- 完成代码、测试和实链路验证后再创建并推送公开远端。
