# 快速开始

示例假设 `$skill` 保存已安装的 skill 目录，设置方法见[安装](install.md)：

```powershell
$skill = Join-Path $env:USERPROFILE ".agents/skills/acquire-research-papers"
```

## 获取一篇已知论文

```powershell
python "$skill/scripts/arp.py" fetch `
  --input "https://aclanthology.org/2024.acl-long.1/" `
  --output "C:\Research\papers"
```

只有 JSON 状态为 `delivered` 时才可以使用输出文件。只有题名、没有 DOI 或正式链接时，必须先经过发现流程；`fetch` 不会在多个同名或近似题名之间猜测。

## 建立主题论文集

用户通常只需要用自然语言描述任务，由当前 Agent 生成论文集规范。下面的精简示例展示系统会明确哪些边界：

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

当前 Agent 随后阅读 `evidence-packets.jsonl`，根据标题和摘要生成绑定哈希的评审决定。导入这些决定并冻结选集：

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

[论文集检索](corpus.md)说明了每个阶段以及会遇到的 pending 状态。

## 准备一次文献调研

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

发现阶段返回 `status: review_required`。先阅读其中的 `saturation_signals` 和 `next_actions`：它们说明评审前是否需要扩大检索词或扩大引用图（见[文献调研](research.md#检索饱和度)）。随后由 Agent 评审经过哈希绑定的候选，冻结最相近论文，获取正式文件，阅读 MinerU 解析结果并导入证据：

```powershell
python "$skill/scripts/arp.py" review research `
  --run C:\Research\literature-review --decisions .\research-review.jsonl
python "$skill/scripts/arp.py" acquire research `
  --run C:\Research\literature-review
python "$skill/scripts/arp.py" evidence research `
  --run C:\Research\literature-review --records .\evidence-review.jsonl
```

评审和证据 JSONL 由当前 Agent 根据不可变候选包和解析后的全文生成，并遵守 [`schemas/`](https://github.com/EnosElinsa/acquire-research-papers/tree/main/schemas) 中的公开格式。最终 `status: complete` 表示冻结的最相近论文都已完成评审，不表示已经找到世界上所有论文，也不表示创新性得到无条件证明。
