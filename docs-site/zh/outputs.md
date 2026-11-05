# 输出文件

先读 CLI 返回的状态、数量、下一步动作和可用路径。可选文件不存在时路径返回 JSON `null`。机器状态用于恢复，日常通常只需读报告和非空待办队列。

| 工作流 / 阶段 | 应保留的状态 | 面向用户的结果 / 可选导出 |
| --- | --- | --- |
| 单篇获取 | 正式 PDF、原始 BibTeX 和 provenance | 核验后的文件对，不生成报告目录 |
| Corpus 发现 | 请求、`coverage.jsonl`、候选、证据包、来源错误和 manifest | 仅有缺失元数据时写 `pending-metadata.csv` |
| Corpus 复核 | 复核决定、`selected-papers.jsonl`、选集和复核 manifest | `pending-review.csv` 受哈希绑定，完成后仍保留空队列 |
| Corpus 获取 | 获取账本、选集绑定、交付 manifest 和正式文件对 | `paper-manifest.csv`；人工/重试队列仅在非空时生成 |
| Research 发现 | `research-plan.json`、`research-candidates.jsonl`、`citation-graph.json`、`search-saturation.json`、`research-run.json` | 此阶段不生成证据或 gap 报告 |
| Research 复核 / 全文 | 复核决定、冻结选集、阶段 manifest、`full-text-manifest.jsonl` 和内部解析缓存 | 非空复核/下载队列；状态区分获取与解析阻塞 |
| Research 证据 | `validated-evidence-reviews.jsonl`、`research-evidence.json` | 一份 `reports/report.md`；`--export-csv` 增加 `papers.csv`、`claim-coverage.csv` |
| 作者文献 | 含来源、身份、日期证据的 `author-discovery.json` | `report.md`；`--export-csv` 增加 `author-discovery.csv` |
| 文献库审计 | `audit.json` | `report.md`、非空人工队列；`--export-csv` 增加 `audit.csv` |
| 文献库更新 / 导入 / 整理 | 待审计划、暂存文件、provenance、备份和 apply journal | 审核后执行计划，保留备份供回滚 |

新 Research 运行标记 `output_version: 2`。没有该字段的旧运行继续使用旧报告布局，不重写冻结字节或哈希。新布局将 research manifest 和 nearest-work matrix 合并为可选 `papers.csv`；证据位置、claim 状态及适用的有界 gap 结论合并到 `report.md`，检索溯源保留在 `research-plan.json`。不带 CSV 导出选项重新运行时，只清除已知生成文件；待办解决后清除对应队列。不要用这些生成文件名保存手工编辑内容。

## 可选 Markdown 规则

`acquire research` 会把选定 PDF 解析到七天 SHA-256 MinerU 缓存，用于内部证据评审。缓存 Markdown 属于分析状态，不是交付文件。普通 fetch、manual fetch 和论文集流程不会产生 Markdown。只有用户明确指定目标目录时才导出：

```powershell
python "$skill/scripts/arp.py" export-md `
  --pdf .\paper.pdf --output C:\Research\markdown
```
