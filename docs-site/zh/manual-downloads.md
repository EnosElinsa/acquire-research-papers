# 人工下载

有些论文只能由用户在正常授权浏览器中下载：ScienceDirect 始终如此，[自动获取](acquisition.md)写入 `manual-download.csv` 的论文也是如此。`manual-fetch` 接管用户下载的文件，识别并核验后放入预留交付位置。

## ScienceDirect 人工接管

ScienceDirect 按设计保持人工模式。需要解析官方预期身份时，先配置 Elsevier API key：

```powershell
python "$skill/scripts/arp.py" config setup elsevier
```

下载前先启动监听：

```powershell
python "$skill/scripts/arp.py" manual-fetch `
  --input "10.1016/j.asieco.2024.101746" `
  --watch "$HOME\Downloads" --output C:\Research\papers
```

CLI 只打开规范的论文页面。用户在正常 Chrome（或其他授权浏览器）中完成 organization login，并下载正式 PDF 和原始 BibTeX。CLI 只观察稳定的新文件或变更文件，核验后交付。它不会控制 ScienceDirect，不会读取用户 Chrome profile，不会导出 Cookie，也不会把 Article Retrieval API 的 403 转成脚本化网站登录。

## 已有文件

如果两个文件已经存在：

```powershell
python "$skill/scripts/arp.py" manual-fetch --input <DOI> `
  --pdf .\paper.pdf --bibtex .\citation.bib --output C:\Research\papers
```

## 冻结论文集中的条目

冻结论文集中的人工条目应使用不可变 selection ID：

```powershell
python "$skill/scripts/arp.py" manual-fetch `
  --selection C:\Research\corpus-run\selection-manifest.json `
  --key <selection-id> --output C:\Research\corpus-delivery `
  --watch "$HOME\Downloads"
```

## 整个人工队列

要在一次会话里处理完整个 `manual-download.csv`，使用 `--queue`：它依次打开每篇论文的正式页面，按下载到达的任意顺序导入，并更新队列。文件已经下载好时，用 `--from <文件夹>` 代替 `--watch`：

```powershell
python "$skill/scripts/arp.py" manual-fetch `
  --selection C:\Research\corpus-run\selection-manifest.json `
  --queue --output C:\Research\corpus-delivery --watch "$HOME\Downloads"
```
