# 来源支持

“支持”必须区分发现、正式文件获取和真实成熟度。

运行 `arp sources` 或 `arp sources --spec <corpus.yaml>`，可离线查看来源能力和逐 venue/年份缺口。参见[来源台账与验收标准](https://github.com/EnosElinsa/acquire-research-papers/blob/main/skills/acquire-research-papers/references/sources.md)。优先 venue 名单尚未确定，已有 ACL/IJCAI/IEEE/ACM/ScienceDirect 场景不代表覆盖全部会议和期刊。枚举完成只针对所选来源，上游仍可能漏收。

## venue 预设

内置 venue 预设让 spec 可以只写简称，例如 `name: INFOCOM` 或 `name: IEEE TMC`：该 venue 会得到 2026 年 11 月真实核对过的标识（37 个 IEEE 期刊和 AAAI 用 ISSN；INFOCOM、ICC、GLOBECOM、WCNC、VTC、ICDCS、ICNP、IWQoS、SECON 和 SIGCOMM 用 OpenAlex 系列；MobiCom 和 MobiHoc 用每届的会议录 DOI）。GitHub 上每周自动复查一次全部预设和官方索引。spec 中自己写的标识优先，`preset: none` 关闭匹配，`arp sources` 列出全部预设。

若 OpenAlex 某届收录数远低于上一年，发现阶段仍把该切片记为完成，但会加一条 `possible_upstream_lag` 警告；若因缺少 Semantic Scholar 或 OpenAlex key 而有摘要待补，会给出对应的 `arp config setup` 命令。用同一命令、同一输出目录重跑时，会重新读取带警告的切片并重新查缺失的摘要，已完成的切片不会重新抓取。

## 来源

| 来源 | 论文发现 | PDF/BibTeX 获取 | 当前成熟度与失败处理 |
| --- | --- | --- | --- |
| Crossref | 主要 venue/year 枚举和 research 搜索 | 不支持 | 稳定的公开元数据来源，但字段完整度仍取决于出版社 |
| ACL Anthology | 官方 proceedings 枚举 | 自动 | 成熟，已经用于真实批量任务 |
| IJCAI proceedings | 官方 proceedings 和 track 解析 | 自动 | 成熟，已经用于真实批量任务 |
| AAAI（ojs.aaai.org） | 用 AAAI ISSN 做 Crossref venue 枚举；记录自带摘要和官方归档 URL | 自动 | 官方 OJS PDF 和 BibTeX 导出。真实验证：AAAI-24 枚举出 2,867 条带摘要的记录，抽样论文已交付。2026 年 11 月初起 AAAI 的引用导出接口对所有客户端返回 HTTP 520，在 AAAI 修复前获取结果为 `network_transient` |
| NeurIPS proceedings | 官方年度列表：主会，以及 2022 年起的 Datasets and Benchmarks | 由发现阶段或摘要页 URL 自动获取 | 官方 PDF 和逐篇 BibTeX 文件。NeurIPS DOI 解析到 Curran Associates，单凭 DOI 不能下载。真实验证：2019 年列出 1,428 篇带摘要的论文；2019、2022 D&B 和 2023 论文已交付 |
| ICLR proceedings | proceedings.iclr.cc 上 2024 年起的官方年度列表 | 由发现阶段或摘要页 URL 自动获取 | 官方 PDF 和逐篇 BibTeX 文件。更早的年份只在 OpenReview 上，OpenReview 对非浏览器客户端返回验证页：发现阶段把这些年份记为 `source_unavailable`，论文转人工下载。真实验证：ICLR 2024 列出 2,260 篇带摘要的论文；抽样论文已交付 |
| PMLR | ICML、AISTATS、COLT、UAI、CoRL、ALT、ACML、L4DC、CLeaR 各卷的官方 BibTeX 文件 | 由发现阶段或论文页 URL 自动获取 | BibTeX 取自官方页面上显示的条目（provenance 记为 `publisher_page_embedded`）。真实验证：ICML 2023 列出 1,828 篇带摘要的论文；ICML 2019 和 2023 论文已交付 |
| CVF Open Access | CVPR、ICCV、WACV 主会官方列表 | 由发现阶段或论文页 URL 自动获取 | CVF 开放获取版本，除水印外与录用版本一致；最终出版版本在 IEEE Xplore（在 venue 上声明 `publisher: IEEE` 可改走 IEEE）。BibTeX 取自页面。真实验证：WACV 2024 列出 846 篇带摘要的论文；CVPR 2019、2023、一个 CVPR workshop 和 WACV 2024 论文已交付 |
| USENIX | USENIX Security、OSDI、NSDI、USENIX ATC 和 FAST 的 technical-sessions 页面，含每篇论文的摘要 | 由发现阶段或报告页 URL 自动获取 | 官方开放获取 PDF 和报告页上显示的 BibTeX（`publisher_page_embedded`；单独的 BibTeX 下载链接需要通过浏览器验证）。按 robots.txt 要求，对 www.usenix.org 的请求间隔 10 秒。真实验证：OSDI 2024 列出 53 篇、USENIX Security 2023 列出 422 篇，全部带摘要；OSDI 和 NSDI 论文已交付 |
| Springer Link | 由 Crossref/OpenAlex/Semantic Scholar 发现；`10.1007` DOI | 期刊论文和书籍章节（LNCS）在页面表明本网络有权限时自动获取 | 官方 PDF 和 Springer 引用导出服务提供的 BibTeX 文件。开放获取论文在任何网络下都可下载，订阅论文只在有权限的网络（如校园网）下载；否则为 `access_required`。不做登录。真实验证：两篇 Machine Learning 期刊论文和一篇 ECCV 章节已交付 |
| IEEE Xplore | 期刊经 Crossref（ISSN）枚举；会议经 OpenAlex（`openalex_source`，如 INFOCOM、ICC、GLOBECOM）枚举；摘要来自 OpenAlex/Semantic Scholar | 配置 CARSI 院校档案后自动 | 使用通用 profile；已在一个 CARSI 院校完成端到端真实验证。每个新增院校都需要首次适配和一篇代表论文冒烟测试 |
| ACM Digital Library | 通常由 Crossref collection 枚举和可选查询 API 发现 | 条件式 HTTP adapter | 只有正式页面和文件接口允许独立客户端访问时才能自动完成。2026 年 11 月实测，非浏览器请求和自动化 Chrome 都会遇到 Cloudflare 人机验证，因此 ACM 论文进入人工队列，提示信息会说明是人机验证 |
| ScienceDirect | Crossref/OpenAlex/Semantic Scholar 发现；Elsevier API 可解析预期身份 | 仅人工 | 用户在正常授权浏览器中下载，CLI 核验并接管本地文件；不自动登录或操作 ScienceDirect |
| Semantic Scholar | 可选带 key 候选搜索、DOI 补全以及引用/related 图扩展 | 不支持 | 只提供发现和图证据；来源失败会保留为诊断 |
| OpenAlex | 可选候选搜索、DOI 补全和引用图扩展 | 不支持 | 需要可选 API key；只提供发现和图证据 |
| MinerU | 不负责发现 | 不负责下载 | 可选七天全文解析缓存，只服务分析，不是论文来源 |
| 通用出版社 adapter | 内部已有受域名约束的实现 | 未作为公开生产默认入口启用 | 需要把批准域名和配置流程产品化后，才能宣称通用支持 |
