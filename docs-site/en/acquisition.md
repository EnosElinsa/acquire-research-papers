# Acquisition

Acquisition starts from a DOI, an exact official URL, or a hash-verified frozen selection. The selected publisher adapter must keep every request inside its approved host boundary. A successful delivery requires:

- a valid official PDF;
- the publisher's raw BibTeX export, preserved verbatim;
- matching DOI, title, year, venue, and author scope;
- provenance and SHA-256 hashes tying the files to the same paper.

Crossref, OpenAlex, Semantic Scholar, repositories, and mirrors never satisfy final delivery.

## Failures stay visible

An inaccessible paper remains in the frozen selection and is written to `manual-download.csv`; a transient network or rate-limit failure goes to `retryable-downloads.csv`. One failure does not stop unrelated papers. A publisher without an adapter goes to the manual queue as `unsupported_adapter`. [Manual downloads](manual-downloads.md) explains how to work through the manual queue.

Use repeatable `--defer-host <exact-hostname>` options to defer a publisher for this run. Deferred records remain in the selection and enter the manual queue; verified prior deliveries remain delivered.

## Binding, reruns, and interruptions

The output directory is bound to one frozen selection before publisher contact. A rerun skips a delivered item only when every recorded path and hash still matches. For safety, an existing directory containing unbound PDFs, BibTeX files, or acquisition ledgers is rejected instead of being overwritten; use a clean delivery directory or a deliberate migration/import workflow.

The ledger is saved after every paper, so an interrupted run (Ctrl+C, a host timeout, a closed browser) resumes with the same command and output. Leftovers of the paper that was interrupted move to `.arp-interrupted/` instead of being deleted.

## Hosts, pacing, and pauses

A batch contacts up to four publisher hosts at the same time (`--parallel-hosts N`; `1` restores one paper at a time), and each host still gets one paper at a time. Requests to one host are spaced; www.usenix.org gets 10 s between requests, as its robots.txt asks. A host is paused for the rest of the run after HTTP 429, three consecutive transient failures, or an institution login failure. IEEE papers of one run share a single dedicated browser, so an institutional login is reused.

A command that runs longer than your agent's command timeout can run in its own process with `--background <job-dir>`; `arp job status` reports its progress and final result, and `arp job list` lists all jobs.
