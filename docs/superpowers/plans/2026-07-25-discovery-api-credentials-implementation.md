# Discovery API Credentials and DOI Abstract Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store discovery API keys in the existing DPAPI payload, expose safe configuration/status commands, and use OpenAlex as a second DOI abstract enricher.

**Architecture:** PowerShell owns encrypted persistence and exact-host secret release. A provider-neutral Python bridge loads optional keys into approved API clients without URLs, logs, or parent environment variables. Discovery runs Semantic Scholar enrichment first and OpenAlex DOI enrichment second, with opt-in sanitized progress written to stderr.

**Tech Stack:** Python 3.11+, argparse, httpx, pytest, Windows PowerShell/DPAPI CLIXML, Pester-style repository PowerShell assertions.

## Approved Public-Skill Addendum

This addendum extends the plan without replacing any original task. The public canonical status command is `arp config status`; `arp credentials status` remains a compatibility alias so existing instructions and callers continue to work. Every capability is optional and independent. The agent checks status for the current task and guides only the configuration that task needs.

### Task 0: Restore the Windows CI baseline

**Files:**
- Modify: `tests/powershell/test-secret-store.ps1`
- Modify only if necessary: `.github/workflows/test.yml`

- [ ] **Step 1: Reproduce the runner failure with module autoload disabled**

Run the PowerShell fixture with `$PSModuleAutoLoadingPreference = "None"` and verify that the current `ConvertTo-SecureString` fixture setup fails because `Microsoft.PowerShell.Security` is unavailable.

- [ ] **Step 2: Replace fixture-only conversions with pure .NET `SecureString` construction**

Add a small test helper using `[Security.SecureString]::new()`, `AppendChar`, and `MakeReadOnly`. Do not change production secret handling or weaken DPAPI assertions.

- [ ] **Step 3: Verify the exact runner mode and normal mode**

Both the module-autoload-disabled invocation and the repository's normal PowerShell test command must exit 0.

- [ ] **Step 4: Commit the CI baseline fix**

```powershell
git add tests/powershell/test-secret-store.ps1 .github/workflows/test.yml
git commit -m "fix: make PowerShell fixtures module-independent"
```

If the workflow itself does not require a change, do not stage it.

---

## File Map

- Create `src/acquire_research_papers/credentials.py`: provider/host registry, DPAPI reader bridge, credential-status bridge.
- Modify `src/acquire_research_papers/discovery/openalex.py`: DOI batch lookup.
- Modify `src/acquire_research_papers/discovery/coordinator.py`: optional sanitized progress callback.
- Modify `src/acquire_research_papers/cli.py`: DPAPI discovery-key wiring, OpenAlex enricher, `credentials status`, and `--progress`.
- Modify `scripts/secret-store.ps1`: generic API-key setter and validator.
- Create `scripts/read-discovery-api-key.ps1`: exact provider-host key release.
- Create `scripts/setup-discovery-api-keys.ps1`: hidden interactive multi-provider setup.
- Create `scripts/credential-status.ps1`: configured/missing status without decryption output.
- Preserve `scripts/setup-elsevier-api-key.ps1` and `scripts/read-elsevier-api-key.ps1` as compatibility entry points.
- Modify `tests/powershell/test-secret-store.ps1`: storage, migration, host boundary, setup, and status regressions.
- Create `tests/unit/test_credentials.py`: Python bridge regressions.
- Modify `tests/unit/test_discovery_clients.py`: OpenAlex DOI lookup regressions.
- Modify `tests/unit/test_discovery_coordinator.py`: enricher continuation and progress regressions.
- Modify `tests/unit/test_corpus_cli.py`: CLI status/progress/stdout regressions.
- Modify `tests/unit/test_skill_layout.py`, `SKILL.md`, `references/credentials-and-cache.md`, `references/corpus-mode.md`, `README.md`, and `README.zh-CN.md`: shipped-file and operator documentation.

### Task 1: Generic DPAPI API-key scopes

**Files:**
- Modify: `tests/powershell/test-secret-store.ps1`
- Modify: `scripts/secret-store.ps1`
- Create: `scripts/read-discovery-api-key.ps1`
- Create: `scripts/setup-discovery-api-keys.ps1`
- Create: `scripts/credential-status.ps1`

- [ ] **Step 1: Write failing PowerShell assertions**

Add synthetic secure strings for `semantic_scholar` and `openalex`, call a provider-neutral setter, and assert all existing scopes survive:

```powershell
Set-DiscoveryApiKey -Provider "semantic_scholar" -ApiKey $semanticKey -Path $secretPath
Set-DiscoveryApiKey -Provider "openalex" -ApiKey $openAlexKey -Path $secretPath
$payload = Import-AcquisitionSecrets -Path $secretPath
Assert-Equal (ConvertFrom-AcquisitionSecureString $payload.Scopes.api_keys.semantic_scholar) "synthetic-semantic-key" "Semantic Scholar key"
Assert-Equal (ConvertFrom-AcquisitionSecureString $payload.Scopes.api_keys.openalex) "synthetic-openalex-key" "OpenAlex key"
Assert-Equal $payload.Scopes.ieee_institution.Credential.UserName "synthetic-user" "existing IEEE scope"
```

Test exact-host release for all mappings and reject `api.openalex.org.evil.example`, `API.OPENALEX.ORG.`, schemes, ports, paths, wildcard forms, and provider-host mismatches. Test `credential-status.ps1` output contains only booleans/provider names and none of the synthetic values.

- [ ] **Step 2: Run the PowerShell test and verify RED**

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tests/powershell/test-secret-store.ps1
```

Expected: failure because `Set-DiscoveryApiKey` and the three new scripts do not exist.

- [ ] **Step 3: Implement the closed provider mapping and atomic updates**

Add to `secret-store.ps1`:

```powershell
function Get-DiscoveryApiProviderHost([string]$Provider) {
  switch ($Provider.Trim().ToLowerInvariant()) {
    "semantic_scholar" { return "api.semanticscholar.org" }
    "openalex" { return "api.openalex.org" }
    "elsevier" { return "api.elsevier.com" }
    default { throw "Unsupported discovery API provider." }
  }
}

function Set-DiscoveryApiKey(
  [string]$Provider,
  [Security.SecureString]$ApiKey,
  [string]$Path = (Get-AcquisitionSecretPath)
) {
  if ($null -eq $ApiKey -or $ApiKey.Length -eq 0) { throw "API key is missing." }
  [void](Get-DiscoveryApiProviderHost $Provider)
  $name = $Provider.Trim().ToLowerInvariant()
  $payload = if (Test-Path -LiteralPath $Path -PathType Leaf) {
    Import-AcquisitionSecrets -Path $Path
  } else { New-AcquisitionSecretPayload }
  if ($payload.Scopes.PSObject.Properties.Name -notcontains "api_keys") {
    $payload.Scopes | Add-Member -NotePropertyName api_keys -NotePropertyValue ([pscustomobject]@{})
  }
  if ($payload.Scopes.api_keys.PSObject.Properties.Name -contains $name) {
    $payload.Scopes.api_keys.$name = $ApiKey
  } else {
    $payload.Scopes.api_keys | Add-Member -NotePropertyName $name -NotePropertyValue $ApiKey
  }
  Save-AcquisitionSecretPayload -Payload $payload -Path $Path
}
```

Validate every known API-key property as a nonempty `SecureString`. Make `Set-ElsevierApiKey` delegate to `Set-DiscoveryApiKey`.

Implement `read-discovery-api-key.ps1` with `-Provider`, `-ExpectedHost`, `-SecretPath`, and `-AllowMissing`; compare the expected host to `Get-DiscoveryApiProviderHost` with exact case-insensitive equality. Implement the setup script with hidden prompts and skip/replace choices. Implement status by inspecting encrypted scope shape without converting secure strings.

- [ ] **Step 4: Run PowerShell regressions and verify GREEN**

Run the Step 2 command. Expected: all PASS lines and exit code 0.

- [ ] **Step 5: Commit Task 1**

```powershell
git add scripts/secret-store.ps1 scripts/read-discovery-api-key.ps1 scripts/setup-discovery-api-keys.ps1 scripts/credential-status.ps1 tests/powershell/test-secret-store.ps1
git commit -m "feat: unify discovery API credentials"
```

### Task 2: Provider-neutral Python DPAPI bridge

**Files:**
- Create: `tests/unit/test_credentials.py`
- Create: `src/acquire_research_papers/credentials.py`
- Modify: `src/acquire_research_papers/acquisition/adapters/elsevier_api.py`

- [ ] **Step 1: Write failing Python tests**

Test exact arguments, optional missing output, ambiguous output, timeout handling, and secret-free exceptions:

```python
provider = DpapiApiKeyProvider(
    provider="openalex",
    expected_host="api.openalex.org",
    script=tmp_path / "read-discovery-api-key.ps1",
    secret_path=tmp_path / "secrets.clixml",
    process_runner=run,
)
assert provider.optional() == "synthetic-key"
assert "synthetic-key" not in calls[0]
assert calls[0][calls[0].index("-Provider") + 1] == "openalex"
```

Test `DpapiElsevierApiKeyProvider` remains compatible and delegates to the generic bridge contract.

- [ ] **Step 2: Run targeted tests and verify RED**

```powershell
uv run pytest tests/unit/test_credentials.py tests/unit/test_elsevier_api.py -q
```

Expected: import failure for `acquire_research_papers.credentials`.

- [ ] **Step 3: Implement minimal bridge**

Create constants and classes:

```python
API_PROVIDER_HOSTS = {
    "semantic_scholar": "api.semanticscholar.org",
    "openalex": "api.openalex.org",
    "elsevier": "api.elsevier.com",
}

class ApiKeyLoadError(RuntimeError):
    pass

class DpapiApiKeyProvider:
    def _read(self, *, allow_missing: bool) -> str | None:
        command = [
            "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(self.script), "-Provider", self.provider,
            "-ExpectedHost", self.expected_host,
            "-SecretPath", str(self.secret_path),
        ]
        if allow_missing:
            command.append("-AllowMissing")
        process = self.process_runner(
            command, check=False, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=self.timeout_seconds,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        lines = [line.strip() for line in process.stdout.splitlines() if line.strip()]
        if process.returncode != 0 or len(lines) > 1:
            raise ApiKeyLoadError("Encrypted API key could not be loaded.")
        return lines[0] if lines else None

    def __call__(self) -> str:
        value = self._read(allow_missing=False)
        if value is None:
            raise ApiKeyLoadError("Encrypted API key could not be loaded.")
        return value

    def optional(self) -> str | None:
        return self._read(allow_missing=True)
```

Use `powershell -NoProfile -ExecutionPolicy Bypass -File`, `capture_output=True`, UTF-8 replacement decoding, a 30-second timeout, and `CREATE_NO_WINDOW`. Never include stdout/stderr in raised messages.

- [ ] **Step 4: Run targeted tests and verify GREEN**

Run the Step 2 command. Expected: all pass.

- [ ] **Step 5: Commit Task 2**

```powershell
git add src/acquire_research_papers/credentials.py src/acquire_research_papers/acquisition/adapters/elsevier_api.py tests/unit/test_credentials.py tests/unit/test_elsevier_api.py
git commit -m "refactor: add host-bound API key bridge"
```

### Task 3: OpenAlex DOI batch enrichment

**Files:**
- Modify: `tests/unit/test_discovery_clients.py`
- Modify: `tests/unit/test_discovery_coordinator.py`
- Modify: `src/acquire_research_papers/discovery/openalex.py`
- Modify: `src/acquire_research_papers/cli.py`

- [ ] **Step 1: Write failing OpenAlex DOI tests**

Assert normalized de-duplication, a `doi:` OR filter, `per_page=100`, abstract reconstruction, endpoint-only provenance, maximum 100 inputs, and a sanitized exception URL:

```python
candidates = client.lookup_dois([
    "https://doi.org/10.1000/ONE",
    "10.1000/one",
    "10.1000/two",
])
assert [candidate.doi for candidate in candidates] == ["10.1000/one", "10.1000/two"]
assert "synthetic-key" not in candidates[0].provenance["query_url"]
```

Add a coordinator regression where Semantic Scholar returns a rate-limit diagnostic and OpenAlex still fills the abstract.

- [ ] **Step 2: Run targeted tests and verify RED**

```powershell
uv run pytest tests/unit/test_discovery_clients.py tests/unit/test_discovery_coordinator.py -q
```

Expected: `OpenAlexClient` has no `lookup_dois` method and no OpenAlex enrichment registration.

- [ ] **Step 3: Implement DOI lookup and production wiring**

Add `lookup_dois(self, dois: list[str]) -> tuple[CandidateMetadata, ...]`. Reject more than 100 unique normalized values, encode full DOI identifiers through `urlencode`, and catch `RateLimited`/`HttpStatusError` to rethrow errors referencing only `self.endpoint`.

Load optional DPAPI keys in `Application.default`, retaining environment variables as explicit compatibility overrides. Register:

```python
DoiBatchEnrichmentProvider(
    "openalex",
    openalex.lookup_dois,
    batch_size=100,
    pause_seconds=0.1,
)
```

after the Semantic Scholar enricher.

- [ ] **Step 4: Run targeted tests and verify GREEN**

Run the Step 2 command plus:

```powershell
uv run pytest tests/unit/test_corpus_discovery_workflow.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit Task 3**

```powershell
git add src/acquire_research_papers/discovery/openalex.py src/acquire_research_papers/cli.py tests/unit/test_discovery_clients.py tests/unit/test_discovery_coordinator.py
git commit -m "feat: enrich missing abstracts through OpenAlex"
```

### Task 4: Credential status and discovery progress

**Files:**
- Modify: `tests/unit/test_corpus_cli.py`
- Modify: `tests/unit/test_discovery_coordinator.py`
- Modify: `src/acquire_research_papers/discovery/coordinator.py`
- Modify: `src/acquire_research_papers/cli.py`

- [ ] **Step 1: Write failing CLI and coordinator tests**

Test `arp credentials status` emits JSON booleans only. Test `arp discover corpus --progress` emits phase/provider/count messages to stderr while stdout remains one parseable final JSON object. Test progress values reject URL/query/key-shaped fields.

- [ ] **Step 2: Run targeted tests and verify RED**

```powershell
uv run pytest tests/unit/test_corpus_cli.py tests/unit/test_discovery_coordinator.py -q
```

Expected: parser rejects `credentials` and `--progress`.

- [ ] **Step 3: Implement status and progress**

Add an optional `progress: Callable[[str, Mapping[str, object]], None]` to `DiscoveryCoordinator`. Emit only closed phase names, provider IDs, and integer counts. In CLI, format progress as compact JSON to stderr:

```python
def progress(event: str, details: Mapping[str, object]) -> None:
    print(json.dumps({"event": event, **details}, sort_keys=True), file=sys.stderr, flush=True)
```

Route `credentials status` before constructing the full application. Keep the final `_emit(...)` stdout behavior unchanged.

Also expose `config status` as the public canonical spelling and keep `credentials status` as an exact compatibility alias. Both commands must return the same capability-only JSON without constructing clients or reading/decrypting key values.

- [ ] **Step 4: Run targeted tests and verify GREEN**

Run the Step 2 command. Expected: all pass and stdout assertions remain unchanged.

- [ ] **Step 5: Commit Task 4**

```powershell
git add src/acquire_research_papers/discovery/coordinator.py src/acquire_research_papers/cli.py tests/unit/test_corpus_cli.py tests/unit/test_discovery_coordinator.py
git commit -m "feat: report safe discovery credential status"
```

### Task 5: Documentation, layout, and complete verification

**Files:**
- Modify: `tests/unit/test_skill_layout.py`
- Modify: `SKILL.md`
- Modify: `references/credentials-and-cache.md`
- Modify: `references/corpus-mode.md`
- Modify: `README.md`
- Modify: `README.zh-CN.md`

- [ ] **Step 1: Write failing layout/documentation assertions**

Require the three new scripts, `arp credentials status`, `setup-discovery-api-keys.ps1`, `--progress`, and OpenAlex DOI enrichment guidance.

- [ ] **Step 2: Run the layout test and verify RED**

```powershell
uv run pytest tests/unit/test_skill_layout.py -q
```

Expected: documentation requirement failure.

- [ ] **Step 3: Update operator documentation**

Document the one-time flow:

```powershell
$skill = Join-Path $env:USERPROFILE ".codex\skills\acquire-research-papers"
& "$skill\scripts\setup-discovery-api-keys.ps1"
uv run --project $skill arp credentials status
uv run --project $skill arp discover corpus --progress `
  --spec "C:\Users\labs2\Desktop\学生2_论文下载_2026.7.18_工作区\student2-corpus-spec-balanced.yaml" `
  --output "C:\Users\labs2\Desktop\学生2_论文下载_2026.7.18_工作区\摘要补全发现清单_2026-07-25-v2"
```

State that keys are DPAPI encrypted, exact-host bound, never printed, and optional. Preserve ScienceDirect manual-only policy.

For the public skill, add:

- a first-use flow led by `arp config status`;
- an optional capability matrix for IEEE institution access, MinerU, Elsevier, OpenAlex, and Semantic Scholar;
- task-scoped guidance so an agent asks only for missing capabilities required by the current task;
- troubleshooting that never asks users to paste secrets into chat or command arguments;
- a safe IEEE institution-adaptation workflow: retain a visible browser, record only sanitized stage/host diagnostics, update the institution profile first, and change the generic browser script plus regression tests only when a genuinely new page shape is encountered.

### Task 7: Public onboarding and generic IEEE institution adaptation

**Files:**
- Modify: `tests/unit/test_skill_layout.py`
- Modify/add targeted IEEE script tests under: `scripts/tests/`
- Modify only as required by failing tests: `scripts/ieee-playwright.mjs`
- Modify: `SKILL.md`
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify relevant references under: `references/`

- [ ] **Step 1: Write failing behavior and documentation tests**

Require the public first-use flow, independent optional capability matrix, task-scoped agent guidance, and the institution-adaptation procedure. Add script-level tests that reject university-name hardcoding and verify diagnostics contain stages and sanitized hosts without URL query strings, SAML state, credentials, or tokens.

- [ ] **Step 2: Run the targeted tests and verify RED**

Run the layout test and IEEE Node tests. The new public guidance/adaptation requirements must fail before implementation.

- [ ] **Step 3: Implement the minimal generic behavior**

Prefer institution-profile changes over browser-script changes. Preserve existing exact authentication-domain restrictions, DPAPI access, single credential submission, persistent context, gateway-loop bounds, visible user continuation, and query sanitization. Do not add institution-specific branches to the generic script.

- [ ] **Step 4: Verify all public-skill gates**

Run Python, PowerShell, Node, skill validation, and `git diff --check`. Confirm all public examples use repository-relative or profile-driven values rather than Guangxi University constants.

- [ ] **Step 5: Commit public onboarding and adaptation guidance**

```powershell
git add SKILL.md README.md README.zh-CN.md references tests scripts
git commit -m "docs: guide optional setup and IEEE adaptation"
```

- [ ] **Step 4: Run all verification gates**

```powershell
uv run pytest -q
powershell -NoProfile -ExecutionPolicy Bypass -File tests/powershell/test-secret-store.ps1
uv run python scripts/validate_skill.py
git diff --check
```

Expected: every command exits 0; no token/key/signature/query-string leakage test fails.

- [ ] **Step 5: Commit and push**

```powershell
git add SKILL.md README.md README.zh-CN.md references/credentials-and-cache.md references/corpus-mode.md tests/unit/test_skill_layout.py
git commit -m "docs: explain unified discovery credentials"
git push origin main
```

### Task 6: Configure keys and regenerate the evidence snapshot

**Files:**
- Runtime secret file outside Git: `%LOCALAPPDATA%\Codex\secrets\acquire-research-papers\secrets.clixml`
- New corpus run outside Git: `C:\Users\labs2\Desktop\学生2_论文下载_2026.7.18_工作区\摘要补全发现清单_2026-07-25-v2`

- [ ] **Step 1: Launch unified interactive setup**

```powershell
& "$env:USERPROFILE\.codex\skills\acquire-research-papers\scripts\setup-discovery-api-keys.ps1"
```

The user enters keys in the visible hidden-input prompts. No key is sent through chat or tool output.

- [ ] **Step 2: Verify status without secret output**

```powershell
uv run --project "$env:USERPROFILE\.codex\skills\acquire-research-papers" arp credentials status
```

Expected: Semantic Scholar and configured optional providers report `true`; output contains no key values.

- [ ] **Step 3: Run a new discovery snapshot with progress**

```powershell
uv run --project "$env:USERPROFILE\.codex\skills\acquire-research-papers" arp discover corpus --progress `
  --spec "C:\Users\labs2\Desktop\学生2_论文下载_2026.7.18_工作区\student2-corpus-spec-balanced.yaml" `
  --output "C:\Users\labs2\Desktop\学生2_论文下载_2026.7.18_工作区\摘要补全发现清单_2026-07-25-v2"
```

- [ ] **Step 4: Compare abstract coverage**

Count `metadata_state == "pending_abstract"` by venue in the old and new `evidence-packets.jsonl`. Verify all newly ready packets have nonempty title and abstract, valid evidence hashes, and sanitized provenance.

- [ ] **Step 5: Prepare the 350-paper review phase**

Copy the balanced spec to a new 350-target spec, retain the verified venue minima, and do not freeze or acquire until semantic decisions against the new evidence hashes satisfy every quota.
