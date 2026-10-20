# Known list acquisition

Input: copy [known-papers.json](inputs/known-papers.json) and populate `records` with the exact DOI/official URL for every requested paper. Do not invent identifiers from a title match. Empty records mean no requested papers and must be reported as such.

1. Normalize each supplied DOI or official URL, retaining ambiguities. For example, run `arp metadata resolve --input <one-real-DOI> --output <work>/identity-1.json --run <work>/identity-run-1`. This capability is offline; a syntactically resolved identity is not publisher verification.
2. Fetch each resolved paper: `arp fetch --input <same-real-DOI-or-official-URL> --output <delivery>/paper-1`. Keep a separate reserved output for each paper and record each command result. One inaccessible paper does not block the rest.
3. For an official pair already downloaded, use `arp verify --pdf <paper.pdf> --bibtex <paper.bib> --expected <reviewed-metadata.json> --output <work>/verification.json --run <work>/verification-run`. Expected metadata requires title/year and preferably DOI/authors/venue; this does not establish publisher origin for arbitrary local files.
4. For a user-driven publisher handoff, use `arp manual-fetch --input <DOI-or-official-URL> --watch <downloads> --output <delivery>/paper-1`. Start the watcher before downloading. Alternatively pass `--pdf` and `--bibtex` for files already present.

Expected output: verified publisher PDF/raw BibTeX pairs and provenance, or a specific manual/retry/access result per paper. Ordinary fetch produces no Markdown.

Recovery: retry the same identity and output after resolving the stated cause; retain existing hashes and provenance. `arp run status --run <work>/identity-run-1` checks the optional capability record. Do not overwrite a mismatched pair or substitute generated BibTeX. For an explicit reviewed batch, use `selection freeze --policy identity` and `acquire selection` from [capabilities](../references/capabilities.md).

Limits: exact-title ambiguity requires agent/user identity review. Official access and native citation exports may require user action. ScienceDirect page interactions remain user-operated.
