# Gap analysis

Input: copy [gap-analysis.yaml](inputs/gap-analysis.yaml). State a falsifiable distinction and the searched scope; describe scenario, mechanism, decisions, objectives and constraints. Supply seeds only when known.

```text
arp discover research --brief <work>/gap-analysis.yaml --output <work>/gap-run
arp review research --run <work>/gap-run --decisions <work>/gap-candidate-review.jsonl
arp acquire research --run <work>/gap-run
arp evidence research --run <work>/gap-run --records <work>/gap-evidence-review.jsonl
```

The agent reviews immutable packets between commands. Use all four search passes: terminology/synonyms, decomposed problem dimensions, backward/forward/related graph expansion, and explicit falsification queries seeking prior equivalent mechanisms. Do not treat low keyword overlap as novelty. Inspect recent and classic work and the closest counterexamples in full text.

For every selected paper record its relation to the proposed distinction, located evidence, uncertainty, and exact artifact hashes. Use the actual host in v2 review provenance and omit unknown model/version metadata. Complete candidate review before freezing; acquire before claim evidence.

Expected output: scope and coverage record, citation graph, reviewed closest-paper selection, full-text evidence matrix, claim coverage and bounded `gap-analysis.md`. State conclusions as limited to searched scope and checked evidence.

Recovery: use the same run for pending publisher downloads, parsing and evidence imports; follow [Related Work recovery](05-related-work.md). Use a new run for changed claims/scope, preserve prior evidence as a snapshot, and compare the resulting structured records with `collection compare` when useful. A blocked paper remains selected and pending.

Limits: no finite search proves universal absence of prior work. Unknown full-text evidence and provider failures must appear in the conclusion. A gap report is not an automatic novelty claim or manuscript narrative.
