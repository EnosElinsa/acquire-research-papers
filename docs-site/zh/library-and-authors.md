# 论文库与作者

下列 `arp` 是 `python <skill-directory>/scripts/arp.py` 的简写。

## 本地 PDF/BibTeX 论文库

```text
arp library audit <library-directory> --output <audit-directory>
arp library update <library-directory> --output <staging-directory>
arp library import <incoming-directory> --destination <library-directory> --output <plan.json>
arp library organize <library-directory> --output <plan.json>
arp library apply --plan <plan.json>
arp library apply --plan <plan.json> --rollback
```

论文库审计报告身份、重复、缺失和歧义，分别核验引用出版信息与 PDF 版本。BibTeX 已更新不能证明 PDF 已更新；注册库元数据仍属于发现证据。

更新只暂存正式文件，导入和整理只生成带哈希计划；明确执行 apply 后才修改文件，并保留备份。原始 BibTeX 字节、BOM、编码和换行保持不变。`--metadata` 可供离线核验，`update --verify-only` 不获取文件。有界 `--watch` 只观察用户已下载的 ScienceDirect PDF/BIB，使用单一人工队列，绝不自动操作页面。详见[论文库参考](https://github.com/EnosElinsa/acquire-research-papers/blob/main/skills/acquire-research-papers/references/library-mode.md)。

## 作者论文

```text
arp discover author --spec <author.json> --output <discovery-directory>
```

作者规范支持身份 ID、机构/合作者、日期范围、主页及本地目录。ORCID、DBLP、主页和数据库记录保留身份歧义及来源错误；只按准确 DOI 去重，区分正式发表、early access 与预印本，期刊卷期日期优先于在线日期，只用明确关系关联不同版本，绝不声称绝对完整。`--records` 可提供离线证据。详见[作者参考](https://github.com/EnosElinsa/acquire-research-papers/blob/main/skills/acquire-research-papers/references/author-mode.md)。
