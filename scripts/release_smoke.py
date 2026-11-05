"""Live smoke test of built release assets, run through ``python scripts/release.py smoke``.

The thin skill is extracted from the release ZIP into a temporary directory and bootstrapped
in isolated runtime, data, and config roots with no API keys: from the built wheel by default,
or from the public release URL with ``--public``. Each check records what it expected and what
it observed. The fetches contact real publishers; the Springer paper is a subscription article
that delivers only on an entitled network and is otherwise ``access_required``.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

FETCHES = (
    ("ACL DOI", "10.18653/v1/2023.acl-long.1", ("delivered",)),
    ("AAAI DOI", "10.1609/aaai.v38i1.27749", ("delivered",)),
    ("NeurIPS URL", "https://proceedings.neurips.cc/paper_files/paper/2023/hash/"
     "0001ca33ba34ce0351e4612b744b3936-Abstract-Conference.html", ("delivered",)),
    ("PMLR URL", "https://proceedings.mlr.press/v202/aamand23a.html", ("delivered",)),
    ("CVF URL", "https://openaccess.thecvf.com/content/CVPR2023/html/Ci_GFPose_Learning_3D_"
     "Human_Pose_Prior_With_Gradient_Fields_CVPR_2023_paper.html", ("delivered",)),
    ("IJCAI DOI", "10.24963/ijcai.2023/1", ("delivered",)),
    ("Springer URL", "https://link.springer.com/article/10.1007/s10994-021-06119-y",
     ("delivered", "access_required")),
    ("Elsevier DOI", "10.1016/j.cell.2020.02.052", ("access_required",)),
)
# Outcomes that say "try again later"; such a check is retried once before it counts.
TRANSIENT = frozenset({"network_transient", "rate_limited"})
RETRY_PAUSE_SECONDS = 30.0
ICML_2023_PAPERS = 1828  # PMLR volume 202; a different count means the official index changed
PRESET_SPEC = """mode: corpus
name: release smoke presets
target: {minimum: 1, maximum: 20}
scope:
  venues:
    - {name: INFOCOM}
    - {name: IEEE TMC}
  years: {include: [2024]}
"""
ICML_SPEC = """mode: corpus
name: release smoke archive index
target: {minimum: 1, maximum: 20, preferred: 10}
scope:
  venues:
    - {name: ICML, years: [2023]}
  years: {include: [2023]}
  topics: {include: [graph neural network]}
"""
Invoke = Callable[..., tuple[int, dict[str, Any], str]]


def _preset_count(root: Path) -> int:
    spec = importlib.util.spec_from_file_location(
        "venue_presets", root / "src/acquire_research_papers/discovery/venue_presets.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up while it executes
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return len(module.PRESETS)


class Smoke:
    def __init__(self, invoke: Invoke, workspace: Path, *, version: str, presets: int,
                 progress: Callable[[str], None], retry_pause: float = RETRY_PAUSE_SECONDS,
                 sleeper: Callable[[float], None] = time.sleep) -> None:
        self.invoke = invoke
        self.workspace = workspace
        self.version = version
        self.presets = presets
        self.progress = progress
        self.retry_pause = retry_pause
        self.sleeper = sleeper
        self.checks: list[dict[str, Any]] = []

    def check(self, name: str, expected: Any, observed: Any, passed: bool) -> bool:
        self.checks.append({"check": name, "expected": expected, "observed": observed,
                            "passed": passed})
        self.progress(f"{'ok  ' if passed else 'FAIL'} {name}: {observed}")
        return passed

    def run(self) -> list[dict[str, Any]]:
        code, payload, _ = self.invoke("--version")
        self.check("version", self.version, payload.get("version"),
                   code == 0 and payload.get("version") == self.version)
        code, payload, _ = self.invoke("doctor", "--host", "kiro-ide", "--skill-directory",
                                       str(self.workspace / "skills" / "acquire-research-papers"))
        pinned = (payload.get("skill") or {}).get("runtime_matches_pin")
        self.check("doctor runtime matches pin", True, pinned, code == 0 and pinned is True)
        _, _, help_text = self.invoke("manual-fetch", "--help", raw=True)
        self.check("manual-fetch documents --open-all", True, "--open-all" in help_text,
                   "--open-all" in help_text)
        self._presets()
        for label, reference, expected in FETCHES:
            observed, retried = fetch_with_retry(
                lambda output: self.invoke("fetch", "--input", reference, "--output", output),
                self.workspace / "out" / label.replace(" ", "-"), expected,
                pause=self.retry_pause, sleeper=self.sleeper)
            self.check(f"fetch {label}", list(expected),
                       f"{observed} (after a retry)" if retried else observed, observed in expected)
        self._discovery()
        self._background_job()
        return self.checks

    def _presets(self) -> None:
        spec = self.workspace / "preset.yaml"
        spec.write_text(PRESET_SPEC, encoding="utf-8")
        code, payload, _ = self.invoke("sources", "--spec", str(spec))
        listed = len(payload.get("venue_presets", ()))
        self.check("sources lists every venue preset", self.presets, listed,
                   code == 0 and listed == self.presets)
        routes = {row.get("venue"): (row.get("preset"), (row.get("openalex_venue") or {})
                                     .get("sources"), (row.get("crossref") or {}).get("available"))
                  for row in payload.get("requested_slices", ())}
        expected = {"INFOCOM": ("ieee-infocom", ["S7407087743"], False),
                    "IEEE TMC": ("ieee-tmc", [], True)}
        self.check("presets route INFOCOM and IEEE TMC", expected, routes, routes == expected)

    def _discovery(self) -> None:
        spec = self.workspace / "icml.yaml"
        spec.write_text(ICML_SPEC, encoding="utf-8")
        discovery = self.workspace / "discovery"
        code, payload, _ = self.invoke("discover", "corpus", "--spec", str(spec),
                                       "--output", str(discovery))
        coverage_file = discovery / "coverage.jsonl"
        rows = ([json.loads(line) for line in coverage_file.read_text(encoding="utf-8")
                 .splitlines() if line.strip()] if coverage_file.is_file() else [])
        pmlr = [(row["provider_id"], row["state"], row["records_recognized"]) for row in rows]
        self.check("discover ICML 2023 through the PMLR index",
                   [("pmlr", "complete", ICML_2023_PAPERS)], pmlr,
                   code == 0 and pmlr == [("pmlr", "complete", ICML_2023_PAPERS)])
        candidates_file = discovery / "candidates.jsonl"
        candidates = ([json.loads(line) for line in candidates_file.read_text(encoding="utf-8")
                       .splitlines() if line.strip()] if candidates_file.is_file() else [])
        complete = sum(bool(item.get("abstract")) and bool(item.get("official_url"))
                       for item in candidates)
        self.check("every ICML candidate has an abstract and official URL",
                   ICML_2023_PAPERS, complete, complete == len(candidates) == ICML_2023_PAPERS)
        if not coverage_file.is_file():
            return
        before = coverage_file.read_bytes()
        code, payload, _ = self.invoke("discover", "corpus", "--spec", str(spec),
                                       "--output", str(discovery))
        unchanged = coverage_file.read_bytes() == before
        self.check("rerun of a finished discovery changes nothing", True, unchanged,
                   code == 0 and unchanged)

    def _background_job(self) -> None:
        job = self.workspace / "job"
        code, payload, _ = self.invoke("--background", str(job), "fetch", "--input",
                                       "https://proceedings.mlr.press/v202/aamand23a.html",
                                       "--output", str(self.workspace / "out" / "job"))
        started = code == 0 and payload.get("status") == "started"
        if not self.check("background job starts", "started", payload.get("status"), started):
            return
        code, payload, _ = self.invoke("job", "status", "--job", str(job), "--wait", "300")
        observed = (payload.get("status"), payload.get("exit_code"),
                    (payload.get("result") or {}).get("status"))
        self.check("background fetch finishes delivered", ("finished", 0, "delivered"),
                   observed, observed == ("finished", 0, "delivered"))


def fetch_with_retry(fetch: Callable[[str], tuple[int, dict[str, Any], str]], output: Path,
                     expected: tuple[str, ...], *, pause: float = RETRY_PAUSE_SECONDS,
                     sleeper: Callable[[float], None] = time.sleep) -> tuple[str, bool]:
    """One fetch outcome; a transient one is retried once, into a fresh output directory."""
    for attempt in range(2):
        code, payload, _ = fetch(str(output / f"attempt-{attempt + 1}"))
        observed = ("delivered" if payload.get("status") == "delivered"
                    else payload.get("error_code") or f"exit {code}")
        if attempt or observed in expected or observed not in TRANSIENT:
            return observed, bool(attempt)
        sleeper(pause)
    raise AssertionError("unreachable")


def _invoker(skill: Path, environment: dict[str, str]) -> Invoke:
    def invoke(*arguments: str, raw: bool = False) -> tuple[int, dict[str, Any], str]:
        result = subprocess.run([sys.executable, str(skill / "scripts" / "arp.py"), *arguments],
                                capture_output=True, text=True, encoding="utf-8",
                                errors="replace", env=environment, timeout=1200, check=False)
        if raw:
            return result.returncode, {}, result.stdout
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        try:
            return result.returncode, json.loads(lines[-1]), result.stdout
        except (IndexError, json.JSONDecodeError):
            return result.returncode, {"stderr": result.stderr[-300:]}, result.stdout
    return invoke


def smoke(root: Path, *, dist: Path | None = None, public: bool = False,
          progress: Callable[[str], None] = lambda line: print(line, file=sys.stderr, flush=True),
          invoke_factory: Callable[[Path, dict[str, str]], Invoke] = _invoker) -> dict:
    version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    dist = (dist or root / "dist" / f"release-{version}").resolve()
    archive = dist / f"acquire-research-papers-skill-{version}.zip"
    wheel = dist / f"acquire_research_papers-{version}-py3-none-any.whl"
    if not archive.is_file() or (not public and not wheel.is_file()):
        raise FileNotFoundError(f"built release assets for {version} are missing in {dist}")
    workspace = Path(tempfile.mkdtemp(prefix="arp-release-smoke-"))
    try:
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(workspace / "skills")
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith("ARP_") and not key.endswith("_API_KEY")
                       and key != "MINERU_TOKEN"}
        environment.update(ARP_RUNTIME_ROOT=str(workspace / "runtime"),
                           ARP_DATA_ROOT=str(workspace / "data"),
                           ARP_CONFIG_ROOT=str(workspace / "config"),
                           ARP_IEEE_REUSE_BROWSER="0", PYTHONPATH="", PYTHONIOENCODING="utf-8")
        if not public:
            environment["ARP_LOCAL_WHEEL"] = str(wheel)
        invoke = invoke_factory(workspace / "skills" / "acquire-research-papers", environment)
        if public:
            # GitHub can answer the first download of a just-published asset with an error.
            for _ in range(3):
                code, payload, _ = invoke("--version")
                if code == 0 and payload.get("version") == version:
                    break
                time.sleep(10)
        progress(f"smoke {version} from {'the public release URL' if public else wheel.name}")
        checks = Smoke(invoke, workspace, version=version, presets=_preset_count(root),
                       progress=progress).run()
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
    failed = [item["check"] for item in checks if not item["passed"]]
    return {"status": "failed" if failed else "passed", "version": version,
            "bootstrap": "public release URL" if public else "local wheel",
            "checks": checks, "failed": failed}
