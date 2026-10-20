# Independent capabilities and composition

Every command below can be invoked independently. Output directories, inputs, and decisions are explicit; the runtime does not invent a new task type for an author check, corpus, Related Work section, or gap analysis. Use `arp` as shorthand for `python <installed-skill-directory>/scripts/arp.py`.

| Capability | Command | Contract |
| --- | --- | --- |
| Resolve identity | `metadata resolve --input <DOI-or-URL> --output <result.json>` | Normalizes exact supplied identity; preserves conflicts and unresolved identity. It performs no discovery or download. |
| Discover candidates | `discover candidates --query <query> --venue <name> --year <year> --output <records.json>` | Candidate records, coverage, and provider diagnostics; no implicit selection or download. Venue/year flags are repeatable. |
| Enrich metadata | `metadata enrich --input <records.json> --output <enriched.json>` | Field provenance, content hashes, conflicts, and provider failures; never fabricates an abstract. |
| Merge/compare collections | `collection merge/compare --left <a.json> --right <b.json> --output <result.json>` | Exact DOI/official identity set operations. Similar titles are review hints, never automatic identity. |
| Validate decisions | `review import --records <records.json> --decisions <decisions.jsonl> --policy identity/relevance --output <reviews.json>` | Rejects stale hashes and unknown identities; identity and relevance policies retain different evidence requirements. |
| Freeze a selection | `selection freeze --records <records.json> --decisions <decisions.jsonl> --policy identity/relevance --run <selection-directory>` | Explicit accepted records produce the existing immutable `selection-manifest.json` and `selected-papers.jsonl`. Optional `--maximum` does not relax review evidence. |
| Acquire | `fetch --input <DOI-or-official-URL> --output <directory>` or `acquire selection --selection <manifest.json> --output <directory>` | Shared official PDF/raw BibTeX verification, publisher boundaries, manual handoff, and retry queues. |
| Verify local files | `verify --pdf <paper.pdf> --bibtex <paper.bib> --expected <metadata.json> --output <result.json>` | Checks an existing pair without fetching. User-supplied files remain user-supplied; verification alone does not create publisher provenance. |
| Parse a local PDF | `parse --pdf <paper.pdf> --output <parse-result.json>` | Works without BibTeX through the internal cache. No upgrade to official-acquisition trust; ordinary acquisition still requires the pair. |
| Validate evidence | `evidence validate --parse-result <parse-result.json> --records <evidence.jsonl> --output <result.json>` | Exact PDF and Markdown hashes plus short located full-text evidence; rejects excerpts missing from the bound text. |
| Manage a library | `library audit`, `update/import/organize`, `apply`, `apply --rollback` | Audit, plan, apply, and rollback remain separate. Keep source hashes, backups, and journal. |
| Export structured records | `export --input <records.json> --format json/csv/markdown --output <file>` | Formats existing structured records. It does not discover, acquire, or export cached full text. |

Pass a separate `--run <directory>` to capability commands that expose it to record input references, parameters, output hashes, per-item states, and next actions. Resume with identical inputs and the same directory; completed artifacts are rechecked. `arp run status --run <directory>` summarizes a capability run or reads supported legacy manifests through a read-only adapter. It does not convert or rewrite legacy files; legacy acquisition/research commands remain the way to resume their original runs.

Metadata/collection outputs contain a `records` array and may be reused directly where a records input is accepted. JSON Lines and a top-level JSON array are also accepted. Export writes a file, while acquisition writes a delivery directory. Keep all output and run paths outside the skill repository; never point an output at a credential file.

`metadata enrich` and `selection freeze` consume full candidate records: `key`, `title`, `year` (integer), `venue`, `relevance_score` (number), `hard_gates_passed` (boolean), and `evidence_fields` (field-name array), plus a resolvable `doi` or `official_url`. Prefer the complete records emitted by discovery. For a user-supplied record, a missing abstract is `""`, an unused score is `0`, and unverified hard gates are `false`; never default a gate to true or invent title/year/venue. Optional authors/keywords default to empty arrays. Complete identity and metadata review before freezing; relevance acceptance additionally requires the actual title and abstract. Identity resolution or collection comparison alone accepts partial records and does not fill these candidate fields.

## Agent review contract

The current agent performs semantic review. Python validates the evidence and provenance; no score or keyword can replace a review. Query and title matching nominate candidates, relevance acceptance requires title, abstract, and passed hard gates, and claim-level relations require full text. Preserve immutable input bytes and hashes.

New reviews use `schema_version: 2`, `reviewer` equal to the actual executing host, and an `executor` object with the same `host`. Add `model` and host `version` only when actually available; omit them otherwise. Do not label a Claude Code or Kiro review as Codex. Unversioned/v1 Codex reviews remain readable without rewriting their bytes or changing existing hashes.

```json
{
  "schema_version": 2,
  "reviewer": "claude-code",
  "executor": {"host": "claude-code"},
  "identity": "doi:10.1234/example",
  "input_sha256": "<exact-record-content-hash>",
  "policy": "identity",
  "policy_version": "identity-review-1",
  "decision": "accept",
  "evidence": ["doi"],
  "reason": "The supplied DOI matches the requested identity."
}
```

This is the generic capability format; corpus, research, and full-text importers retain their specialized candidate IDs, hash names, and evidence fields. `input_sha256` is SHA-256 over the exact record serialized as UTF-8 JSON with keys sorted, `ensure_ascii=False`, and compact separators `(',', ':')`; changing a field requires a new review. Obtain the running release's authoritative contracts with `arp schema capability-review.schema.json` (or the specialized schema) and inspect the immutable packets. Never copy a sample hash or accept decision into a real run.

For standalone `evidence validate`, copy `paper_id`, `full_text_sha256`, and `markdown_sha256` from the unchanged parse result. Each nested evidence record's `paper_id` must match that parse identity. Include the real host review provenance and located excerpts from its bound Markdown; an unrelated file with matching words is not evidence.

## Standalone full-text evidence

Run `arp parse --pdf <paper.pdf> --output <work>/parse-result.json --run <work>/parse-run`. Read the returned Markdown before writing evidence. `arp schema capability-evidence-review.schema.json` returns this import contract. Copy the following JSON array to `<work>/evidence-review.json`, replacing every angle-bracket placeholder with observed values. For JSONL input, write each top-level review object on one line without the enclosing array.

```json
[
  {
    "schema_version": 2,
    "reviewer": "kiro-cli",
    "executor": {"host": "kiro-cli"},
    "policy": "fulltext",
    "policy_version": "fulltext-review-1",
    "reason": "<why this exact parsed document supports this reviewed relation>",
    "full_text_sha256": "<copy the exact 64-character PDF hash from parse-result.json>",
    "markdown_sha256": "<copy the exact 64-character Markdown hash from parse-result.json>",
    "records": [
      {
        "claim_id": "claim-1",
        "paper_id": "<copy parse-result.paper_id: sha256 followed by colon and the PDF hash>",
        "relation": "direct-support",
        "read_scope": "full-text",
        "section": "<the observed section heading>",
        "page": null,
        "excerpt": "<a short exact excerpt from the bound Markdown, at most 500 characters>",
        "explanation": "<how the located excerpt bears on the stated claim>",
        "uncertainty": "<remaining limits or qualifications>"
      }
    ]
  }
]
```

Set both host fields to the actual host; omit unknown model/version metadata. Replace `direct-support` with `indirect-support`, `qualifies`, `contradicts`, or `background` when warranted. Direct support and contradiction require an observed section or positive PDF page; do not invent a page label. Every row still requires a short exact full-text excerpt. The top-level `policy`, `policy_version`, `reason`, and both artifact hashes are mandatory, and every nested `paper_id` is the parse result's `sha256:<PDF-hash>` identity.

```text
arp evidence validate --parse-result <work>/parse-result.json --records <work>/evidence-review.json --output <work>/validated-evidence.json --run <work>/evidence-run
arp run status --run <work>/evidence-run
```

Validation rechecks the PDF/Markdown bytes, review schema and provenance, paper identity, located relation, and excerpt membership. The result includes validated `records`, original `reviews`, and claim `coverage` with counts, paper identity, full-text hash, and read scope. Coverage lists claims actually present in accepted evidence; it does not imply that omitted claims or all possible papers were reviewed. User-supplied parsing remains `source_trust: user-supplied` and does not establish an official publisher PDF/BibTeX pair. For an empty or insufficient parse, report the unresolved claim rather than fabricating a record.

## Status and recovery

Distinguish `agent_review`, `user_download`, `configuration_required`, `rate_limited`, `retryable`, and permanent `failed` item states. Complete unrelated papers while preserving blocked items. Do not convert missing input to a fabricated empty success or overwrite a changed output. Hash conflicts require investigation and a new reviewed run when inputs intentionally change. A lock prevents concurrent use of the same capability run. See [seven composition recipes](../examples/README.md).
