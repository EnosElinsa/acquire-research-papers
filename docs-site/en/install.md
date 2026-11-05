# Install

Install the skill with the standard Skills installer (Node.js/npm required); no developer clone or development dependency sync is needed:

```text
npx skills add EnosElinsa/acquire-research-papers --skill acquire-research-papers -a codex -g
```

Use Python 3.11+ and [uv](https://docs.astral.sh/uv/). Resolve the actual directory returned by the installer; the shared default is normally `~/.agents/skills/acquire-research-papers`:

```powershell
$skill = Join-Path $env:USERPROFILE ".agents/skills/acquire-research-papers"
python "$skill/scripts/arp.py" --help
python "$skill/scripts/arp.py" config status
```

The standard-library launcher reads `runtime.json`, downloads the fixed release wheel, verifies SHA-256, and installs it with uv into a separate cache. It never needs a developer checkout or installs development tools into the skill. File configuration and core commands support Windows/macOS/Linux. Current IEEE browser access and legacy DPAPI require Windows, PowerShell, and Node.js; on macOS and Linux, IEEE papers join the manual-download queue. Live institutional access needs a separate check.

Update by rerunning the same Skills install command. Registries, credentials, caches, named institution profiles, and browser sessions live outside the installed skill. Use a separate delivery directory. Development builds can use the digest-verified local-wheel procedure in [CONTRIBUTING.md](https://github.com/EnosElinsa/acquire-research-papers/blob/main/CONTRIBUTING.md).

!!! warning "Developer checkouts"
    If your current skill directory is a Git developer checkout, preserve it. Do not point a third-party installer's overwrite operation at that directory. Build an export and use the repository's safe copy installer into a new directory; it refuses `.git` targets and keeps an explicit backup when replacing a clean previous thin skill. See [safe migration](https://github.com/EnosElinsa/acquire-research-papers/blob/main/CONTRIBUTING.md#safe-copy-and-checkout-migration).

## Host setup and checked support

Codex, Claude Code, Kiro IDE, and Kiro CLI share the same skill and pinned wheel. User skill directories are `~/.agents/skills/`, `~/.claude/skills/`, and `~/.kiro/skills/` respectively. Copy only the exported `acquire-research-papers/` folder. Kiro custom agents require explicit `skill://` resources; a [resource template](https://github.com/EnosElinsa/acquire-research-papers/blob/main/skills/acquire-research-papers/templates/kiro-agent.example.json) is included. See [host installation and official sources](https://github.com/EnosElinsa/acquire-research-papers/blob/main/skills/acquire-research-papers/references/hosts.md), checked on **October 20, 2026**.

Run `arp doctor --host <codex|claude-code|kiro-ide|kiro-cli> --skill-directory <actual-path>`. Its default local inventory reports Python/runtime/schema/configuration/dependency state. Host loading and institutional access remain unverified. `--check-host-version` explicitly runs the host executable's version command; `--remote-check` explicitly probes public Crossref reachability without credentials. Official format compatibility and synthetic CI are not live certification; Claude Code and Kiro interactive execution remain unverified until recorded.

## Release assets and manual installation

Every [GitHub release](https://github.com/EnosElinsa/acquire-research-papers/releases/latest) provides:

| Asset | Use |
| --- | --- |
| `acquire-research-papers-skill-<version>.zip` | Extract and copy the contained `acquire-research-papers/` folder to a new skill directory. It contains instructions, references, schemas, a launcher, and the pinned runtime manifest. |
| `acquire_research_papers-<version>-py3-none-any.whl` | Install the CLI independently with `uv tool install <wheel-path>`, or supply its absolute path as `ARP_LOCAL_WHEEL` when bootstrapping offline. The launcher still verifies the manifest digest. |
| `SHA256SUMS` | Compare downloaded asset hashes with `Get-FileHash <path> -Algorithm SHA256` on PowerShell or `sha256sum <path>` on Linux. |

Manual skill installation needs Python 3.11+ and uv. The launcher normally downloads its pinned wheel on first use; dependency installation also needs network access or a populated uv cache. Node.js and Google Chrome are additionally required for IEEE browser access. Do not copy the source archive or a developer checkout into the skill directory. See [SUPPORT.md](https://github.com/EnosElinsa/acquire-research-papers/blob/main/SUPPORT.md) for bootstrap and migration troubleshooting.

## Verify a release

From v0.16.0 on, the [release provenance workflow](https://github.com/EnosElinsa/acquire-research-papers/actions/workflows/provenance.yml) rebuilds every published release from its tag on Linux and on Windows. It requires both rebuilds, the tag's `runtime.json` pin, and the published wheel and ZIP to be identical byte for byte, and then records a GitHub artifact attestation for the two files. Check a downloaded asset with the [GitHub CLI](https://cli.github.com/):

```text
gh attestation verify acquire_research_papers-<version>-py3-none-any.whl --repo EnosElinsa/acquire-research-papers
gh attestation verify acquire-research-papers-skill-<version>.zip --repo EnosElinsa/acquire-research-papers
```

A passing check means the file's SHA-256 matches a build that this repository's workflow produced from the release tag. Releases before v0.16.0 have no attestation; compare their hashes with `SHA256SUMS` instead.
