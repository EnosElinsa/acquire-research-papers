# Host installation and checked support

The same `SKILL.md`, references, templates, schemas, launcher, and fixed wheel are used by every host. The running agent reads evidence and makes semantic decisions; the Python CLI performs deterministic operations. No host SDK is imported by the capability services. This package does not install an agent orchestrator or permanent service.

## Install the exported skill

Resolve the actual installed directory rather than assuming a host tool name. Python 3.11+ and uv are required by the portable launcher. `agents/openai.yaml` supplies Codex presentation metadata and is harmless to other hosts; it does not change the shared workflow.

Fresh launcher caches use the platform cache base plus `acquire-research-papers/runtimes/`. Existing `Codex/runtimes/acquire-research-papers/` caches at that platform base are reused in place for compatibility; no copy or conversion is performed. `ARP_RUNTIME_ROOT` explicitly overrides either choice. The launcher still validates the wheel hash and installed marker before reuse. This runtime cache is separate from `ARP_CONFIG_ROOT` and `ARP_DATA_ROOT`.

| Host | User directory | Project directory | Host discovery/invocation |
| --- | --- | --- | --- |
| Codex | `~/.agents/skills/acquire-research-papers/` | `.agents/skills/acquire-research-papers/` | Mention `$acquire-research-papers` or use the host's skills selector. |
| Claude Code | `~/.claude/skills/acquire-research-papers/` | `.claude/skills/acquire-research-papers/` | Invoke `/acquire-research-papers` or let description matching load it. |
| Kiro IDE | `~/.kiro/skills/acquire-research-papers/` | `.kiro/skills/acquire-research-papers/` | Agent Steering & Skills → Import a skill → local folder or the repository's skill subdirectory. |
| Kiro CLI | `~/.kiro/skills/acquire-research-papers/` | `.kiro/skills/acquire-research-papers/` | Default agent discovers skills; custom agents require explicit `skill://` resources. |

The repository's safe copy installer accepts `--host codex`, `--host claude-code`, `--host kiro-ide`, or `--host kiro-cli` instead of an explicit `--target`. It copies only an exported, allowlisted skill; existing targets require `--replace` and retain a backup. `--project-root <directory>` chooses that workspace's host directory. The installer still refuses Git checkout targets and links, including a project directory inside a Git checkout. Preserve an existing developer checkout and use a different user skill directory or the host's reviewed import flow.

```text
python scripts/install_skill.py --source <exported-skill-directory> --host claude-code
python scripts/install_skill.py --source <exported-skill-directory> --host kiro-cli
python <installed-skill-directory>/scripts/arp.py doctor --host kiro-cli --skill-directory <installed-skill-directory>
```

These installation-script commands run from a source checkout; the exported thin skill contains only `scripts/arp.py`. End users can copy the folder from the release ZIP directly to the indicated host directory. Do not copy the whole source repository into a skill directory.

## Kiro custom-agent template

Copy [the Kiro resource example](../templates/kiro-agent.example.json) into a custom agent's configuration or merge its `resources` entries into an existing configuration. Replace its name if needed. Preserve any existing resource entries and permission choices.

```json
{
  "name": "research-papers",
  "resources": [
    "skill://.kiro/skills/acquire-research-papers/SKILL.md",
    "skill://~/.kiro/skills/acquire-research-papers/SKILL.md"
  ]
}
```

Only include the location actually installed if the other location does not exist. This template grants no shell, browser, network, or credential permission. Follow the selected host's normal tool-permission and user-interaction model.

## Inspect this installation

`arp doctor --host <host>` is a local inventory. `--skill-directory` selects an explicit path; otherwise a user directory is assumed, or `--project-root` selects a workspace path. It reports Python/runtime versions, the skill manifest, runtime schemas, executable presence, non-secret configuration state, and optional dependency presence. It neither bootstraps another runtime nor opens a browser.

- `--check-host-version` opts into running only the selected CLI executable with `--version`; IDE version detection remains unknown.
- `--remote-check` opts into a credential-free Crossref reachability probe. It does not test keyed providers, publisher permissions, or institution access.
- `host_load: unverified` means the host has not confirmed loading or invocation. File presence is not proof of host integration.
- A configured key is not proof of current API entitlement; legacy DPAPI is reported as unchecked by this local inventory.
- Institution access remains `unverified`; use `arp config ieee doctor --profile <id> --reference <representative-IEEE-reference>` for a separate live check. An open-access paper does not establish subscription access.

## Verification scope and sources

Host paths and discovery guidance were checked against official documentation on **2026-10-20**: [Codex skills](https://developers.openai.com/codex/skills/), [Claude Code skills](https://code.claude.com/docs/en/skills), [Kiro skills](https://kiro.dev/docs/skills/), and [Kiro custom-agent configuration](https://kiro.dev/docs/custom-agents/configuration-reference/). Kiro's skills page is dated October 2, 2026.

Documentation compatibility and unit-test fixtures are not real-host certification. Record actual host version, OS, date, command, and observed scope when running a live check. Until recorded, Claude Code and Kiro execution are **not live verified**. Core Python commands target Windows/macOS/Linux; IEEE browser integration and legacy DPAPI retain a Windows requirement in the current implementation. Cross-platform synthetic CI does not verify live publisher or institutional access.
