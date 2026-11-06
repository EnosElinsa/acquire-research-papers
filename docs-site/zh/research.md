# 文献调研

可靠的文献调研不能只运行一次完整句子搜索。[快速开始](quick-start.md#准备一次文献调研)给出了完整 brief 和四条命令。

## 四轮检索

设计中的 skill 工作流包含四轮互补检索：

1. **直接术语：**研究问题本身、近义词、缩写和旧称。
2. **机制拆解：**分别搜索并重新组合场景、机制、决策变量、目标和约束。
3. **引用扩展：**从高相关种子论文查看后向参考文献、前向引用、Related Work 和引用图近邻。
4. **主动证伪：**专门寻找可能推翻 gap 的早期工作、等价机制或反例。

`discover research` 生成的关键词检索只含 brief 自身的词：研究问题加场景和机制、全部维度合并、只用机制和场景、以及去掉所提机制后的同一问题（用于证伪）。brief 中 `queries` 和 `synonyms` 的每一项各增加一次检索。引用扩展通过引用图完成，不作为关键词检索。`analysis.rows_per_query` 和 `analysis.max_candidates` 分别设定每次检索的结果数和保留的候选数；`scope.venues` 可以写刊名、ISSN，或 `T-RO` 这类预设名。`scope.publication_types: [review]`、`scope.doi_prefixes`、`scope.title_terms` 的过滤方式与 `discover candidates` 相同。年份、DOI 前缀和期刊限制由各来源在检索时直接应用，返回的结果都在范围内。

标题和摘要足以提出候选并做初筛。若要判断某篇论文直接支持、反驳或已经解决某个研究问题，必须阅读正文，记录章节或页码，并保留简短摘录。Gap 结论必须限定在已经搜索的范围内，并列出最接近的反例。

## 分阶段流程

Research mode 是明确分阶段、可恢复的流程，不是无人参与的一键系统综述：

- `discover research` 使用 Crossref 以及已配置的 Semantic Scholar/OpenAlex 搜索，按 DOI 去重，并执行有边界的后向参考文献、前向引用和 related-paper 扩展。可选来源可以独立失败，只留下脱敏诊断，不会抹掉其他来源的结果。它写出 `research-plan.json`、`research-candidates.jsonl`、`citation-graph.json`、`search-saturation.json` 和 `research-run.json`，并返回 `status: review_required`。
- `review research` 要求当前 Agent 对每个哈希绑定候选明确给出 include/exclude 决定，然后只冻结需要全文核验的最相近论文。规范化决定和审核清单也会通过哈希绑定到选集。
- `acquire research` 复用正式出版社获取流程，保留人工和重试队列，并通过内容寻址的 MinerU 缓存解析已核验 PDF。获取待办和解析待办分别计数；顶层状态指向最早尚未完成的关口，混合失败也不会互相遮蔽。
- `evidence research` 校验论文 ID、PDF 和 Markdown 哈希、claim ID、阅读范围、位置和摘录，之后填充证据图、最相近工作矩阵、claim 覆盖表和有边界的 gap 报告。`--export-csv` 增加 `papers.csv` 和 `claim-coverage.csv`。

标题和摘要仍然只能用于提出和初筛候选。直接支持或反驳必须有正文摘录以及章节或页码。因出版社访问或 MinerU 失败而未完成的论文会继续保留在同一个冻结任务中，不会被静默删除或替换。

## 检索饱和度

`search-saturation.json` 说明检索停止时是否仍在发现新论文。`discover research` 会输出其中的 `saturation_signals` 和 `next_actions`，证据报告也会在“Search saturation”一节重复这些内容。

| 记录部分 | 内容 |
| --- | --- |
| `query_passes` | 每轮查询的范围内结果数，以及其中新增的论文数 |
| `citation_frontier` | 每个引用图扩展步骤（种子和方向）的同类数据，以及因 `analysis.graph_seed_limit` 未扩展的种子 |
| `coverage` | 年份分布（近期指检索范围内最近三年）、被引至少 100 次的论文，以及有摘要的候选数 |
| `boundary_papers` | 只来自单一检索路径或缺少摘要的候选 |

评审前先处理这些信号：

| 信号 | 含义 | 处理方式 |
| --- | --- | --- |
| `search_still_growing` | 最后一轮查询仍新增至少三篇论文，且新增数不少于该轮结果的 30% | 用近义词、旧术语或 venue 名称扩大 brief |
| `citation_frontier_growing` | 最后一个引用图步骤仍新增同样多的论文 | 提高 `analysis.graph_seed_limit` 或 `analysis.graph_neighbors_per_direction` |
| `seeds_not_expanded` | 有候选种子因种子上限被跳过 | 提高 `analysis.graph_seed_limit` |
| `candidate_limit_reached` | 候选数达到上限，排名靠后的论文被截掉 | 检查排序或收窄 brief |
| `provider_failures` | 某个检索或引用图来源失败 | 稍后重跑；该来源的结果缺失 |
| `no_recent_work` / `no_earlier_work` | 没有候选落在检索范围内最近三年，或全部候选都在最近三年 | 补充当前或较早的术语和 venue |
| `stable_within_bounds` | 增长和上限类信号都没有出现 | 进入评审 |

修改 brief 后，把发现阶段重跑到新目录。`stable_within_bounds` 只表示本次运行自身的查询和边界不再新增论文，不能把它报告为召回率，也不能当作不存在其他工作的证明。

## 参考

完整的 Agent 契约（包括评审和证据记录的 schema）见 [skill 的 research 参考](https://github.com/EnosElinsa/acquire-research-papers/blob/main/skills/acquire-research-papers/references/research-mode.md)。
