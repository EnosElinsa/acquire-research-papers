"""Interactive configuration entrypoints; stdout contains non-secret JSON only."""
from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
import shlex
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
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
from acquire_research_papers.institution_profiles import InstitutionStore, profile_id, validate_profile
from acquire_research_papers.paths import AppPaths
from acquire_research_papers.file_credentials import CredentialManager, TOKEN_HOSTS


class IeeeDiagnosticError(IeeeBridgeError):
    """A failed live check with sanitized, timestamped evidence of completed stages."""

    def __init__(self, phase: str, message: str, *, diagnostics: dict, retryable: bool):
        super().__init__(phase, message)
        self.diagnostics = diagnostics
        self.retryable = retryable


def runtime_paths() -> AppPaths:
    return AppPaths.default()


def _profile_migration_path(paths: AppPaths) -> Path:
    journal = paths.config_paths.root / ".arp-profile-migration.json"
    if journal.resolve() != journal:
        raise ValueError("Invalid profile migration journal path")
    return journal


@contextmanager
def _profile_migration_lock(paths: AppPaths) -> Iterator[None]:
    root = paths.config_paths.root
    root.mkdir(parents=True, exist_ok=True)
    target = root / ".arp-profile-migration.lock"
    if target.resolve() != target:
        raise ValueError("Invalid profile migration lock path")
    # Keep this file after unlocking so every process locks the same inode.
    with target.open("a+b") as handle:
        if os.fstat(handle.fileno()).st_size == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ValueError("Profile migration is in progress; retry when it finishes") from None
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _profile_metadata_path(paths: AppPaths, name: str) -> Path:
    if not isinstance(name, str) or not name.endswith(".json"):
        raise ValueError("Invalid profile migration journal filename")
    if name != "active.json":
        profile_id(name[:-5])
    root = paths.config_paths.root / "institutions"
    target = root / name
    partial = target.with_suffix(".json.partial")
    if root.resolve() != root or target.resolve() != target or partial.resolve() != partial:
        raise ValueError("Invalid profile migration journal target")
    return target


def _atomic_profile_bytes(target: Path, data: bytes) -> None:
    """Publish journal/recovery metadata without a reusable crash-sensitive temp name."""
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".arp-profile-", suffix=".tmp", dir=target.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        if os.name != "nt":
            descriptor = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def _profile_journal_records(paths: AppPaths, payload: Any) -> list[tuple[Path, bytes | None]]:
    """Validate the entire nonsecret journal before changing any metadata."""
    try:
        if (not isinstance(payload, dict) or set(payload) != {"schema_version", "originals"}
                or type(payload["schema_version"]) is not int or payload["schema_version"] != 1
                or not isinstance(payload["originals"], list)):
            raise ValueError
        records = []
        seen = set()
        for entry in payload["originals"]:
            if not isinstance(entry, dict) or set(entry) != {"name", "content"}:
                raise ValueError
            target = _profile_metadata_path(paths, entry["name"])
            if target in seen:
                raise ValueError
            seen.add(target)
            content = entry["content"]
            if content is not None:
                if not isinstance(content, str):
                    raise ValueError
                content = base64.b64decode(content, validate=True)
                value = json.loads(content.decode("utf-8"))
                if target.name == "active.json":
                    if not isinstance(value, dict) or set(value) != {"id"}:
                        raise ValueError
                    profile_id(value["id"])
                elif validate_profile(value)["id"] != target.stem:
                    raise ValueError
            records.append((target, content))
        return records
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise ValueError("Invalid profile migration journal; preserve it for diagnosis") from None


def _begin_profile_migration(paths: AppPaths, originals: dict[Path, bytes | None]) -> None:
    journal = _profile_migration_path(paths)
    if journal.exists():
        raise ValueError("Unfinished profile migration journal requires recovery")
    payload = {"schema_version": 1, "originals": [
        {"name": target.name, "content": base64.b64encode(content).decode("ascii")
         if content is not None else None} for target, content in originals.items()]}
    _profile_journal_records(paths, payload)
    _atomic_profile_bytes(journal, (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8"))


def _recover_profile_migration(paths: AppPaths, backend: Callable[[], str], *,
                               locked: bool = False) -> str | None:
    journal = _profile_migration_path(paths)
    if not journal.exists():
        return None
    if not locked:
        with _profile_migration_lock(paths):
            return _recover_profile_migration(paths, backend, locked=True)
    try:
        payload = json.loads(journal.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError):
        raise ValueError("Invalid profile migration journal; preserve it for diagnosis") from None
    records = _profile_journal_records(paths, payload)
    selected = backend()
    for target, content in records:
        if selected == "dpapi":
            if content is None:
                target.unlink(missing_ok=True)
            elif not target.exists() or target.read_bytes() != content:
                _atomic_profile_bytes(target, content)
        # An interrupted InstitutionStore publication can leave this exact
        # partial name; the validated journal limits cleanup to affected files.
        target.with_suffix(".json.partial").unlink(missing_ok=True)
    journal.unlink()
    return selected


def store_for(paths: AppPaths, *, manager: CredentialManager | None = None) -> InstitutionStore:
    legacy = paths.registry.parent / "institutions"
    current = paths.config_paths.institutions
    if legacy.is_dir():
        if not current.is_dir():
            return InstitutionStore(legacy)
        selected = manager if manager is not None else credential_manager(paths)
        if selected.backend == "dpapi":
            return InstitutionStore(legacy)
    return InstitutionStore(current)


def credential_manager(paths: AppPaths, *, env_file: Path | None = None) -> CredentialManager:
    from acquire_research_papers.credentials import DpapiApiKeyProvider, DpapiCredentialStatusProvider
    from acquire_research_papers.mineru import DpapiMineruTokenProvider

    api_values: dict[tuple[str, str], str | None] = {}
    institution_values: dict[tuple[str, str, str], dict | None] = {}
    status_values: dict[str, bool] | None = None

    def read(provider: str, host: str) -> str | None:
        if os.name != "nt":
            raise ValueError("DPAPI requires the original Windows account; migrate on Windows first")
        if TOKEN_HOSTS.get(provider) != host.casefold():
            raise ValueError("API credential host does not match the provider")
        key = provider, host.casefold()
        if key not in api_values:
            if provider == "mineru":
                api_values[key] = DpapiMineruTokenProvider(
                    script=script_root() / "read-mineru-token.ps1",
                    secret_path=paths.secrets / "secrets.clixml")()
            else:
                api_values[key] = DpapiApiKeyProvider(provider=provider, expected_host=host,
                    script=script_root() / "read-discovery-api-key.ps1",
                    secret_path=paths.secrets / "secrets.clixml").optional()
        return api_values[key]

    def institution(profile: dict, host: str) -> dict | None:
        identifier = CredentialManager._institution_identity(profile, host, allow_legacy=True)
        key = identifier, profile["credential_ref"], host.casefold()
        if key not in institution_values:
            arguments = ["-SecretPath", str(paths.secrets / "secrets.clixml"),
                         "-ExpectedHost", host, "-Optional"]
            if profile.get("credential_ref") != "legacy:ieee_institution":
                arguments += ["-ProfileId", identifier]
            institution_values[key] = _powershell("read-browser-credential.ps1", arguments)
        value = institution_values[key]
        return dict(value) if value is not None else None

    def status():
        nonlocal status_values
        if os.name != "nt":
            raise ValueError("DPAPI requires Windows; migrate on the original machine first")
        if status_values is None:
            status_values = DpapiCredentialStatusProvider(
                script=script_root() / "credential-status.ps1",
                secret_path=paths.secrets / "secrets.clixml")()
        return dict(status_values)

    manager = CredentialManager(paths, env_file=env_file, legacy_reader=read,
                                legacy_status=status, legacy_institution=institution)
    recovered = _recover_profile_migration(paths, manager._backend)
    if recovered is not None and recovered != manager.backend:
        raise ValueError("Configuration backend changed during migration recovery; retry the command")
    return manager


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
    config_modes.add_parser("init", help="create editable empty configuration templates")
    for action in ("path", "edit"):
        command = config_modes.add_parser(action)
        command.add_argument("--profile")
    migrate = config_modes.add_parser("migrate", help="explicitly copy legacy DPAPI credentials")
    migrate.add_argument("--from", dest="from_backend", choices=["dpapi"], required=True)
    setup = config_modes.add_parser("setup", help="configure only the capability this task needs")
    setup.add_argument("provider", choices=["ieee", "mineru", "elsevier", "openalex", "semantic_scholar"])
    setup.add_argument("--profile", default="default")
    setup.add_argument("--organization")
    setup.add_argument("--entry-url")
    setup.add_argument("--credential-host", help="exact login host for saved institution credentials")
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


def bridge_for(profile: dict[str, Any], paths: AppPaths, *, timeout: int = 900,
               manager: CredentialManager | None = None) -> IeeeBridge:
    root = script_root()
    manager = manager if manager is not None else credential_manager(paths)
    store = store_for(paths, manager=manager)
    browser = store.browser_directory(paths.profiles / "ieee-profiles", profile["id"])
    if profile.get("credential_ref") == "legacy:ieee_institution" and (paths.profiles / "ieee").is_dir():
        browser = paths.profiles / "ieee"
    return IeeeBridge(script=root / "ieee-playwright.mjs",
                      profile_root=browser,
                      dependency_root=paths.dependencies, work_root=paths.runs,
                      secret_path=paths.secrets / "secrets.clixml",
                      access_profile=store.path(profile["id"]), timeout_seconds=timeout,
                      credential_provider=(lambda host: manager.institution(profile, host))
                          if profile.get("mode") == "carsi" else None,
                      credential_host=profile.get("credential_host", ""),
                      data_root=paths.registry.parent.parent,
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
    manager = credential_manager(paths, env_file=getattr(args, "env_file", None))
    store = store_for(paths, manager=manager)
    if args.config_mode == "init":
        return manager.initialize()
    if args.config_mode in {"path", "edit"}:
        target = manager.env_file
        if args.profile:
            profile = store.get(args.profile)
            target = paths.config_paths.credentials / f"{profile['id']}.env"
        if args.config_mode == "edit":
            manager.initialize()
            if args.profile:
                from acquire_research_papers.file_credentials import FileCredentialStore
                FileCredentialStore(target).initialize(("INSTITUTION_USERNAME", "INSTITUTION_PASSWORD"))
            editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
            command = shlex.split(editor) if editor and os.name != "nt" else (
                ["notepad"] if os.name == "nt" else ["open", "-t"] if sys.platform == "darwin"
                else ["xdg-open"])
            # A Windows editor value is already a native command line. Re-splitting
            # it with shlex keeps literal quotes which Popen would quote a second time.
            launch = (editor.strip() + " " + subprocess.list2cmdline([str(target)])
                      if editor and os.name == "nt" else [*command, str(target)])
            subprocess.Popen(launch,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return {"config": str(paths.config_paths.settings), "env_file": str(target),
                "institutions": str(store.root), "backend": manager.backend}
    if args.config_mode == "migrate":
        if manager.backend != "dpapi" or not (paths.secrets / "secrets.clixml").is_file():
            raise ValueError("DPAPI migration requires the selected legacy backend; it may already be migrated")
        migrate_legacy(store, paths)
        profiles = [store.get(item["id"]) for item in store.list()]
        active = store.active()
        destination = InstitutionStore(paths.config_paths.institutions)
        copied = []
        for profile in profiles:
            updated = dict(profile)
            if profile.get("credential_ref"):
                updated.update(credential_ref=f"ieee_profiles:{profile['id']}",
                               credential_file=f"credentials/{profile['id']}.env")
            copied.append(validate_profile(updated))

        def profile_conflicts():
            if destination.root == store.root:
                return []
            conflicts = [f"institutions/{profile['id']}.json" for profile in copied
                if destination.path(profile["id"]).exists()
                and destination.get(profile["id"]) != profile]
            if active and (destination.root / "active.json").exists():
                selected = destination.active()
                if selected is None or selected["id"] != active["id"]:
                    conflicts.append("institutions/active.json")
            return sorted(conflicts)

        conflicts = profile_conflicts()
        if conflicts:
            return {"status": "conflict", "conflicts": conflicts}

        def export():
            if manager.legacy_status is None or manager.legacy_reader is None:
                raise ValueError("DPAPI credential reader is unavailable")
            configured = manager.legacy_status()
            api = {key: manager.legacy_reader(key, TOKEN_HOSTS[key])
                   for key in TOKEN_HOSTS if configured.get(key)}
            institutions = []
            for profile in profiles:
                if not profile.get("credential_ref") or not profile.get("credential_host"):
                    continue
                pair = manager.institution(profile, profile["credential_host"])
                if pair:
                    updated = {**profile, "credential_ref": f"ieee_profiles:{profile['id']}",
                               "credential_file": f"credentials/{profile['id']}.env"}
                    institutions.append({"profile": updated,
                        "expected_host": profile["credential_host"], **pair})
            return {"api": api, "institutions": institutions}

        originals: dict[Path, bytes | None] = {}

        def copy_profiles():
            conflicts = profile_conflicts()
            if conflicts:
                raise ValueError("Migration profile conflict: " + ", ".join(conflicts))
            targets = [destination.path(profile["id"]) for profile in copied]
            targets.append(destination.root / "active.json")
            originals.update({path: path.read_bytes() if path.exists() else None for path in targets})
            _begin_profile_migration(paths, originals)
            for profile in copied:
                if not destination.path(profile["id"]).exists() or destination.get(profile["id"]) != profile:
                    destination.save(profile, replace=True)
            if active:
                destination.use(active["id"])

        with _profile_migration_lock(paths):
            if manager._backend() != "dpapi":
                raise ValueError("DPAPI migration is already complete; retry the command")
            try:
                result = manager.migrate_from_dpapi(export, before_switch=copy_profiles)
            except Exception:
                # Use the committed settings, including failure immediately after
                # the settings rename. Abrupt termination leaves this replayable
                # journal for the next normal manager construction.
                _recover_profile_migration(paths, manager._backend, locked=True)
                raise
            _recover_profile_migration(paths, manager._backend, locked=True)
            return result
    migrate_legacy(store, paths)
    if args.config_mode == "setup":
        if args.provider != "ieee":
            if manager.backend == "file":
                manager.initialize()
                manager.save_api(args.provider, getpass.getpass(f"{args.provider} credential (hidden): "))
                return {"status": "stored", "provider": args.provider,
                        "env_file": str(manager.env_file)}
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
        if args.mode == "carsi" or args.save_credentials:
            profile["credential_host"] = args.credential_host or contract.get("credentialHost", "")
            profile["credential_ref"] = f"ieee_profiles:{args.profile}"
            if manager.backend == "file":
                profile["credential_file"] = f"credentials/{args.profile}.env"
        profile = validate_profile(profile)
        if store.path(args.profile).exists() and not args.replace:
            raise ValueError("institution profile already exists; use --replace to update it")
        if args.save_credentials:
            if not profile.get("credential_host"):
                raise ValueError("saved credentials require an exact credential host")
            if manager.backend == "file":
                manager.save_institution(profile, username=input("Institution username: "),
                                         password=getpass.getpass("Institution password (hidden): "))
            else:
                _powershell("setup-ieee-profile-credential.ps1",
                        ["-ProfileId", args.profile, "-CredentialHost", profile["credential_host"],
                            "-Path", str(paths.secrets / "secrets.clixml")], interactive=True)
        saved = store.save(profile, replace=args.replace)
        store.use(args.profile)
        result: dict[str, Any] = {"status": "configured", "profile": saved}
        if args.inspect:
            observation = bridge_for(saved, paths, manager=manager).operate("inspect")
            # This observation has names/types/labels only; it contains no values or HTML.
            result["observation"] = observation
            result["candidate_contract"] = candidate_contract(observation)
        if not args.no_login and args.mode != "direct":
            result["login"] = bridge_for(saved, paths, manager=manager).operate("login")
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
    bridge = bridge_for(profile, paths, timeout=args.timeout, manager=manager)
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
