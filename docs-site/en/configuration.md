# Configuration

## First use: configure only what this task needs

Start by asking which optional capabilities are already configured:

```powershell
python "$skill/scripts/arp.py" config status
```

The command returns capability booleans only; `--details` adds non-secret profile/history details. File values are read for presence and never emitted; legacy DPAPI status inspects scope shape without decrypting secrets. A `true` result means local configuration exists; it does not prove live API or publisher entitlement. Configure only a capability required by this task, then test it with a representative operation.

| Capability | Configure it when | Setup |
| --- | --- | --- |
| None | Public Crossref discovery; discovery and acquisition from the official ACL, IJCAI, AAAI, NeurIPS, ICLR (2024 on), PMLR, CVF, and USENIX archives; open-access Springer papers | No secret setup |
| Semantic Scholar | You want keyed candidate search, higher limits, and the first DOI abstract-enrichment pass | `arp config setup semantic_scholar` |
| OpenAlex | You need IEEE or ACM conferences enumerated through their OpenAlex series (INFOCOM, ICC, GLOBECOM, SIGCOMM, and others), additional candidate search, or a second DOI abstract-enrichment pass | `arp config setup openalex` |
| IEEE | You need institutional IEEE access; start with manual login and optionally enable a supported CARSI form | `arp config setup ieee` |
| Elsevier | You need official metadata resolution for the manual ScienceDirect handoff | `arp config setup elsevier` |
| MinerU | You need selected PDFs parsed for internal full-text analysis or explicit Markdown export | `arp config setup mineru` |

!!! danger "Keep secrets out of chat"
    Secret prompts are interactive and non-echoing; institution names and official entry URLs are ordinary non-secret inputs. Never paste a password, API key, token, or cookie into chat, an agent message, a command argument, or a repository file.

Local editing of the selected credential file outside the repository is supported. Provider updates are independent: adding OpenAlex does not replace IEEE, MinerU, Elsevier, or Semantic Scholar.

## Editable local credentials

New installations default to an editable local file backend outside the repository. Use `arp config init`, `arp config path`, and `arp config edit`; `config edit --profile <id>` opens one institution's file. The configuration root contains `config.toml`, `.env`, `institutions/<id>.json`, and `credentials/<id>.env`. `ARP_CONFIG_ROOT` overrides the platform configuration root; `ARP_DATA_ROOT` isolates runtime data. New data roots use the application's own name; detected legacy roots remain compatible.

The root `.env` contains `SEMANTIC_SCHOLAR_API_KEY`, `OPENALEX_API_KEY`, `ELSEVIER_API_KEY`, and `MINERU_TOKEN`. A selected institution file contains `INSTITUTION_USERNAME` and `INSTITUTION_PASSWORD`. [Empty templates](https://github.com/EnosElinsa/acquire-research-papers/blob/main/skills/acquire-research-papers/templates/.env.example) ship without values. Files are plaintext restricted to the current user: edit locally, keep private, and never commit them. Saving credentials does not enable automatic login.

Crossref answers requests that carry a contact address from its faster polite pool. To use it, put your own address in `config.toml` under `[discovery]` as `contact_email = "..."`, or set `ARP_CONTACT_EMAIL`; `arp config status --details` shows whether one is set. Nothing is filled in for you, and the address is left out of recorded query URLs.

API precedence is explicit process environment → one selected file; file selection is `--env-file` → `ARP_ENV_FILE` → default `.env`. There is no upward search, implicit dotenv merging, shell execution, or interpolation. Each command reads a snapshot; empty values are unconfigured. Institutions read only their selected profile file. Existing DPAPI installations stay legacy; explicit `arp config migrate --from dpapi` runs on the original Windows account, preserves the source, reports conflicting key names, and never overwrites conflicts. See [configuration details](https://github.com/EnosElinsa/acquire-research-papers/blob/main/skills/acquire-research-papers/references/credentials-and-cache.md).

## Named institution profiles

The examples use `arp` as shorthand for `python <skill-directory>/scripts/arp.py`.

```text
arp config setup ieee --profile my-institution --mode assisted
arp config ieee list
arp config ieee use my-institution
arp config ieee login --profile my-institution
arp config ieee doctor --profile my-institution --reference <IEEE-URL>
```

IEEE supports `direct`, `assisted`, and explicit-contract `carsi` profiles, each with an isolated browser context. Profile configuration, identity-provider login, return to IEEE, a verified download, and institutional entitlement are separate states. An open-access download does not establish subscription entitlement. See [IEEE institutional access](ieee.md) and the [configuration reference](https://github.com/EnosElinsa/acquire-research-papers/blob/main/skills/acquire-research-papers/references/configuration.md).
