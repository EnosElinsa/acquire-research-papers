# Topic corpus

Input: copy [corpus.yaml](inputs/corpus.yaml), replace topic, venues, years, requested count and quotas with the user's requirements, and inspect `arp schema corpus-spec.schema.json`. The example count is a template, not a recommendation.

```text
arp discover corpus --spec <work>/corpus.yaml --output <work>/discovery --progress
arp review corpus --run <work>/discovery --decisions <work>/review-decisions.jsonl
arp acquire corpus --selection <work>/discovery/selection-manifest.json --output <delivery>
```

Between discovery and review, the executing agent must inspect `evidence-packets.jsonl` and create title-and-abstract decisions bound to actual packet hashes. Keywords are optional; full text is not required for corpus relevance. Use v2 reviewer metadata naming the real host, and preserve specialized corpus fields. Missing abstracts stay pending. Selection only uses explicit accepted decisions and retains coverage/quota shortfalls.

Expected output: coverage records, immutable evidence packets, reviewed candidates, a frozen selection, verified official pairs, and manual/retry queues. Discovery performs no acquisition.

Recovery: rerun discovery with the same spec and directory to retry partial slices, then import decisions and acquire from the same manifest. For a manual item, run `arp manual-fetch --selection <work>/discovery/selection-manifest.json --key <selection-id> --output <delivery> --watch <downloads>`, then rerun acquisition. Use a new run for changed scope or hashes; do not edit the frozen list.

Limits: metadata-provider coverage is bounded and failures remain visible. Do not lower relevance thresholds or remove inaccessible records to fill a quota. See [corpus mode](../references/corpus-mode.md).
