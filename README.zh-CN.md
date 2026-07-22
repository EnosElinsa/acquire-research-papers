# 研究论文获取（Acquire Research Papers）

[English](README.md)

[![CI](https://github.com/EnosElinsa/acquire-research-papers/actions/workflows/test.yml/badge.svg)](https://github.com/EnosElinsa/acquire-research-papers/actions/workflows/test.yml)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

这是一个全局 Codex skill 和确定性命令行工具，用于检索、筛选和获取研究论文。每项完成的交付都包含出版社托管的 PDF、出版社导出的原始 BibTeX，以及证明二者属于同一篇论文的来源与哈希记录。

检索 API 只负责提出候选论文，不能替代正式文件。低置信度、边界或元数据冲突的论文会进入待确认清单。

## 工作流

| 工作流 | 适用任务 | 结果 |
| --- | --- | --- |
| `fetch` | DOI、出版社链接或明确论文清单 | 已核验的 PDF 与原始 BibTeX |
| `manual-fetch` | 需要用户在授权浏览器中完成下载 | 自动接管本地文件、核验并交付 |
| `discover corpus` | 指定期刊/会议、主题、年份和数量 | 覆盖账本与不可变证据包 |
| `review corpus` | Codex 对发现证据作语义判断 | 经过校验、满足配额的冻结选集 |
| `acquire corpus` | 已冻结的论文选择清单 | 已核验论文对及分开的人工、重试队列 |
| `discover research` | gap、相似工作、claim 引用或 Related Work | 证据表、对比、gap 与审核记录 |

PDF 转 Markdown 是可选步骤。研究模式可以临时调用 MinerU 分析候选全文，但只在用户明确要求时才导出 Markdown。

## 支持的来源

- ACL Anthology 和 IJCAI proceedings
- IEEE Xplore，以及可选的用户自定义 CARSI 机构访问配置
- ACM Digital Library
- ScienceDirect 人工机构登录接管流程
- 能唯一提供正式 PDF 和原始 BibTeX 的出版社页面

Crossref、OpenAlex 和 Semantic Scholar 只用于发现候选。镜像 PDF、模型生成引用和纯元数据记录都不算完成交付。

## 全局安装

需要 Git、[uv](https://docs.astral.sh/uv/) 和 Python 3.11+。只有 IEEE 等浏览器适配器需要 Node.js 与固定版本的 Playwright。机构凭据和可选 API key 通过 Windows DPAPI 加密。

```powershell
$skill = Join-Path $env:USERPROFILE ".codex\skills\acquire-research-papers"
git clone https://github.com/EnosElinsa/acquire-research-papers.git $skill
uv sync --project $skill --locked --all-groups
& "$skill\scripts\install-playwright.ps1"
uv run --project $skill arp --help
```

已有安装可先运行 `git pull --ff-only`，再执行 `uv sync --locked --all-groups`。

## 使用方法

直接获取受支持的论文：

```powershell
uv run --project $skill arp fetch `
  --input "https://aclanthology.org/2024.acl-long.1/" `
  --output "C:\Research\papers"
```

对于需要订阅权限的 ScienceDirect 论文，先启动监听：

```powershell
uv run --project $skill arp manual-fetch `
  --input "10.1016/j.asieco.2024.101746" `
  --watch "$HOME\Downloads" `
  --output "C:\Research\papers"
```

命令只会打开规范的出版社论文页。你在正常 Chrome 中完成 organization login，并手动下载 PDF 和出版社原始 BibTeX；之后工具会自动识别本次新增或变更且已写入稳定的文件，核验 DOI、题名、年份、期刊、第一作者和 PDF 身份，再以 `manual_publisher_download` 来源交付。

这条流程不会自动操作 ScienceDirect，不会连接正常 Chrome 的 profile，也不会读取、复制或导出 Cookie、Local Storage 或会话数据。

如果文件已经下载，可以直接交给工具：

```powershell
uv run --project $skill arp manual-fetch --input <DOI> `
  --pdf .\paper.pdf --bibtex .\citation.bib --output C:\Research\papers
```

论文集发现、论文集下载、文献调研和可选 Markdown 导出：

```powershell
uv run --project $skill arp discover corpus `
  --spec .\corpus.yaml --output C:\Research\corpus-discovery
uv run --project $skill arp review corpus `
  --run C:\Research\corpus-discovery `
  --decisions C:\Research\review-decisions.jsonl
uv run --project $skill arp acquire corpus `
  --selection C:\Research\corpus-discovery\selection-manifest.json `
  --output C:\Research\corpus `
  --defer-host publisher.example
uv run --project $skill arp discover research --brief .\brief.yaml --output C:\Research\review
uv run --project $skill arp export-md --pdf .\paper.pdf --output C:\Research\markdown
```

发现阶段按期刊/会议和年份完整分页，写入 `coverage.jsonl`、`candidates.jsonl`、`evidence-packets.jsonl`、`pending-metadata.csv` 和 `discovery-manifest.json`，不会下载出版社文件，也不会直接冻结选集。Codex 使用标题和摘要判断相关性，关键词是可选证据，发现阶段不要求正文权限。`review corpus` 会同时校验请求、候选、证据包和覆盖记录的哈希，再用 `review-decisions.jsonl` 做语义判断和配额规划。只有显式接受的论文可进入 `selected-papers.jsonl`；达到首选数量并满足全部配额后可以提前停止，未审查的溢出候选仍保留在 `pending-review.csv`。下载阶段在首次访问出版社前用 `selection-binding.json` 绑定输出目录，只消费冻结清单，不会增删论文；它输出核验后的 PDF/BibTeX、`acquisition-manifest.jsonl`、`manual-download.csv`、`retryable-downloads.csv` 和 `delivery-manifest.json`。

单篇论文需要用户访问时，整批下载不会中断。工具会继续处理其余选择，并在 `manual-download.csv` 中记录 selection ID、DOI、官方链接、出版社主机、原因和预留目标路径。之后使用 `manual-fetch --selection <manifest> --key <selection-id>`，系统会依据冻结身份核验本地 PDF/BibTeX，再填入预留位置。

需要在某次运行中禁止访问指定发布方时，可以重复传入 `--defer-host <准确主机名>`。已有且通过哈希核验的交付仍会复用；其他匹配记录不会从冻结清单中删除，而会写入人工下载队列。

交付目录必须位于本仓库之外。运行状态统一保存在 `%LOCALAPPDATA%\Codex`。

## 凭据与 API key

公开仓库不包含账号、密码、API key、token、Cookie 或浏览器配置。

在交互式 PowerShell 中配置你自己的 IEEE 机构档案和机构凭据：

```powershell
& "$skill\scripts\setup-ieee-institution.ps1"
```

机构档案还需要配置登录 CARSI 后进入 IEEE 的准确资源 URL。配置的接受/继续控件默认自动点击；如需人工完成，可在 `fetch` 或 `acquire corpus` 中传入 `--no-accept-ieee-attribute-release`。拒绝控件永远不会被点击，且 persistent browser context 未返回 `ieeexplore.ieee.org` 前不会请求 PDF。

仅在需要 Markdown 提取时单独配置 MinerU：

```powershell
& "$skill\scripts\setup-mineru-token.ps1"
```

配置只用于官方元数据查询的 Elsevier API key：

```powershell
& "$skill\scripts\setup-elsevier-api-key.ps1"
```

配置程序会询问 CARSI 中的准确机构选项、身份认证主机名、登录表单的可访问名称、资源入口，以及可选的属性发布页和接受/拒绝控件名称；仓库不提供任何学校默认值。凭据输入不会回显，密文通过 DPAPI 与当前 Windows 用户绑定。ScienceDirect 人工接管流程不保存任何机构密码。工具也不假设 API key 拥有 Article Retrieval 全文权限；遇到 403 时转入人工浏览器下载，不会改用网站自动化。

配置前请阅读 [`references/credentials-and-cache.md`](references/credentials-and-cache.md) 和 [`SECURITY.md`](SECURITY.md)。

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

## 合规使用

机构访问只能用于账号与学校许可范围内的资料。本项目不会绕过出版社访问控制、重新分发论文、自动化被禁止的出版社交互，或削弱学校认证流程。

本项目采用 [MIT License](LICENSE)。
