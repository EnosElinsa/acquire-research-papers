"""Interactive configuration entrypoints; stdout contains non-secret JSON only."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from acquire_research_papers.acquisition.adapters.ieee import (
    IeeeBridge,
    IeeeBridgeError,
    IeeeXploreAdapter,
)
from acquire_research_papers.acquisition.base import NotOfficial
from acquire_research_papers.artifacts import InvalidPdfError
from acquire_research_papers.bibliography import (
    BibMissing, MetadataMismatch, parse_bibtex, verify_bibliography,
)
from acquire_research_papers.http import NetworkTransient
from acquire_research_papers.institution_profiles import InstitutionStore, validate_profile
from acquire_research_papers.paths import AppPaths


class IeeeDiagnosticError(IeeeBridgeError):
    """A failed live check with sanitized, timestamped evidence of completed stages."""

    def __init__(self, phase: str, message: str, *, diagnostics: dict, retryable: bool):
        super().__init__(phase, message)
        self.diagnostics = diagnostics
        self.retryable = retryable


def runtime_paths() -> AppPaths:
    return AppPaths.default()


def store_for(paths: AppPaths) -> InstitutionStore:
    return InstitutionStore(paths.registry.parent / "institutions")


def script_root() -> Path:
    from acquire_research_papers.cli import _resolve_script_root
    return _resolve_script_root(Path(__file__).resolve().parents[2], Path(__file__).resolve().parent)


def _powershell(name: str, arguments: list[str], *, interactive: bool = False) -> Any:
    if os.name != "nt":
        raise ValueError("IEEE browser and encrypted credentials currently require Windows")
    command = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
               str(script_root() / name), *arguments]
    result = subprocess.run(command, check=False, text=True, encoding="utf-8", errors="replace",
                            capture_output=not interactive, timeout=None if interactive else 30,
                            creationflags=0 if interactive else getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise ValueError("Configuration helper did not complete; check the interactive terminal")
    if not interactive:
        return json.loads(result.stdout)
    return None


def migrate_legacy(store: InstitutionStore, paths: AppPaths) -> None:
    if not store.list() and (paths.secrets / "secrets.clixml").is_file() and os.name == "nt":
        # The bridge returns only institution routing fields, never credential values.
        try:
            legacy = _powershell("read-institution-profile.ps1",
                                 ["-SecretPath", str(paths.secrets / "secrets.clixml")])
        except ValueError:
            return
        store.migrate_legacy(legacy)


def register(config_modes: argparse._SubParsersAction) -> None:
    setup = config_modes.add_parser("setup", help="configure only the capability this task needs")
    setup.add_argument("provider", choices=["ieee", "mineru", "elsevier", "openalex", "semantic_scholar"])
    setup.add_argument("--profile", default="default")
    setup.add_argument("--organization")
    setup.add_argument("--entry-url")
    setup.add_argument("--mode", choices=["direct", "assisted", "carsi"], default="assisted")
    setup.add_argument("--contract", type=Path, help="non-secret form contract JSON")
    setup.add_argument("--replace", action="store_true")
    setup.add_argument("--no-login", action="store_true")
    setup.add_argument("--save-credentials", action="store_true")
    setup.add_argument("--inspect", action="store_true", help="observe non-sensitive form structure")
    ieee = config_modes.add_parser("ieee", help="manage named institutional access profiles")
    modes = ieee.add_subparsers(dest="ieee_action", required=True)
    modes.add_parser("list")
    use = modes.add_parser("use")
    use.add_argument("profile")
    for action in ("login", "doctor"):
        command = modes.add_parser(action)
        command.add_argument("--profile")
        command.add_argument("--reference", required=action == "doctor")
        command.add_argument("--timeout", type=int, default=900)


def bridge_for(profile: dict[str, Any], paths: AppPaths, *, timeout: int = 900) -> IeeeBridge:
    root = script_root()
    store = store_for(paths)
    browser = store.browser_directory(paths.profiles / "ieee-profiles", profile["id"])
    if profile.get("credential_ref") == "legacy:ieee_institution" and (paths.profiles / "ieee").is_dir():
        browser = paths.profiles / "ieee"
    return IeeeBridge(script=root / "ieee-playwright.mjs",
                      profile_root=browser,
                      dependency_root=paths.dependencies, work_root=paths.runs,
                      secret_path=paths.secrets / "secrets.clixml",
                      access_profile=store.path(profile["id"]), timeout_seconds=timeout,
                      accept_attribute_release=bool(profile.get("contract", {}).get("acceptAttributeRelease", False)))


def candidate_contract(observation: dict[str, Any]) -> dict[str, Any]:
    """Suggest exact locators without enabling automatic login or reading input values."""
    form = observation.get("form", {})
    result: dict[str, Any] = {"credentialHost": observation.get("hostname"),
                              "requires_review": True}
    def locator(control):
        labels = control.get("labels") or []
        if len(labels) == 1 and labels[0]:
            return {"kind": "label", "value": labels[0]}
        if control.get("placeholder"):
            return {"kind": "placeholder", "value": control["placeholder"]}
        for field in ("id", "name"):
            if control.get(field):
                return {"kind": field, "value": control[field]}
        return None
    for name, types in (("usernameLocator", {"text", "email"}), ("passwordLocator", {"password"})):
        controls = [c for c in form.get("inputs", []) if c.get("type") in types]
        if len(controls) == 1 and locator(controls[0]):
            result[name] = locator(controls[0])
    buttons = form.get("controls") or []
    if len(buttons) == 1:
        button = buttons[0]
        result["loginLocator"] = ({"kind": "role", "role": button.get("role", "button"),
                                   "value": button["text"]} if button.get("text") else locator(button))
    result["template"] = "single_page" if "passwordLocator" in result else "two_step_or_manual"
    return result


def dispatch(args: argparse.Namespace) -> dict[str, Any] | None:
    if args.command not in {"config", "credentials"} or args.config_mode == "status":
        return None
    paths = runtime_paths()
    store = store_for(paths)
    migrate_legacy(store, paths)
    if args.config_mode == "setup":
        if args.provider != "ieee":
            name = "setup-mineru-token.ps1" if args.provider == "mineru" else "setup-discovery-api-keys.ps1"
            arguments = ["-Path", str(paths.secrets / "secrets.clixml")]
            if args.provider != "mineru":
                arguments.extend(["-Provider", args.provider])
            _powershell(name, arguments, interactive=True)
            return {"status": "stored", "provider": args.provider}
        organization = args.organization or input("Institution name: ").strip()
        entry = args.entry_url or input("Official IEEE/library entry URL (HTTPS): ").strip()
        contract = json.loads(args.contract.read_text(encoding="utf-8")) if args.contract else {}
        profile = {"schema_version": 2, "id": args.profile, "organization": organization,
                   "mode": args.mode, "entry_url": entry, "contract": contract}
        if args.mode == "carsi":
            profile["credential_host"] = contract.get("credentialHost", "")
            profile["credential_ref"] = f"ieee_profiles:{args.profile}"
        profile = validate_profile(profile)
        if store.path(args.profile).exists() and not args.replace:
            raise ValueError("institution profile already exists; use --replace to update it")
        if args.save_credentials:
            if args.mode != "carsi":
                raise ValueError("saved credentials require a configured automatic CARSI form")
            _powershell("setup-ieee-profile-credential.ps1",
                        ["-ProfileId", args.profile, "-CredentialHost", profile["credential_host"],
                         "-Path", str(paths.secrets / "secrets.clixml")], interactive=True)
        saved = store.save(profile, replace=args.replace)
        store.use(args.profile)
        result: dict[str, Any] = {"status": "configured", "profile": saved}
        if args.inspect:
            observation = bridge_for(saved, paths).operate("inspect")
            # This observation has names/types/labels only; it contains no values or HTML.
            result["observation"] = observation
            result["candidate_contract"] = candidate_contract(observation)
        if not args.no_login and args.mode != "direct":
            result["login"] = bridge_for(saved, paths).operate("login")
        return result
    if args.ieee_action == "list":
        return {"profiles": store.list(), **store.details()}
    if args.ieee_action == "use":
        selected = store.use(args.profile)
        return {"status": "selected", "profile": selected["id"]}
    profile = store.get(args.profile) if args.profile else store.active()
    if not profile:
        raise ValueError("configure an IEEE profile with arp config setup ieee first")
    if args.timeout < 1 or args.timeout > 3600:
        raise ValueError("timeout must be between 1 and 3600 seconds")
    bridge = bridge_for(profile, paths, timeout=args.timeout)
    if args.ieee_action == "login":
        result = bridge.operate("login", args.reference)
        if result.get("status") == "downloaded":
            # A login operation with a reference also performed an actual publisher download.
            result = {"status": "verified", "download_verified": True,
                      "returned_to_ieee": True, "access": result.get("access", "unknown")}
        store.record_validation(profile["id"], result)
        return result
    diagnostic = {"configuration_valid": True, "download_verified": False,
                  "returned_to_ieee": None, "institution_login_completed": None,
                  "access": "unknown"}
    try:
        result = bridge.retrieve(args.reference)
        diagnostic.update(returned_to_ieee=True, access=result.access,
                          institution_login_completed=True if result.access == "institutional" else None)
        pair = IeeeXploreAdapter(bridge)._pair(result)
        verify_bibliography(pair.document.metadata, parse_bibtex(pair.bibtex_text))
        diagnostic = {"status": "verified", "configuration_valid": True, "download_verified": True,
                      "returned_to_ieee": True, "access": result.access,
                      "institution_login_completed": True if result.access == "institutional" else None}
        updated = store.record_validation(profile["id"], diagnostic)
        return {**diagnostic, **updated["last_validation"]}
    except (IeeeBridgeError, NetworkTransient, MetadataMismatch, BibMissing, InvalidPdfError,
            NotOfficial, OSError, subprocess.TimeoutExpired) as exc:
        retryable = isinstance(exc, (NetworkTransient, subprocess.TimeoutExpired))
        phase = (exc.phase if isinstance(exc, IeeeBridgeError) else
                 "dependency-timeout" if isinstance(exc, subprocess.TimeoutExpired) else
                 "publisher-transport" if isinstance(exc, NetworkTransient) else
                 "local-io" if isinstance(exc, OSError) else "artifact-validation")
        diagnostic.update(phase=phase, requires_user_action=isinstance(exc, IeeeBridgeError) and
                          phase in {"access-required", "authentication-not-complete", "manual-login-timeout"})
        updated = store.record_validation(profile["id"], diagnostic)
        message = ("IEEE runtime dependency setup timed out." if isinstance(exc, subprocess.TimeoutExpired)
                   else str(exc))
        raise IeeeDiagnosticError(phase, message, diagnostics=updated["last_validation"],
                                  retryable=retryable) from exc
