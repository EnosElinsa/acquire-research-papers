# Acquire Research Papers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and publicly release a global Codex skill that can fetch specified papers, collect quota-driven corpora, and support evidence-driven literature research while delivering verified official PDF/BibTeX pairs and optional Markdown.

**Architecture:** A Python 3.11+ package provides deterministic models, SQLite state, discovery clients, source adapters, artifact validation, delivery, and CLI commands. Codex performs semantic interpretation and evidence judgment through schemas and skill instructions; Playwright/PowerShell bridges handle Windows institutional access, and MinerU is isolated behind a cache service.

**Tech Stack:** Python 3.11+, uv, argparse, dataclasses, SQLite, httpx, Beautiful Soup, jsonschema, PyYAML, Pybtex, platformdirs, pytest, local HTTP integration tests, Node.js Playwright bridge, PowerShell DPAPI bridge, GitHub Actions.

---

## Milestones and scope

- Milestone A (Tasks 1-8): runnable open-paper `fetch` vertical slice with official PDF/BibTeX validation, registry, delivery, and CLI.
- Milestone B (Tasks 9-10): audited IEEE/CARSI acquisition and optional MinerU cache.
- Milestone C (Tasks 11-12): generic corpus discovery and research evidence workflows.
- Milestone D (Tasks 13-15): ACM/ScienceDirect adapters, complete skill documentation, live validation, and public release.

Each task ends with a focused commit. Do not start the next milestone while the previous milestone's full test suite is red.

## File responsibility map

- `SKILL.md`: concise agent routing and safe operating procedure.
- `agents/openai.yaml`: Codex UI metadata generated from the final skill.
- `pyproject.toml`, `uv.lock`: package metadata and reproducible dependencies.
- `schemas/*.json`: public interchange contracts for corpus, research, and paper records.
- `src/acquire_research_papers/models.py`: enums/dataclasses shared by all components.
- `src/acquire_research_papers/specs.py`: YAML/JSON loading and JSON Schema validation.
- `src/acquire_research_papers/paths.py`: global paths and containment checks.
- `src/acquire_research_papers/registry.py`: SQLite schema, transactions, state, dedupe, and numbering.
- `src/acquire_research_papers/artifacts.py`: PDF hashing/validation and atomic file handling.
- `src/acquire_research_papers/bibliography.py`: BibTeX parsing and official metadata comparison.
- `src/acquire_research_papers/http.py`: bounded requests, redirects, retries, and domain throttling.
- `src/acquire_research_papers/acquisition/base.py`: source adapter protocol and normalized results.
- `src/acquire_research_papers/acquisition/router.py`: official landing/source adapter selection.
- `src/acquire_research_papers/acquisition/adapters/*.py`: provider-specific page contracts.
- `src/acquire_research_papers/discovery/*.py`: Crossref/OpenAlex/Semantic Scholar candidate discovery and corpus quota bookkeeping.
- `src/acquire_research_papers/research/*.py`: research brief expansion, evidence records, and research deliverables.
- `src/acquire_research_papers/mineru.py`: seven-day content-addressed analysis cache.
- `src/acquire_research_papers/delivery.py`: generic and numbered output profiles.
- `src/acquire_research_papers/cli.py`: `arp` subcommands and JSON stdout contract.
- `scripts/*.ps1`, `scripts/*.mjs`: audited Windows credentials and IEEE browser bridge.
- `references/*.md`: progressive-disclosure operating rules.
- `tests/unit`, `tests/integration`, `tests/fixtures`: deterministic coverage.

### Task 1: Scaffold the public skill and Python package

**Files:**
- Create: `SKILL.md`
- Create: `agents/openai.yaml`
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.gitattributes`
- Create: `LICENSE`
- Create: `src/acquire_research_papers/__init__.py`
- Create: `src/acquire_research_papers/cli.py`
- Create: `tests/unit/test_skill_layout.py`

- [ ] **Step 1: Run the required skill initializer in an isolated temporary parent**

Run:

```powershell
$scratch = Join-Path $env:TEMP "arp-skill-init"
python C:\Users\labs2\.codex\skills\.system\skill-creator\scripts\init_skill.py `
  acquire-research-papers --path $scratch --resources scripts,references `
  --interface 'display_name=Research Paper Acquisition' `
  --interface 'short_description=Discover and acquire verified research papers' `
  --interface 'default_prompt=Use $acquire-research-papers to discover or fetch official papers and BibTeX.'
```

Expected: a valid generated template under the temporary parent. Use it as the structural baseline; do not copy placeholder text into the repository.

After inspecting the generated structure, remove only the verified temporary `arp-skill-init` directory; never remove the actual repository.

- [ ] **Step 2: Create package metadata and dependency groups**

Write `pyproject.toml` with:

```toml
[build-system]
requires = ["hatchling>=1.27,<2"]
build-backend = "hatchling.build"

[project]
name = "acquire-research-papers"
version = "0.1.0"
description = "Codex skill and CLI for verified academic paper acquisition"
requires-python = ">=3.11"
license = { text = "MIT" }
dependencies = [
  "beautifulsoup4>=4.13,<5",
  "httpx>=0.28,<1",
  "jsonschema>=4.23,<5",
  "platformdirs>=4.3,<5",
  "pybtex>=0.25,<1",
  "PyYAML>=6.0,<7",
]

[project.scripts]
arp = "acquire_research_papers.cli:main"

[dependency-groups]
dev = [
  "pytest>=8.3,<9",
  "pytest-httpserver>=1.1,<2",
  "ruff>=0.11,<1",
]

[tool.hatch.build.targets.wheel]
packages = ["src/acquire_research_papers"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra"

[tool.ruff]
line-length = 100
target-version = "py311"
```

- [ ] **Step 3: Write a failing layout test**

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_required_skill_and_package_files_exist() -> None:
    required = [
        "SKILL.md",
        "agents/openai.yaml",
        "pyproject.toml",
        "src/acquire_research_papers/__init__.py",
        "src/acquire_research_papers/cli.py",
    ]
    assert all((ROOT / relative).is_file() for relative in required)


def test_runtime_data_is_ignored() -> None:
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in (".env", "*.clixml", "registry.sqlite*", "runs/", "downloads/"):
        assert pattern in ignored
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `uv sync --all-groups; uv run pytest tests/unit/test_skill_layout.py -q`

Expected: FAIL because the skill/package files do not yet exist.

- [ ] **Step 5: Add the minimal valid skill and CLI**

Use this public CLI contract in `src/acquire_research_papers/cli.py`:

```python
from __future__ import annotations

import argparse
import json
from collections.abc import Sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="arp")
    parser.add_argument("--version", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.version:
        print(json.dumps({"name": "acquire-research-papers", "version": "0.1.0"}))
        return 0
    build_parser().print_help()
    return 0
```

Create a concise valid `SKILL.md` with only `name` and `description` frontmatter and routing to `fetch`, `discover corpus`, and `discover research`. Create `agents/openai.yaml` using the generated interface values. Add an MIT license, LF normalization in `.gitattributes`, and repository/runtime exclusions in `.gitignore`.

- [ ] **Step 6: Lock dependencies and run baseline checks**

Run:

```powershell
uv lock
uv run pytest tests/unit/test_skill_layout.py -q
uv run ruff check src tests
python C:\Users\labs2\.codex\skills\.system\skill-creator\scripts\quick_validate.py .
```

Expected: layout tests PASS, Ruff PASS, and skill validator prints `Skill is valid!`.

- [ ] **Step 7: Commit**

```powershell
git add SKILL.md agents pyproject.toml uv.lock .gitignore .gitattributes LICENSE src tests
git commit -m "chore: scaffold research paper acquisition skill"
```

### Task 2: Define schemas and typed domain models

**Files:**
- Create: `schemas/corpus-spec.schema.json`
- Create: `schemas/research-brief.schema.json`
- Create: `schemas/paper-record.schema.json`
- Create: `src/acquire_research_papers/models.py`
- Create: `src/acquire_research_papers/specs.py`
- Create: `tests/unit/test_models.py`
- Create: `tests/unit/test_specs.py`

- [ ] **Step 1: Write failing model and schema tests**

```python
from acquire_research_papers.models import ErrorCode, PaperMetadata, PaperStatus, normalize_doi


def test_normalize_doi_removes_url_and_prefix() -> None:
    assert normalize_doi("https://doi.org/10.1109/TEST.1") == "10.1109/test.1"
    assert normalize_doi("doi:10.1016/J.TEST.2026.1") == "10.1016/j.test.2026.1"


def test_metadata_requires_title_and_official_landing_url() -> None:
    metadata = PaperMetadata(
        title="Verified Paper",
        authors=("Ada Lovelace",),
        year=2026,
        venue="Test Venue",
        doi="10.1109/test.1",
        publisher="Test Publisher",
        landing_url="https://publisher.example/paper",
    )
    assert metadata.doi == "10.1109/test.1"
    assert PaperStatus.PAIR_VERIFIED.value == "pair_verified"
    assert ErrorCode.BIB_MISSING.value == "bib_missing"
```

```python
from pathlib import Path

import pytest

from acquire_research_papers.specs import SpecValidationError, load_corpus_spec


def test_corpus_spec_defaults_preferred_to_range_midpoint(tmp_path: Path) -> None:
    path = tmp_path / "job.yaml"
    path.write_text(
        "mode: corpus\nname: test\ntarget:\n  minimum: 60\n  maximum: 100\n",
        encoding="utf-8",
    )
    spec = load_corpus_spec(path)
    assert spec["target"]["preferred"] == 80


def test_corpus_spec_rejects_maximum_below_minimum(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(
        "mode: corpus\nname: bad\ntarget:\n  minimum: 100\n  maximum: 60\n",
        encoding="utf-8",
    )
    with pytest.raises(SpecValidationError):
        load_corpus_spec(path)
```

- [ ] **Step 2: Run tests to verify RED**

Run: `uv run pytest tests/unit/test_models.py tests/unit/test_specs.py -q`

Expected: import failures for missing modules.

- [ ] **Step 3: Implement enums, dataclasses, normalization, and schema loading**

Define exact enum values from the design and immutable metadata:

```python
class PaperStatus(str, Enum):
    DISCOVERED = "discovered"
    AUTO_ACCEPTED = "auto_accepted"
    PENDING_REVIEW = "pending_review"
    REJECTED = "rejected"
    RESOLVING = "resolving"
    DOWNLOADED = "downloaded"
    PAIR_VERIFIED = "pair_verified"
    TEMPORARILY_PARSED = "temporarily_parsed"
    NUMBERED = "numbered"
    DELIVERED = "delivered"


class ErrorCode(str, Enum):
    NOT_FOUND = "not_found"
    NOT_OFFICIAL = "not_official"
    ACCESS_REQUIRED = "access_required"
    AUTH_INTERACTIVE = "auth_interactive"
    RATE_LIMITED = "rate_limited"
    PDF_INVALID = "pdf_invalid"
    BIB_MISSING = "bib_missing"
    METADATA_MISMATCH = "metadata_mismatch"
    DUPLICATE = "duplicate"
    SCREENING_AMBIGUOUS = "screening_ambiguous"
    PAGE_CONTRACT_CHANGED = "page_contract_changed"
    NETWORK_TRANSIENT = "network_transient"
```

`PaperMetadata` must include `title`, `authors`, `year`, `venue`, `doi`, `publisher`, `landing_url`, and optional `publication_type`. Use `jsonschema.Draft202012Validator` for schema validation. Apply the midpoint default after validation of required fields and reject inconsistent target ranges in Python with a path-specific `SpecValidationError`.

- [ ] **Step 4: Run tests and schema examples**

Run: `uv run pytest tests/unit/test_models.py tests/unit/test_specs.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add schemas src/acquire_research_papers/models.py src/acquire_research_papers/specs.py tests/unit/test_models.py tests/unit/test_specs.py
git commit -m "feat: define paper acquisition schemas and models"
```

### Task 3: Add safe global paths and configuration

**Files:**
- Create: `src/acquire_research_papers/paths.py`
- Create: `src/acquire_research_papers/config.py`
- Create: `tests/unit/test_paths.py`

- [ ] **Step 1: Write failing path tests**

```python
from pathlib import Path

import pytest

from acquire_research_papers.paths import AppPaths, ensure_outside_repository


def test_app_paths_are_outside_skill_repository(tmp_path: Path) -> None:
    paths = AppPaths.for_root(tmp_path / "local")
    assert paths.registry == tmp_path / "local" / "paper-acquisition" / "registry.sqlite"
    assert paths.cache.name == "acquire-research-papers"
    assert paths.secrets.name == "acquire-research-papers"


def test_delivery_cannot_target_skill_repository(tmp_path: Path) -> None:
    repository = tmp_path / "skill"
    repository.mkdir()
    with pytest.raises(ValueError, match="outside the skill repository"):
        ensure_outside_repository(repository / "downloads", repository)
```

- [ ] **Step 2: Run RED**

Run: `uv run pytest tests/unit/test_paths.py -q`

Expected: missing module failure.

- [ ] **Step 3: Implement `AppPaths` and containment**

```python
@dataclass(frozen=True)
class AppPaths:
    registry: Path
    cache: Path
    secrets: Path
    profiles: Path
    dependencies: Path
    runs: Path

    @classmethod
    def default(cls) -> "AppPaths":
        local = Path(user_data_dir("Codex", appauthor=False))
        return cls.for_root(local)

    @classmethod
    def for_root(cls, local: Path) -> "AppPaths":
        return cls(
            registry=local / "paper-acquisition" / "registry.sqlite",
            cache=local / "cache" / "acquire-research-papers",
            secrets=local / "secrets" / "acquire-research-papers",
            profiles=local / "browser-profiles" / "acquire-research-papers",
            dependencies=local / "deps" / "acquire-research-papers",
            runs=local / "paper-acquisition" / "runs",
        )
```

Resolve paths before containment comparison and reject the repository itself or descendants as delivery/runtime locations.

- [ ] **Step 4: Run GREEN and commit**

Run: `uv run pytest tests/unit/test_paths.py -q`

Expected: PASS.

```powershell
git add src/acquire_research_papers/paths.py src/acquire_research_papers/config.py tests/unit/test_paths.py
git commit -m "feat: isolate acquisition runtime paths"
```

### Task 4: Build the SQLite registry and state machine

**Files:**
- Create: `src/acquire_research_papers/registry.py`
- Create: `tests/unit/test_registry.py`

- [ ] **Step 1: Write failing registry tests**

```python
from pathlib import Path

import pytest

from acquire_research_papers.models import PaperStatus
from acquire_research_papers.registry import Registry, StateTransitionError


def test_registry_deduplicates_normalized_doi(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "registry.sqlite")
    first = registry.upsert_paper(title="Paper", doi="https://doi.org/10.1109/TEST.1")
    second = registry.upsert_paper(title="Paper", doi="10.1109/test.1")
    assert first == second


def test_illegal_transition_is_rejected(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "registry.sqlite")
    paper_id = registry.upsert_paper(title="Paper", doi="10.1109/test.2")
    with pytest.raises(StateTransitionError):
        registry.transition(paper_id, PaperStatus.DELIVERED)


def test_number_allocation_is_stable_and_gap_free(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "registry.sqlite")
    one = registry.create_verified_paper("One", "10.1109/one")
    two = registry.create_verified_paper("Two", "10.1109/two")
    assert registry.allocate_number("task", "IEEE TEVC", one) == 1
    assert registry.allocate_number("task", "IEEE TEVC", one) == 1
    assert registry.allocate_number("task", "IEEE TEVC", two) == 2
```

- [ ] **Step 2: Run RED**

Run: `uv run pytest tests/unit/test_registry.py -q`

Expected: missing registry failure.

- [ ] **Step 3: Implement schema, WAL, transactions, and legal transitions**

Create tables `papers`, `artifacts`, `tasks`, `task_candidates`, `provenance`, `evidence`, `number_allocations`, and `events`. Use `BEGIN IMMEDIATE` for number allocation and this transition map:

```python
ALLOWED_TRANSITIONS = {
    PaperStatus.DISCOVERED: {
        PaperStatus.AUTO_ACCEPTED,
        PaperStatus.PENDING_REVIEW,
        PaperStatus.REJECTED,
    },
    PaperStatus.AUTO_ACCEPTED: {PaperStatus.RESOLVING},
    PaperStatus.RESOLVING: {PaperStatus.DOWNLOADED},
    PaperStatus.DOWNLOADED: {PaperStatus.PAIR_VERIFIED},
    PaperStatus.PAIR_VERIFIED: {
        PaperStatus.TEMPORARILY_PARSED,
        PaperStatus.NUMBERED,
        PaperStatus.DELIVERED,
    },
    PaperStatus.TEMPORARILY_PARSED: {
        PaperStatus.NUMBERED,
        PaperStatus.DELIVERED,
    },
    PaperStatus.NUMBERED: {PaperStatus.DELIVERED},
}
```

Record errors as events without replacing the last successful state.

- [ ] **Step 4: Run GREEN and inspect SQLite durability**

Run: `uv run pytest tests/unit/test_registry.py -q`

Expected: PASS, including reopen-on-disk assertions.

- [ ] **Step 5: Commit**

```powershell
git add src/acquire_research_papers/registry.py tests/unit/test_registry.py
git commit -m "feat: add durable paper acquisition registry"
```

### Task 5: Validate PDF and official BibTeX pairs

**Files:**
- Create: `src/acquire_research_papers/artifacts.py`
- Create: `src/acquire_research_papers/bibliography.py`
- Create: `tests/unit/test_artifacts.py`
- Create: `tests/unit/test_bibliography.py`
- Create: `tests/fixtures/citations/verified.bib.txt`

- [ ] **Step 1: Write failing artifact tests**

```python
from pathlib import Path

import pytest

from acquire_research_papers.artifacts import InvalidPdfError, sha256_file, validate_pdf


def test_pdf_header_and_hash(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.7\nsynthetic\n%%EOF\n")
    validate_pdf(pdf)
    assert len(sha256_file(pdf)) == 64


def test_html_response_is_not_pdf(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_text("<html>login</html>", encoding="utf-8")
    with pytest.raises(InvalidPdfError):
        validate_pdf(pdf)
```

```python
import pytest

from acquire_research_papers.bibliography import MetadataMismatch, parse_bibtex, verify_bibliography
from acquire_research_papers.models import PaperMetadata


def verified_metadata() -> PaperMetadata:
    return PaperMetadata(
        title="Verified Paper",
        authors=("Ada Lovelace", "Alan Turing"),
        year=2026,
        venue="IEEE Test",
        doi="10.1109/test.1",
        publisher="IEEE",
        landing_url="https://ieeexplore.ieee.org/document/1",
    )


def test_official_bibtex_matches_metadata() -> None:
    parsed = parse_bibtex(
        "@article{k, title={Verified Paper}, author={Lovelace, Ada and Turing, Alan}, "
        "year={2026}, journal={IEEE Test}, doi={10.1109/TEST.1}}"
    )
    verify_bibliography(verified_metadata(), parsed)


def test_doi_mismatch_is_blocking() -> None:
    wrong_entry = parse_bibtex(
        "@article{k, title={Verified Paper}, author={Lovelace, Ada and Turing, Alan}, "
        "year={2026}, journal={IEEE Test}, doi={10.1109/wrong}}"
    )
    with pytest.raises(MetadataMismatch, match="DOI"):
        verify_bibliography(verified_metadata(), wrong_entry)
```

- [ ] **Step 2: Run RED**

Run: `uv run pytest tests/unit/test_artifacts.py tests/unit/test_bibliography.py -q`

Expected: missing modules.

- [ ] **Step 3: Implement strict validation**

Use `pybtex.database.parse_string(..., "bibtex")`. Require one entry, normalize DOI/title/author names, require exact DOI when both sides provide one, exact year, venue alias equivalence, and normalized title similarity at least `0.95`. Return field-specific mismatch details; never synthesize a BibTeX entry.

Implement `atomic_write_bytes(destination, data)` with an exclusive `.partial` sibling, `fsync`, PDF validation before rename, and cleanup on failure.

- [ ] **Step 4: Run GREEN and commit**

Run: `uv run pytest tests/unit/test_artifacts.py tests/unit/test_bibliography.py -q`

Expected: PASS.

```powershell
git add src/acquire_research_papers/artifacts.py src/acquire_research_papers/bibliography.py tests/unit/test_artifacts.py tests/unit/test_bibliography.py tests/fixtures/citations
git commit -m "feat: verify official PDF and BibTeX pairs"
```

### Task 6: Add bounded HTTP and the source adapter protocol

**Files:**
- Create: `src/acquire_research_papers/http.py`
- Create: `src/acquire_research_papers/acquisition/__init__.py`
- Create: `src/acquire_research_papers/acquisition/base.py`
- Create: `src/acquire_research_papers/acquisition/router.py`
- Create: `src/acquire_research_papers/acquisition/adapters/__init__.py`
- Create: `src/acquire_research_papers/acquisition/adapters/direct.py`
- Create: `tests/conftest.py`
- Create: `tests/unit/test_http.py`
- Create: `tests/unit/test_adapter_router.py`
- Create: `tests/integration/test_direct_adapter.py`

- [ ] **Step 1: Write failing redirect and adapter tests**

```python
import pytest

from acquire_research_papers.http import HostBoundaryError, SafeHttpClient


def test_redirect_outside_allowed_hosts_is_rejected(httpserver) -> None:
    httpserver.expect_request("/paper").respond_with_data(
        "", status=302, headers={"Location": "https://attacker.example/capture"}
    )
    client = SafeHttpClient(allowed_hosts={httpserver.host})
    with pytest.raises(HostBoundaryError):
        client.get(httpserver.url_for("/paper"))
```

```python
from acquire_research_papers.acquisition.router import AdapterRouter


def test_router_uses_exact_hostname() -> None:
    router = AdapterRouter.with_defaults()
    assert router.name_for("https://aclanthology.org/2025.acl-long.1/") == "acl-anthology"
    assert router.name_for("https://aclanthology.org.evil.example/paper") is None
```

- [ ] **Step 2: Run RED**

Run: `uv run pytest tests/unit/test_http.py tests/unit/test_adapter_router.py tests/integration/test_direct_adapter.py -q`

Expected: missing modules.

- [ ] **Step 3: Implement the normalized adapter interface**

```python
@dataclass(frozen=True)
class SourceDocument:
    metadata: PaperMetadata
    pdf_url: str
    bibtex_url: str
    allowed_hosts: frozenset[str]


@dataclass(frozen=True)
class AcquiredPair:
    document: SourceDocument
    pdf_bytes: bytes
    bibtex_text: str


class SourceAdapter(Protocol):
    name: str

    def supports(self, landing_url: str) -> bool: ...
    def resolve(self, landing_url: str) -> SourceDocument: ...
    def acquire(self, document: SourceDocument) -> AcquiredPair: ...
```

`SafeHttpClient` must keep `follow_redirects=False`, perform at most five manual redirects, check every target hostname before sending the next request, use bounded timeouts, and retry only connection/timeouts and `5xx` twice. Do not retry `401`, `403`, `404`, or `429`.

Add reusable deterministic fixtures in `tests/conftest.py`:

```python
from pathlib import Path


FIXTURES = Path(__file__).resolve().parent / "fixtures"


@dataclass
class FixtureServer:
    server: HTTPServer

    @property
    def host(self) -> str:
        return self.server.host

    @property
    def client(self) -> SafeHttpClient:
        return SafeHttpClient(allowed_hosts={self.host})

    def url(self, path: str) -> str:
        return self.server.url_for(path)

    def serve_text(self, path: str, text: str, content_type: str = "text/html") -> None:
        self.server.expect_request(path).respond_with_data(
            text, content_type=content_type
        )

    def serve_bytes(self, path: str, data: bytes, content_type: str) -> None:
        self.server.expect_request(path).respond_with_data(
            data, content_type=content_type
        )


@pytest.fixture
def fixture_server(httpserver: HTTPServer) -> FixtureServer:
    return FixtureServer(httpserver)


@pytest.fixture
def verified_pair() -> AcquiredPair:
    metadata = PaperMetadata(
        title="Verified Paper",
        authors=("Ada Lovelace",),
        year=2026,
        venue="Test Venue",
        doi="10.1109/test.1",
        publisher="Test Publisher",
        landing_url="https://publisher.example/paper",
    )
    document = SourceDocument(
        metadata=metadata,
        pdf_url="https://publisher.example/paper.pdf",
        bibtex_url="https://publisher.example/paper.bib",
        allowed_hosts=frozenset({"publisher.example"}),
    )
    return AcquiredPair(
        document=document,
        pdf_bytes=b"%PDF-1.7\nsynthetic\n%%EOF\n",
        bibtex_text=(
            "@article{k,title={Verified Paper},author={Lovelace, Ada},year={2026},"
            "journal={Test Venue},doi={10.1109/test.1}}"
        ),
    )
```

- [ ] **Step 4: Run GREEN and commit**

Run: `uv run pytest tests/unit/test_http.py tests/unit/test_adapter_router.py tests/integration/test_direct_adapter.py -q`

Expected: PASS with a local HTTP server; no internet required.

```powershell
git add src/acquire_research_papers/http.py src/acquire_research_papers/acquisition tests/unit/test_http.py tests/unit/test_adapter_router.py tests/integration/test_direct_adapter.py
git commit -m "feat: add bounded official source adapters"
```

### Task 7: Implement ACL Anthology and IJCAI official adapters

**Files:**
- Create: `src/acquire_research_papers/acquisition/adapters/acl.py`
- Create: `src/acquire_research_papers/acquisition/adapters/ijcai.py`
- Create: `tests/fixtures/acl/paper.html`
- Create: `tests/fixtures/ijcai/paper.html`
- Create: `tests/unit/test_acl_adapter.py`
- Create: `tests/unit/test_ijcai_adapter.py`

- [ ] **Step 1: Save minimal official-page fixtures and write failing tests**

```python
def test_acl_resolves_official_pdf_and_bib(fixture_server) -> None:
    fixtures = Path(__file__).resolve().parents[1] / "fixtures"
    fixture_server.serve_text(
        "/acl/2025.acl-long.1/",
        (fixtures / "acl" / "paper.html").read_text(encoding="utf-8"),
    )
    adapter = AclAnthologyAdapter(client=fixture_server.client)
    document = adapter.resolve(fixture_server.url("/acl/2025.acl-long.1/"))
    assert document.metadata.title == "A Verified ACL Paper"
    assert document.pdf_url.endswith("2025.acl-long.1.pdf")
    assert document.bibtex_url.endswith("2025.acl-long.1.bib")
    assert document.allowed_hosts == frozenset({fixture_server.host})
```

```python
def test_ijcai_rejects_demo_track_when_main_track_required(fixture_server) -> None:
    fixtures = Path(__file__).resolve().parents[1] / "fixtures"
    fixture_server.serve_text(
        "/ijcai/2025/1246",
        (fixtures / "ijcai" / "paper.html").read_text(encoding="utf-8"),
    )
    adapter = IjcaiProceedingsAdapter(client=fixture_server.client)
    document = adapter.resolve(fixture_server.url("/ijcai/2025/1246"))
    assert document.metadata.publication_type == "demo"
    assert not adapter.matches_track(document, allowed={"main", "regular"})
```

- [ ] **Step 2: Run RED**

Run: `uv run pytest tests/unit/test_acl_adapter.py tests/unit/test_ijcai_adapter.py -q`

Expected: missing adapters.

- [ ] **Step 3: Implement page contracts**

Use Beautiful Soup and require unique official links. ACL accepts exact `.pdf` and `.bib` anchors derived from the anthology ID. IJCAI requires unique visible `PDF` and `BibTeX` links, parses the track label, and normalizes DOI `10.24963/ijcai.<year>/<number>`. Ambiguous or missing links raise `PageContractChanged` rather than falling back to a generic guess.

- [ ] **Step 4: Run GREEN and commit**

Run: `uv run pytest tests/unit/test_acl_adapter.py tests/unit/test_ijcai_adapter.py -q`

Expected: PASS.

```powershell
git add src/acquire_research_papers/acquisition/adapters/acl.py src/acquire_research_papers/acquisition/adapters/ijcai.py tests/fixtures/acl tests/fixtures/ijcai tests/unit/test_acl_adapter.py tests/unit/test_ijcai_adapter.py
git commit -m "feat: acquire ACL and IJCAI official papers"
```

### Task 8: Deliver the first end-to-end `fetch` slice

**Files:**
- Create: `src/acquire_research_papers/resolver.py`
- Create: `src/acquire_research_papers/delivery.py`
- Modify: `src/acquire_research_papers/cli.py`
- Create: `tests/unit/test_delivery.py`
- Create: `tests/integration/test_fetch_cli.py`

- [ ] **Step 1: Write failing delivery and CLI tests**

```python
def test_generic_delivery_is_atomic_and_reusable(tmp_path: Path, verified_pair) -> None:
    delivery = GenericDelivery(tmp_path / "out")
    result = delivery.deliver(pair=verified_pair, paper_id="paper-1")
    assert result.pdf.name == "paper.pdf"
    assert result.bibtex.name == "citation.bib"
    assert result.provenance.name == "provenance.json"
    assert delivery.deliver(pair=verified_pair, paper_id="paper-1") == result
```

```python
def test_fetch_cli_emits_one_json_object(fixture_server, tmp_path, capsys) -> None:
    fixtures = Path(__file__).resolve().parents[1] / "fixtures"
    fixture_server.serve_text(
        "/acl/2025.acl-long.1/",
        (fixtures / "acl" / "paper.html").read_text(encoding="utf-8"),
    )
    fixture_server.serve_bytes(
        "/acl/2025.acl-long.1.pdf", b"%PDF-1.7\nsynthetic\n%%EOF\n", "application/pdf"
    )
    fixture_server.serve_text(
        "/acl/2025.acl-long.1.bib",
        "@inproceedings{k,title={A Verified ACL Paper},author={Lovelace, Ada},"
        "year={2025},booktitle={ACL},doi={10.18653/v1/2025.acl-long.1}}",
        "application/x-bibtex",
    )
    application = Application.for_test(
        app_root=tmp_path / "app",
        adapter=AclAnthologyAdapter(
            client=fixture_server.client,
            production_hosts={fixture_server.host},
        ),
    )
    exit_code = run_cli([
        "fetch",
        "--input",
        fixture_server.url("/acl/2025.acl-long.1/"),
        "--output",
        str(tmp_path / "out"),
    ], application=application)
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "delivered"
    assert Path(payload["pdf"]).is_file()
    assert Path(payload["bibtex"]).is_file()
```

- [ ] **Step 2: Run RED**

Run: `uv run pytest tests/unit/test_delivery.py tests/integration/test_fetch_cli.py -q`

Expected: missing resolver/delivery/subcommand.

- [ ] **Step 3: Implement resolver, generic delivery, and CLI**

Add `run_cli(argv, application)` for dependency-injected tests and `main(argv)` for the production console entry point. Add `fetch`, `status`, `resume`, and `review` parsers. Resolve DOI through `https://doi.org/<doi>` using manual redirect host validation, resolve official URLs through the adapter router, and reject ambiguous title-only input unless discovery returns one canonical record.

CLI stdout is exactly one JSON object. Diagnostics go to stderr and contain no headers, cookies, or secret values. Exit codes: `0` success/existing, `64` invalid input, `69` access unavailable, `75` rate limited, `78` page/metadata contract error.

- [ ] **Step 4: Run the Milestone A suite**

Run:

```powershell
uv run pytest -q
uv run ruff check src tests
uv run arp --version
```

Expected: full suite PASS; version command emits valid JSON.

- [ ] **Step 5: Commit**

```powershell
git add src/acquire_research_papers/resolver.py src/acquire_research_papers/delivery.py src/acquire_research_papers/cli.py tests/unit/test_delivery.py tests/integration/test_fetch_cli.py
git commit -m "feat: deliver verified papers through fetch CLI"
```

### Task 9: Port and generalize the IEEE/CARSI adapter

**Files:**
- Create: `src/acquire_research_papers/acquisition/adapters/ieee.py`
- Create: `scripts/ieee-playwright.mjs`
- Create: `scripts/secret-store.ps1`
- Create: `scripts/setup-secrets.ps1`
- Create: `scripts/read-browser-credential.ps1`
- Create: `scripts/migrate-legacy-secrets.ps1`
- Create: `tests/unit/test_ieee_bridge.py`
- Create: `tests/node/test-ieee-playwright.mjs`
- Create: `tests/powershell/test-secret-store.ps1`

- [ ] **Step 1: Write failing Python bridge tests**

```python
def test_ieee_bridge_uses_dedicated_runtime_paths(tmp_path: Path) -> None:
    bridge = IeeeBridge(
        script=tmp_path / "ieee-playwright.mjs",
        profile_root=tmp_path / "profiles" / "ieee",
        dependency_root=tmp_path / "deps",
        work_root=tmp_path / "runs",
    )
    command = bridge.command("https://ieeexplore.ieee.org/document/11014597")
    assert "Google\\Chrome\\User Data" not in " ".join(command)
    assert str(tmp_path / "profiles" / "ieee") in command


def test_ieee_adapter_requires_official_bibtex(ieee_bridge_stub) -> None:
    ieee_bridge_stub.returns(pdf=b"%PDF-1.7\n", bibtex="")
    metadata = PaperMetadata(
        title="IEEE Paper",
        authors=("Ada Lovelace",),
        year=2026,
        venue="IEEE Test",
        doi="10.1109/test.1",
        publisher="IEEE",
        landing_url="https://ieeexplore.ieee.org/document/1",
    )
    ieee_document = SourceDocument(
        metadata=metadata,
        pdf_url="https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?arnumber=1",
        bibtex_url="https://ieeexplore.ieee.org/xpl/downloadCitations",
        allowed_hosts=frozenset({"ieeexplore.ieee.org"}),
    )
    with pytest.raises(BibMissing):
        IeeeXploreAdapter(ieee_bridge_stub).acquire(ieee_document)
```

- [ ] **Step 2: Port the audited Node tests and establish RED**

Copy the behavioral tests from:

```text
C:\Users\labs2\Desktop\Projects\mec-research-wiki\.agents\skills\retrieve-ieee-papers\scripts\tests\test-ieee-playwright.mjs
```

Change repository-specific duplicate/output assertions to the normalized bridge contract. Add a citation export fixture asserting the bridge returns `pdfPath`, raw official `bibtex`, `title`, `authors`, `year`, `venue`, `doi`, and `landingUrl`.

Run:

```powershell
node --test tests/node/test-ieee-playwright.mjs
uv run pytest tests/unit/test_ieee_bridge.py -q
```

Expected: FAIL because the generalized bridge does not exist.

- [ ] **Step 3: Port the security-proven browser implementation**

Use the existing audited implementation as source:

```text
C:\Users\labs2\Desktop\Projects\mec-research-wiki\.agents\skills\retrieve-ieee-papers\scripts\ieee-playwright.mjs
```

Preserve exact-host credential release, separate persistent Chrome profile, `BrowserContext.request`, `maxRedirects: 0`, PDF header validation, one metadata restart, and one authentication attempt. Remove all `raw/tmp`, `raw/sources`, and repository naming assumptions. Add official citation export inside the same browser context and return only sanitized JSON.

- [ ] **Step 4: Generalize DPAPI secrets and migrate ciphertext**

Store new secrets at:

```text
%LOCALAPPDATA%\Codex\secrets\acquire-research-papers\secrets.clixml
```

The payload schema contains named scopes (`ieee_gxu`, `mineru`, optional API keys). `migrate-legacy-secrets.ps1` reads the existing DPAPI payload at `%LOCALAPPDATA%\Codex\secrets\retrieve-ieee-papers.clixml` under the same Windows account and writes a new encrypted payload without printing plaintext. Reject any destination inside the Git repository.

- [ ] **Step 5: Run all IEEE and secret tests**

Run:

```powershell
node --test tests/node/test-ieee-playwright.mjs
powershell -NoProfile -ExecutionPolicy Bypass -File tests/powershell/test-secret-store.ps1
uv run pytest tests/unit/test_ieee_bridge.py -q
```

Expected: all PASS and test logs contain no synthetic secret values.

- [ ] **Step 6: Commit**

```powershell
git add src/acquire_research_papers/acquisition/adapters/ieee.py scripts tests/node tests/powershell tests/unit/test_ieee_bridge.py
git commit -m "feat: add secure IEEE institutional acquisition"
```

### Task 10: Add optional MinerU analysis cache

**Files:**
- Create: `src/acquire_research_papers/mineru.py`
- Create: `tests/unit/test_mineru.py`
- Create: `tests/integration/test_mineru_cache.py`

- [ ] **Step 1: Write failing cache tests**

```python
from datetime import UTC, datetime, timedelta


class FakeMineruRunner:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, pdf: Path, output: Path) -> MineruResult:
        self.calls += 1
        output.mkdir(parents=True, exist_ok=True)
        markdown = output / "paper.md"
        markdown.write_text("# Parsed paper\n", encoding="utf-8")
        return MineruResult(mode="precision", output_dir=output, markdown=markdown)


@pytest.fixture
def fake_mineru() -> FakeMineruRunner:
    return FakeMineruRunner()


def test_research_parse_is_content_addressed(tmp_path: Path, fake_mineru) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.7\ncache\n")
    cache = MineruCache(tmp_path / "cache", runner=fake_mineru)
    first = cache.parse(pdf)
    second = cache.parse(pdf)
    assert first == second
    assert fake_mineru.calls == 1


def test_expired_cache_is_purged(tmp_path: Path, fake_mineru) -> None:
    cache = MineruCache(tmp_path / "cache", runner=fake_mineru)
    entry = cache.create_fixture(last_accessed=datetime.now(UTC) - timedelta(days=8))
    assert cache.purge_expired(now=datetime.now(UTC)) == [entry.key]
```

- [ ] **Step 2: Run RED**

Run: `uv run pytest tests/unit/test_mineru.py tests/integration/test_mineru_cache.py -q`

Expected: missing module.

- [ ] **Step 3: Implement precision parsing and exact fallback**

Run `mineru-open-api extract <pdf> -o <precision> -f md --model pipeline --language en` with `MINERU_TOKEN` injected only into the child environment. Use isolated `precision/` and `flash/` directories. Permit one token-free `flash-extract` only when logs simultaneously identify result-archive download, exact host `cdn-mineru.openxlab.org.cn`, and EOF/TLS transport failure. Treat `429` as exit code `75` and never loop.

Store `metadata.json` with PDF SHA-256, mode, created/last-accessed timestamps, and successful output directory. `export-md` copies only the successful directory.

- [ ] **Step 4: Run GREEN and commit**

Run: `uv run pytest tests/unit/test_mineru.py tests/integration/test_mineru_cache.py -q`

Expected: PASS, including token-redaction assertions.

```powershell
git add src/acquire_research_papers/mineru.py tests/unit/test_mineru.py tests/integration/test_mineru_cache.py
git commit -m "feat: cache optional MinerU research parses"
```

### Task 11: Implement metadata discovery and generic corpus collection

**Files:**
- Create: `src/acquire_research_papers/discovery/__init__.py`
- Create: `src/acquire_research_papers/discovery/crossref.py`
- Create: `src/acquire_research_papers/discovery/openalex.py`
- Create: `src/acquire_research_papers/discovery/semantic_scholar.py`
- Create: `src/acquire_research_papers/discovery/corpus.py`
- Modify: `src/acquire_research_papers/cli.py`
- Create: `tests/fixtures/discovery/*.json`
- Create: `tests/unit/test_discovery_clients.py`
- Create: `tests/unit/test_corpus.py`
- Create: `tests/integration/test_corpus_cli.py`

- [ ] **Step 1: Write failing quota and screening tests**

```python
def test_corpus_prioritizes_recent_and_stops_at_preferred() -> None:
    spec = {
        "target": {"preferred": 3, "minimum": 2, "maximum": 4},
        "scope": {"years": {"include": [2026, 2025, 2024], "priority": [2026, 2025, 2024]}},
    }
    candidates = [
        CandidateMetadata("old", "Old", 2024, "Test", 0.99, True, ("title", "abstract")),
        CandidateMetadata("new-1", "New 1", 2026, "Test", 0.90, True, ("title", "abstract")),
        CandidateMetadata("new-2", "New 2", 2025, "Test", 0.88, True, ("title", "abstract")),
        CandidateMetadata("new-3", "New 3", 2025, "Test", 0.87, True, ("title", "abstract")),
    ]
    plan = CorpusPlanner(spec).select(candidates)
    assert [item.key for item in plan.auto_accepted] == ["new-1", "new-2", "new-3"]
    assert len(plan.auto_accepted) == 3


def test_borderline_candidate_is_pending() -> None:
    candidate = CandidateMetadata(
        "borderline", "Borderline", 2026, "Test", 0.72, True, ("abstract",)
    )
    decision = ScreeningGate().decide(candidate)
    assert decision.status is PaperStatus.PENDING_REVIEW
    assert "relevance_below_auto_threshold" in decision.reasons
```

- [ ] **Step 2: Write client fixture tests and run RED**

Test Crossref cursor/date/source filters, OpenAlex citation/related expansion, Semantic Scholar positive/negative recommendation payloads, `429` classification, and optional API key headers without printing keys.

Run: `uv run pytest tests/unit/test_discovery_clients.py tests/unit/test_corpus.py tests/integration/test_corpus_cli.py -q`

Expected: missing discovery modules.

- [ ] **Step 3: Implement candidate-only clients and corpus planner**

Define immutable `CandidateMetadata` with `key`, `title`, `year`, `venue`, `relevance_score`, `hard_gates_passed`, evidence fields, optional DOI/official URL, and discovery provenance. All discovery clients return candidates and provenance; none may return a final BibTeX or mark an artifact official. `CorpusPlanner` applies hard gates, score thresholds, year priority, minimum/preferred/maximum totals, grouped quotas, and recent-window ratio. If quality is insufficient, return `shortfall` rather than lower thresholds.

Add CLI:

```text
arp discover corpus --spec job.yaml --output <directory>
```

The command writes `candidates.jsonl` and `pending-review.csv`. Agent decisions can be imported via `arp review`; accepted candidates then reuse the `fetch` pipeline.

- [ ] **Step 4: Run GREEN and commit**

Run:

```powershell
uv run pytest tests/unit/test_discovery_clients.py tests/unit/test_corpus.py tests/integration/test_corpus_cli.py -q
uv run ruff check src tests
```

Expected: PASS.

```powershell
git add src/acquire_research_papers/discovery src/acquire_research_papers/cli.py tests/fixtures/discovery tests/unit/test_discovery_clients.py tests/unit/test_corpus.py tests/integration/test_corpus_cli.py
git commit -m "feat: discover and plan quota-driven paper corpora"
```

### Task 12: Implement research briefs and evidence packages

**Files:**
- Create: `src/acquire_research_papers/research/__init__.py`
- Create: `src/acquire_research_papers/research/planner.py`
- Create: `src/acquire_research_papers/research/evidence.py`
- Create: `src/acquire_research_papers/research/delivery.py`
- Modify: `src/acquire_research_papers/cli.py`
- Create: `tests/unit/test_research_planner.py`
- Create: `tests/unit/test_evidence.py`
- Create: `tests/integration/test_research_cli.py`

- [ ] **Step 1: Write failing research plan and evidence tests**

```python
def test_gap_plan_contains_direct_decomposed_graph_and_falsification_passes() -> None:
    brief = {
        "schema_version": 1,
        "mode": "research",
        "question_type": "gap-analysis",
        "research_question": "Does LLM-guided evolutionary search already optimize this coupling?",
        "work_under_review": {"scenario": "MEC", "mechanism": "LLM-guided EC"},
        "claims": [],
        "seed_papers": [],
        "scope": {},
        "delivery": {"write_narrative": False, "export_markdown": False},
    }
    plan = ResearchPlanner().build(brief)
    assert [query.kind for query in plan.queries] == [
        "direct",
        "mechanism-decomposition",
        "citation-expansion",
        "falsification",
    ]


def test_abstract_only_evidence_cannot_be_direct_support() -> None:
    with pytest.raises(EvidenceValidationError, match="full text"):
        EvidenceRecord(
            claim_id="claim-1",
            paper_id="paper-1",
            relation="direct-support",
            read_scope="abstract-only",
            section=None,
            page=None,
            excerpt="",
            explanation="The abstract appears relevant.",
        ).validate()
```

- [ ] **Step 2: Run RED**

Run: `uv run pytest tests/unit/test_research_planner.py tests/unit/test_evidence.py tests/integration/test_research_cli.py -q`

Expected: missing research modules.

- [ ] **Step 3: Implement deterministic research artifacts**

`ResearchPlanner` expands a validated brief into four query passes and seed graph requests. `EvidenceRecord` permits `direct-support`, `indirect-support`, `qualifies`, `contradicts`, and `background`; direct support requires full-text read scope, section/page, and a non-empty short excerpt. Store evidence in SQLite and export:

```text
research-manifest.csv
pending-review.csv
evidence-map.md
nearest-work-matrix.csv
gap-analysis.md
```

`gap-analysis.md` must include scope, search passes, closest counterexamples, and the bounded wording `within the searched scope`. It remains an evidence report, not manuscript prose, unless `delivery.write_narrative` is true.

- [ ] **Step 4: Run GREEN and commit**

Run: `uv run pytest tests/unit/test_research_planner.py tests/unit/test_evidence.py tests/integration/test_research_cli.py -q`

Expected: PASS.

```powershell
git add src/acquire_research_papers/research src/acquire_research_papers/cli.py tests/unit/test_research_planner.py tests/unit/test_evidence.py tests/integration/test_research_cli.py
git commit -m "feat: build evidence-driven literature research workflows"
```

### Task 13: Add ACM Digital Library and ScienceDirect adapters

**Files:**
- Create: `src/acquire_research_papers/acquisition/adapters/acm.py`
- Create: `src/acquire_research_papers/acquisition/adapters/sciencedirect.py`
- Create: `tests/fixtures/acm/paper.html`
- Create: `tests/fixtures/sciencedirect/open.html`
- Create: `tests/fixtures/sciencedirect/subscribed.html`
- Create: `tests/fixtures/sciencedirect/denied.html`
- Create: `tests/unit/test_acm_adapter.py`
- Create: `tests/unit/test_sciencedirect_adapter.py`

- [ ] **Step 1: Write failing provider tests**

```python
def test_acm_requires_official_citation_export(fixture_server) -> None:
    fixtures = Path(__file__).resolve().parents[1] / "fixtures"
    fixture_server.serve_text(
        "/acm/doi/10.1145/123.456",
        (fixtures / "acm" / "paper.html").read_text(encoding="utf-8"),
    )
    adapter = AcmDigitalLibraryAdapter(client=fixture_server.client)
    document = adapter.resolve(fixture_server.url("/acm/doi/10.1145/123.456"))
    assert document.bibtex_url.endswith("/action/exportCiteProcCitation")
    assert "dl.acm.org" in adapter.production_hosts


def test_sciencedirect_reports_missing_campus_entitlement(fixture_server) -> None:
    fixtures = Path(__file__).resolve().parents[1] / "fixtures"
    fixture_server.serve_text(
        "/sciencedirect/denied",
        (fixtures / "sciencedirect" / "denied.html").read_text(encoding="utf-8"),
    )
    adapter = ScienceDirectAdapter(client=fixture_server.client)
    with pytest.raises(AccessRequired):
        adapter.resolve(fixture_server.url("/sciencedirect/denied"))
```

- [ ] **Step 2: Run RED**

Run: `uv run pytest tests/unit/test_acm_adapter.py tests/unit/test_sciencedirect_adapter.py -q`

Expected: missing adapters.

- [ ] **Step 3: Implement exact page contracts**

ACM accepts only official `dl.acm.org` landing/PDF/citation export hosts and parses publication type so KDD corpus rules can exclude non-target tracks. ScienceDirect first checks official/open PDF, then detects subscriber entitlement in the current browser/network context; if no direct PDF is authorized, return `access_required`. Do not store a South China Agricultural University account. Keep Elsevier API-key support optional and disabled when no encrypted key exists.

- [ ] **Step 4: Run GREEN and commit**

Run: `uv run pytest tests/unit/test_acm_adapter.py tests/unit/test_sciencedirect_adapter.py -q`

Expected: PASS.

```powershell
git add src/acquire_research_papers/acquisition/adapters/acm.py src/acquire_research_papers/acquisition/adapters/sciencedirect.py tests/fixtures/acm tests/fixtures/sciencedirect tests/unit/test_acm_adapter.py tests/unit/test_sciencedirect_adapter.py
git commit -m "feat: support ACM and ScienceDirect official acquisition"
```

### Task 14: Complete the skill, references, CI, and security checks

**Files:**
- Modify: `SKILL.md`
- Regenerate: `agents/openai.yaml`
- Create: `references/corpus-mode.md`
- Create: `references/research-mode.md`
- Create: `references/source-policies.md`
- Create: `references/credentials-and-cache.md`
- Create: `.github/workflows/test.yml`
- Create: `scripts/validate_skill.py`
- Create: `tests/unit/test_no_sensitive_artifacts.py`

- [ ] **Step 1: Write failing policy tests**

```python
def test_repository_contains_no_runtime_artifacts() -> None:
    forbidden_suffixes = {".clixml", ".sqlite", ".pdf", ".bib"}
    tracked = subprocess.check_output(["git", "ls-files"], text=True).splitlines()
    assert not [path for path in tracked if Path(path).suffix.lower() in forbidden_suffixes]


def test_skill_routes_all_three_modes() -> None:
    text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "fetch" in text
    assert "discover corpus" in text
    assert "discover research" in text
    assert "Markdown" in text and "explicit" in text
```

- [ ] **Step 2: Run RED**

Run: `uv run pytest tests/unit/test_no_sensitive_artifacts.py -q`

Expected: fail until final policies/docs are present.

- [ ] **Step 3: Write concise progressive-disclosure skill docs**

Keep `SKILL.md` under 500 lines. Put mode details and source contracts in one-level `references/` files. State hard stops, official BibTeX policy, temporary research parsing, exact institution rules, task recovery, and when to load each reference. Do not add README, quick-reference, install-guide, or changelog files.

Regenerate metadata:

```powershell
python C:\Users\labs2\.codex\skills\.system\skill-creator\scripts\generate_openai_yaml.py . `
  --interface 'display_name=Research Paper Acquisition' `
  --interface 'short_description=Discover and acquire verified research papers' `
  --interface 'default_prompt=Use $acquire-research-papers to discover or fetch official papers and BibTeX.'
```

- [ ] **Step 4: Add CI**

GitHub Actions runs on `windows-latest` and `ubuntu-latest`, uses Python 3.11 and 3.13, installs uv, executes `uv sync --locked --all-groups`, `uv run ruff check src tests`, `uv run pytest -q`, and `uv run python scripts/validate_skill.py .`. The bundled validator checks frontmatter, name/folder equality, required files, and forbidden placeholders so CI does not depend on a user-specific Codex installation. Node/PowerShell tests run on Windows without real secrets.

- [ ] **Step 5: Run the complete deterministic gate**

Run:

```powershell
uv sync --locked --all-groups
uv run ruff check src tests
uv run pytest -q
node --test tests/node/test-ieee-playwright.mjs
powershell -NoProfile -ExecutionPolicy Bypass -File tests/powershell/test-secret-store.ps1
python C:\Users\labs2\.codex\skills\.system\skill-creator\scripts\quick_validate.py .
git diff --check
```

Expected: every command exits 0; sensitive scan reports zero.

- [ ] **Step 6: Commit**

```powershell
git add SKILL.md agents references .github tests/unit/test_no_sensitive_artifacts.py pyproject.toml uv.lock
git commit -m "docs: complete public paper acquisition skill"
```

### Task 15: Run live validation, forward tests, and publish v0.1.0

**Files:**
- Create locally but never track: runtime outputs under `%LOCALAPPDATA%\Codex` and `%USERPROFILE%\Downloads\papers`
- Modify only if live evidence requires a fix: adapter source, matching fixture, and matching test

- [ ] **Step 1: Migrate encrypted local credentials**

Run `scripts/migrate-legacy-secrets.ps1` and then a child-process decrypt probe that prints only `OK`/`FAIL`. Verify the new file is outside the repository and ignored by repository-sensitive scans. Never print or pass secrets in command arguments.

- [ ] **Step 2: Test one official open pair**

Run `arp fetch` for one current ACL or IJCAI paper. Verify official landing provenance, `%PDF-`, raw official BibTeX, metadata match, registry record, generic output, and duplicate reuse on a second invocation.

- [ ] **Step 3: Test one IEEE institutional pair**

Run `arp fetch` for an IEEE paper requiring Guangxi University CARSI. Verify no manual click, exact IdP host, PDF and official BibTeX, no cookie export, and duplicate reuse.

- [ ] **Step 4: Test one ScienceDirect pair on the campus network**

Run `arp fetch` for a subscribed Elsevier paper while South China Agricultural University campus access is available. Verify ScienceDirect provenance, PDF/BibTeX pair, and `access_required` behavior when entitlement is unavailable.

- [ ] **Step 5: Test optional MinerU behavior**

For a research task, verify temporary parsing lands only in the SHA-256 cache and is reused. Verify ordinary fetch/corpus creates no Markdown. Run `arp export-md` and confirm Markdown appears only after that explicit command.

- [ ] **Step 6: Run corpus and research forward tests**

Use fresh task prompts without revealing expected answers:

```text
Find 5 official 2024-2026 IJCAI main-track papers about LLM-assisted evolutionary optimization. Deliver PDF and official BibTeX only.
```

```text
Given one seed paper and a claim about LLM-guided evolutionary search, find the closest work and build an evidence package without drafting manuscript prose.
```

Also parse `C:\Users\labs2\Downloads\paper-download-assignment-2026-07-18.docx` with optional scope selector `学生2`, generate a small `CorpusSpec`, and acquire a bounded sample before any 200-300 paper run.

- [ ] **Step 7: Apply live fixes with TDD and rerun all gates**

For each page drift or live failure: add a failing fixture/contract test, implement the smallest adapter fix, rerun the focused test, then rerun the complete deterministic gate and relevant live smoke. Do not broaden auth hosts during selector repair.

- [ ] **Step 8: Final security and repository audit**

Run:

```powershell
git status --short --branch
git diff --check
git ls-files
uv run pytest -q
uv run ruff check src tests
```

Verify no `.clixml`, token, credential, browser profile, registry, cache, PDF, BibTeX, Markdown parse, task output, or user assignment document is tracked.

- [ ] **Step 9: Commit final live-tested fixes**

```powershell
git add --all
git diff --cached --check
git commit -m "release: validate paper acquisition skill v0.1.0"
```

Skip the commit only if the live validation produced no source changes.

- [ ] **Step 10: Create the public repository, push, and tag**

```powershell
gh repo create EnosElinsa/acquire-research-papers --public --source . --remote origin --description "Codex skill for discovering and acquiring verified research papers"
git push -u origin main
git tag -a v0.1.0 -m "acquire-research-papers v0.1.0"
git push origin v0.1.0
```

Verify:

```powershell
$local = git rev-parse HEAD
$remote = (git ls-remote origin refs/heads/main -q).Split()[0]
if ($local -ne $remote) { throw "Remote main SHA mismatch" }
gh repo view EnosElinsa/acquire-research-papers --json visibility,url,defaultBranchRef
```

Expected: visibility `PUBLIC`, default branch `main`, and matching local/remote SHA.
