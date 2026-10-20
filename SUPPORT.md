# Help and feedback / 使用帮助与反馈

Start with the [English guide](README.md), [中文指南](README.zh-CN.md), [release downloads](https://github.com/EnosElinsa/acquire-research-papers/releases/latest), and [changelog](CHANGELOG.md). Developer builds and safe migration are described in [CONTRIBUTING.md](CONTRIBUTING.md).

## Installation and updates

- Use Python 3.11+ and uv. The standard `npx skills` installer also needs Node.js/npm; manual ZIP installation avoids that installer requirement. IEEE browser access needs Windows, PowerShell, and Node.js.
- Copy only the folder inside the skill ZIP. A source-code archive is for development. Preserve any existing Git checkout and install the thin skill into a different directory.
- The launcher normally downloads a fixed GitHub release wheel and verifies `runtime.json`. A digest mismatch is an integrity failure: re-download the published asset and compare `SHA256SUMS`; do not edit the expected hash to bypass the check.
- `ARP_LOCAL_WHEEL` must point to the exact matching wheel, not a differently rebuilt file with the same version. A local wheel does not itself provide all dependencies for offline installation.
- Updates preserve external runtime state. A new runtime version can need fresh dependency installation; it does not imply that a stored institution session remains valid.

安装或更新时请保留原有开发 checkout，只复制 ZIP 内的轻量 skill 文件夹。摘要不匹配时先核对发布页和 `SHA256SUMS`，不要关闭校验。请先确认 Python、uv、Node.js 等前置条件，再提交问题。

## Institution access

Use `arp config status --details`, `arp config ieee list`, and a representative `arp config ieee doctor --profile <id> --reference <DOI-or-IEEE-URL>`. A stored profile or old successful check does not establish current access. An open-access paper is not a subscription test.

Start a new institution with assisted manual login and its official entry URL. CAPTCHA, QR codes, OTP, and MFA remain user actions in the dedicated visible browser. Automatic CARSI forms need an explicitly reviewed contract and exact credential hostname. Do not broaden a hostname or repeatedly submit credentials to make a page pass.

不同学校先使用人工登录。报告问题时只提供经脱敏的阶段、精确主机名和表单类型；不要上传账户、密码、浏览器 profile、Cookie、SAML 内容、URL 查询参数或含私人信息的截图。

## Local library changes

Audit evidence before applying a plan. A matching filename or current BibTeX does not establish the PDF's identity/version. Use `--metadata` with an empty JSON object for a network-free audit. Keep plans and backups until verified. If source/output hashes changed, inspect the external edit and generate a new plan instead of forcing a previous plan onto it. Rollback must also respect later edits.

ScienceDirect downloads remain manual. Start the watcher before downloading new pairs, or explicitly import files already present. Author discovery may report missing sources, truncation, and namesakes; it cannot certify a complete bibliography.

## Report a problem or suggest an improvement

Use the [issue forms](https://github.com/EnosElinsa/acquire-research-papers/issues/new/choose). Include the release version, OS, installation method, command shape with private paths replaced, expected/actual behavior, and a minimal synthetic reproduction. Share only redacted diagnostic fields. Do not attach your paper collection, secrets file, browser state, access tokens, signed links, or institutional sessions.

For credential exposure, host-boundary failures, unsafe file replacement, or other vulnerabilities, use [private reporting](https://github.com/EnosElinsa/acquire-research-papers/security/advisories/new) and [SECURITY.md](SECURITY.md), not a public issue. Support and feature requests have no guaranteed response time.
