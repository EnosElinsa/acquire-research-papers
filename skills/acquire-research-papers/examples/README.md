# Composition recipes

These are copyable applications of independent capabilities, not additional kernel task types. Copy only the needed input templates into a private working directory outside the installed skill and source repository. Replace all explanatory placeholders with user-provided identities, paths, and scope before executing. `arp` means `python <actual-installed-skill-directory>/scripts/arp.py`; commands use one line so any supported host can adapt its shell quoting.

| Scenario | Recipe | Input template |
| --- | --- | --- |
| Known list acquisition | [Known list](01-known-list.md) | [known-papers.json](inputs/known-papers.json) |
| Topic corpus | [Topic corpus](02-topic-corpus.md) | [corpus.yaml](inputs/corpus.yaml) |
| Author gap check | [Author gap check](03-author-gap-check.md) | [author.json](inputs/author.json), [empty-metadata.json](inputs/empty-metadata.json) |
| Local library update/organization | [Library maintenance](04-library-maintenance.md) | [empty-metadata.json](inputs/empty-metadata.json) |
| Related Work, claim evidence and gap analysis | [Research](05-related-work.md) | [related-work.yaml](inputs/related-work.yaml), [gap-analysis.yaml](inputs/gap-analysis.yaml) |
| Explicit chapters | [Book chapters](07-book-chapters.md) | [chapter-map.json](inputs/chapter-map.json) |

Start with `arp doctor --host <actual-host> --skill-directory <actual-installed-skill-directory>` and `arp config status`. Configure only required optional providers. The agent reads packets and full text and writes real hash-bound decisions. Templates contain no acceptance decisions, output hashes, credentials, model claims, or fabricated publisher artifacts.

Capability commands can record a lightweight run using `--run`; check it with `arp run status --run <directory>`. A read-only adapter also summarizes supported legacy manifests without converting or rewriting them. Legacy corpus/research/author commands keep their original recovery instructions. Never assume one run format can be substituted for another. Keep each frozen selection unchanged and use a new directory for changed scope.
