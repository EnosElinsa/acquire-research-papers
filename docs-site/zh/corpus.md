# 论文集检索

论文集模式适合“指定这些 venue、这些年份，查找这些主题”的有边界任务。[快速开始](quick-start.md#建立主题论文集)给出了完整规范和三条命令。

## 论文集检索如何工作

1. **定义边界。** 当前 Agent 记录准确的期刊/会议、年份、论文类型、主题、排除项、总数和配额。
2. **先枚举再筛选。** ACL、IJCAI、NeurIPS、ICLR（2024 年起）、PMLR 系列会议（ICML、AISTATS、COLT 等）、CVF（CVPR、ICCV、WACV）和 USENIX（Security、OSDI、NSDI、ATC、FAST）读取各自的官方索引；期刊和已知会议集通过 ISSN、collection DOI、venue 和年份分页读取 Crossref；OpenAlex 和 Semantic Scholar 可以补充基于查询的候选。
3. **记录覆盖状态。** 每个“venue × 年份”都会标记为 complete、partial 或 failed。缺少 proceedings 页面或准确标识符时，会生成诊断信息，不会把空结果伪装成完整覆盖。
4. **合并并补全。** 优先按 DOI 去重。缺少摘要时，先按 DOI 查询 Semantic Scholar，配置 OpenAlex 后再进行第二轮补全；每个字段保留来源记录。
5. **依据证据评审。** 确定性规则排除错误年份、venue、track、论文类型和明显的目录/封面信息。关键词只负责提出候选；正式接受必须由当前 Agent 同时判断标题和摘要，并记录理由。
6. **满足配额后冻结。** 最终清单和规范都会绑定哈希。进入下载阶段后不能再添加、删除或替换论文。

## pending 状态

两种 pending 状态是正常工作流的一部分：

- `pending_abstract` 表示仍未获得可信摘要。论文会保留等待后续补全，但不能只根据题名自动接受。
- `ready_unreviewed`（经常表现为 `decision_missing`）表示元数据足够，但尚未完成语义评审；常见原因是首选数量和全部配额已经满足。它不能进入冻结选集。

## 断点与重跑

发现产物同时也是断点。对同一目录重新运行时，会复用已经完成的切片，只重试不完整来源；带 `possible_upstream_lag` 警告的切片会重新读取，缺失的摘要会重新查询，已完成的切片不会重新抓取。

venue 预设让规范可以只写简称，例如 `name: INFOCOM` 或 `name: IEEE TMC`；覆盖范围见[来源支持](sources.md#venue-预设)。发现前运行 `arp sources --spec <corpus.yaml>`，可离线查看逐 venue/年份缺口。

评审完成后，[自动获取](acquisition.md)只交付冻结选集。完整的 Agent 契约见 [skill 的 corpus 参考](https://github.com/EnosElinsa/acquire-research-papers/blob/main/skills/acquire-research-papers/references/corpus-mode.md)。

## 按主题找几篇综述

论文集会先列出每个 venue、每一年的全部论文。若只需从多本期刊中找几篇综述，改为按主题检索：

```text
arp discover candidates --query "mobile robot path planning survey" --year 2024 --year 2025 --type review --doi-prefix 10.1109 --title-term "path planning|motion planning" --output candidates.json
```

检索在 Crossref 和 Semantic Scholar 上无需 key，OpenAlex 需要 key，几个来源同时进行，并限定在给定年份和过滤条件内；`--preset T-RO` 或 `--issn` 可限定到指定期刊。标题和摘要中不含任何主题词的记录会被去掉，其余按匹配程度排序。用同一命令、同一输出重跑时，只重新查询上次没有完成的来源。Agent 评审标题和摘要后，把接受的 DOI 写入文本文件，再运行 `arp fetch --input-file`。完整步骤见[主题综述示例](https://github.com/EnosElinsa/acquire-research-papers/blob/main/skills/acquire-research-papers/examples/08-topic-surveys.md)。关键词检索不能保证穷尽，结果中应说明检索所用的查询和过滤条件。
