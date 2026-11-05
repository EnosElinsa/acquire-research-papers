# Manual downloads

Some papers can only be downloaded by the user in a normal authorized browser: ScienceDirect always, and any paper that [acquisition](acquisition.md) wrote to `manual-download.csv`. `manual-fetch` takes over the files you download, identifies and verifies them, and places them in the reserved delivery paths.

## ScienceDirect manual handoff

ScienceDirect remains manual by design. Configure an Elsevier API key if the task needs official expected-identity resolution:

```powershell
python "$skill/scripts/arp.py" config setup elsevier
```

Start the watcher before downloading:

```powershell
python "$skill/scripts/arp.py" manual-fetch `
  --input "10.1016/j.asieco.2024.101746" `
  --watch "$HOME\Downloads" --output C:\Research\papers
```

The CLI opens only the canonical article page. The user completes organization login and downloads the official PDF plus raw BibTeX in a normal browser. The CLI observes only stable new or changed files, verifies the pair, and delivers it. It never controls ScienceDirect, reads the user's Chrome profile, exports cookies, or turns an Article Retrieval API 403 into scripted website login.

## Files you already have

If both files already exist:

```powershell
python "$skill/scripts/arp.py" manual-fetch --input <DOI> `
  --pdf .\paper.pdf --bibtex .\citation.bib --output C:\Research\papers
```

## Items of a frozen corpus

For a frozen corpus item, use its immutable selection ID:

```powershell
python "$skill/scripts/arp.py" manual-fetch `
  --selection C:\Research\corpus-run\selection-manifest.json `
  --key <selection-id> --output C:\Research\corpus-delivery `
  --watch "$HOME\Downloads"
```

## The whole manual queue

To work through the whole `manual-download.csv` of an acquisition in one session, use `--queue`. It opens each paper's official page in turn, imports pairs in whatever order they are downloaded, and updates the queue. Add `--from <folder>` instead of `--watch` when the files are already downloaded:

```powershell
python "$skill/scripts/arp.py" manual-fetch `
  --selection C:\Research\corpus-run\selection-manifest.json `
  --queue --output C:\Research\corpus-delivery --watch "$HOME\Downloads"
```
