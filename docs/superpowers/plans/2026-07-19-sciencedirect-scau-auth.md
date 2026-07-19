# ScienceDirect SCAU Authentication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add unattended South China Agricultural University WebVPN authentication for subscribed ScienceDirect PDF and official BibTeX acquisition without weakening existing source or credential boundaries.

**Architecture:** Keep the current direct/open or campus-IP HTTP path first. When it returns `access_required`, delegate once to a dedicated persistent Playwright bridge that authenticates only at the exact SCAU VPN host, retrieves artifacts through the exact WebVPN ScienceDirect proxy, and returns canonical publisher metadata to the existing delivery pipeline.

**Tech Stack:** Python 3.11+, PowerShell DPAPI CLIXML, Node.js, pinned `playwright-core` 1.61.1, pytest, Node test runner.

---

## File responsibility map

- `scripts/secret-store.ps1`: validate and atomically update the optional `sciencedirect_scau` DPAPI scope.
- `scripts/setup-sciencedirect-secret.ps1`: non-echoing interactive setup that changes only the SCAU scope.
- `scripts/read-sciencedirect-credential.ps1`: exact-host credential release bridge.
- `scripts/sciencedirect-playwright.mjs`: WebVPN authentication and proxied ScienceDirect artifact retrieval.
- `src/acquire_research_papers/acquisition/adapters/sciencedirect_bridge.py`: Python subprocess boundary and result validation.
- `src/acquire_research_papers/acquisition/adapters/sciencedirect.py`: direct-first adapter with one institutional fallback.
- `src/acquire_research_papers/cli.py`: production bridge wiring.
- `tests/powershell/test-secret-store.ps1`: encrypted-scope preservation and host-gate coverage.
- `tests/node/test-sciencedirect-playwright.mjs`: URL, host, challenge, and authentication-state contracts.
- `tests/unit/test_sciencedirect_bridge.py`: subprocess command and adapter boundary tests.
- `tests/unit/test_sciencedirect_adapter.py`: direct-first and institutional fallback tests.
- `references/*.md`, `SKILL.md`, original design: agent-facing credential and source policy.

### Task 1: Add the encrypted SCAU credential scope

**Files:**
- Modify: `tests/powershell/test-secret-store.ps1`
- Modify: `scripts/secret-store.ps1`
- Create: `scripts/setup-sciencedirect-secret.ps1`
- Create: `scripts/read-sciencedirect-credential.ps1`

- [ ] **Step 1: Write failing PowerShell tests**

Extend the synthetic test payload with a separate SCAU credential and assert:

```powershell
$scauCredential = [Management.Automation.PSCredential]::new("synthetic-scau", $scauPassword)
Set-ScienceDirectCredential -Credential $scauCredential -Path $secretPath
$updated = Import-AcquisitionSecrets -Path $secretPath
Assert-Equal $updated.Scopes.ieee_gxu.Credential.UserName "synthetic-user" "IEEE preserved"
Assert-Equal $updated.Scopes.sciencedirect_scau.Credential.UserName "synthetic-scau" "SCAU username"
```

Assert the credential bridge succeeds only for `vpn.scau.edu.cn` and rejects
`vpn.scau.edu.cn.evil.example`, the proxy article host, and HTTP-origin aliases.

- [ ] **Step 2: Run RED**

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tests/powershell/test-secret-store.ps1
```

Expected: FAIL because `Set-ScienceDirectCredential` and the SCAU credential bridge do not exist.

- [ ] **Step 3: Implement minimal atomic scope update**

Refactor the existing atomic CLIXML write into a helper, validate the optional scope on import, and implement:

```powershell
function Set-ScienceDirectCredential(
  [Management.Automation.PSCredential]$Credential,
  [string]$Path = (Get-AcquisitionSecretPath)
) {
  if ($null -eq $Credential -or [string]::IsNullOrWhiteSpace($Credential.UserName)) {
    throw "ScienceDirect SCAU credential is missing."
  }
  $payload = Import-AcquisitionSecrets -Path $Path
  $scope = [pscustomobject]@{
    Organization = "South China Agricultural University"
    Credential = $Credential
  }
  if ($payload.Scopes.PSObject.Properties.Name -contains "sciencedirect_scau") {
    $payload.Scopes.sciencedirect_scau = $scope
  }
  else {
    $payload.Scopes | Add-Member -NotePropertyName sciencedirect_scau -NotePropertyValue $scope
  }
  Save-AcquisitionSecretPayload -Payload $payload -Path $Path
}
```

The setup script must prompt with `Read-Host -AsSecureString`; the read bridge must reject before importing the secret unless `ExpectedHost` exactly equals `vpn.scau.edu.cn`.

- [ ] **Step 4: Run GREEN and commit**

Run the focused PowerShell test and `uv run pytest tests/unit/test_no_sensitive_artifacts.py -q`.

Commit:

```powershell
git add scripts tests/powershell tests/unit/test_no_sensitive_artifacts.py
git commit -m "feat: store SCAU ScienceDirect credentials securely"
```

### Task 2: Implement the isolated WebVPN browser contract

**Files:**
- Create: `tests/node/test-sciencedirect-playwright.mjs`
- Create: `scripts/sciencedirect-playwright.mjs`

- [ ] **Step 1: Write failing Node contract tests**

Cover these exported contracts before implementation:

```javascript
assert.equal(isApprovedCredentialHost("vpn.scau.edu.cn"), true);
assert.equal(isApprovedCredentialHost("vpn.scau.edu.cn.evil.example"), false);
assert.equal(
  canonicalToProxyUrl("https://www.sciencedirect.com/science/article/pii/S1049007824000411"),
  "https://www-sciencedirect-com-s.vpn.scau.edu.cn/science/article/pii/S1049007824000411",
);
assert.throws(() => assertNoInteractiveChallenge("验证码"), /captcha/i);
```

Use a fake page/context to prove that an existing proxy session never reads credentials, an authentication page reads them once at the exact host, and incomplete authentication cannot retry submission.

- [ ] **Step 2: Run RED**

Run:

```powershell
node --test tests/node/test-sciencedirect-playwright.mjs
```

Expected: FAIL because the module is missing.

- [ ] **Step 3: Implement minimal browser bridge**

Implement exact canonical/proxy URL validation, dedicated path validation, strict unique login fields, CAPTCHA/OTP detection, one credential read/submission, current-page metadata parsing, and same-PII PDF/BibTeX requests. Emit exactly one success JSON object and structured non-sensitive stderr on failure.

- [ ] **Step 4: Run GREEN and commit**

Run both Node suites:

```powershell
node --test tests/node/test-sciencedirect-playwright.mjs tests/node/test-ieee-playwright.mjs
```

Commit:

```powershell
git add scripts/sciencedirect-playwright.mjs tests/node/test-sciencedirect-playwright.mjs
git commit -m "feat: automate SCAU WebVPN ScienceDirect access"
```

### Task 3: Wire institutional fallback into the Python adapter

**Files:**
- Create: `tests/unit/test_sciencedirect_bridge.py`
- Modify: `tests/unit/test_sciencedirect_adapter.py`
- Create: `src/acquire_research_papers/acquisition/adapters/sciencedirect_bridge.py`
- Modify: `src/acquire_research_papers/acquisition/adapters/sciencedirect.py`
- Modify: `src/acquire_research_papers/cli.py`

- [ ] **Step 1: Write failing Python tests**

Define a stub bridge result and prove:

```python
def test_sciencedirect_falls_back_once_when_direct_entitlement_is_missing(
    fixture_server,
) -> None:
    fixture_server.serve_text(
        "/science/article/pii/S1049007824000411",
        (FIXTURES / "sciencedirect" / "denied.html").read_text(encoding="utf-8"),
    )
    bridge = StubScienceDirectBridge(bridge_result())
    adapter = ScienceDirectAdapter(
        client=fixture_server.client,
        bridge=bridge,
        production_hosts={fixture_server.host},
    )
    canonical_url = fixture_server.url("/science/article/pii/S1049007824000411")
    document = adapter.resolve(canonical_url)
    pair = adapter.acquire(document)
    assert bridge.calls == [canonical_url]
    assert pair.bibtex_text.startswith("@article")
```

Also assert open-access fixtures make zero bridge calls, command arguments use only dedicated runtime paths, bridge output outside its run directory is rejected, proxy lookalike hosts are rejected, and an empty BibTeX cannot be delivered.

- [ ] **Step 2: Run RED**

Run:

```powershell
uv run pytest tests/unit/test_sciencedirect_adapter.py tests/unit/test_sciencedirect_bridge.py -q
```

Expected: FAIL because the bridge and fallback do not exist.

- [ ] **Step 3: Implement minimal Python boundary**

Create a bridge patterned after `IeeeBridge`, using the same pinned installer but separate `sciencedirect-scau` profile and run directory. Extend `ScienceDirectAdapter.for_production(bridge=bridge)` to accept the bridge, preserve the direct path, cache the institutional pair, and map authentication phases to `AccessRequired` without swallowing page-contract or path-boundary failures.

- [ ] **Step 4: Run GREEN and commit**

Run the focused tests plus fetch integration tests.

```powershell
uv run pytest tests/unit/test_sciencedirect_adapter.py tests/unit/test_sciencedirect_bridge.py tests/integration/test_fetch_cli.py -q
```

Commit:

```powershell
git add src/acquire_research_papers/acquisition/adapters/sciencedirect.py src/acquire_research_papers/acquisition/adapters/sciencedirect_bridge.py src/acquire_research_papers/cli.py tests/unit/test_sciencedirect_adapter.py tests/unit/test_sciencedirect_bridge.py
git commit -m "feat: add ScienceDirect institutional fallback"
```

### Task 4: Update skill contracts and perform live validation

**Files:**
- Modify: `SKILL.md`
- Modify: `references/source-policies.md`
- Modify: `references/credentials-and-cache.md`
- Modify: `docs/superpowers/specs/2026-07-19-acquire-research-papers-design.md`
- Modify: `scripts/validate_skill.py`
- Modify: `tests/unit/test_skill_layout.py`
- Modify: `tests/unit/test_no_sensitive_artifacts.py`
- Modify: `pyproject.toml`
- Modify: `src/acquire_research_papers/__init__.py`

- [ ] **Step 1: Write failing documentation/layout tests**

Require the new setup/read/browser scripts and require the policy text to name `sciencedirect_scau`, `vpn.scau.edu.cn`, the exact proxy host, one credential submission, and structured stops for CAPTCHA/OTP.

- [ ] **Step 2: Run RED**

Run:

```powershell
uv run pytest tests/unit/test_skill_layout.py tests/unit/test_no_sensitive_artifacts.py -q
```

Expected: FAIL because public contracts still describe campus/IP-only v1 behavior.

- [ ] **Step 3: Update documentation and version**

Replace the old “do not store a campus account” rule with the approved DPAPI scope and exact-host WebVPN contract. Bump the package to `0.2.0`; do not include credentials, tokens, cookies, signed query values, live HTML, or browser storage in tracked files.

- [ ] **Step 4: Store the real credential interactively**

Run `scripts/setup-sciencedirect-secret.ps1` in a PTY and enter the supplied values only at non-echoing prompts. Verify only scope names and organization metadata; never print decrypted values.

- [ ] **Step 5: Run deterministic release gates**

Run:

```powershell
uv run pytest -q
node --test tests/node/test-ieee-playwright.mjs tests/node/test-sciencedirect-playwright.mjs
powershell -NoProfile -ExecutionPolicy Bypass -File tests/powershell/test-secret-store.ps1
uv run ruff check .
uv run python scripts/validate_skill.py
git diff --check
```

- [ ] **Step 6: Run a bounded live subscribed-paper test**

Fetch `https://www.sciencedirect.com/science/article/pii/S1049007824000411` into a new directory under the user's Downloads folder. Verify `%PDF-`, raw BibTeX DOI match, canonical provenance, no Markdown, one login at most, and a duplicate registry fetch that does not reopen authentication. If CAPTCHA, OTP, or entitlement exclusion occurs, report that exact structured boundary and do not bypass it.

- [ ] **Step 7: Commit and finish the branch**

```powershell
git add SKILL.md references docs scripts/validate_skill.py tests/unit pyproject.toml src/acquire_research_papers/__init__.py uv.lock
git commit -m "release: add SCAU ScienceDirect authentication"
```

Use `superpowers:verification-before-completion`, then `superpowers:finishing-a-development-branch`. With the user's existing authorization, fast-forward `main`, push the branch result, and wait for remote CI before declaring completion.
