import argparse
import base64
import json
import sys
from types import SimpleNamespace

import pytest

from acquire_research_papers import configuration_commands as config
from acquire_research_papers.credentials import API_PROVIDER_HOSTS
from acquire_research_papers.file_credentials import CredentialManager, FileCredentialStore
from acquire_research_papers.institution_profiles import InstitutionStore
from acquire_research_papers.paths import AppPaths


def command(*arguments):
    parser = argparse.ArgumentParser()
    parser.set_defaults(command="config", env_file=None)
    modes = parser.add_subparsers(dest="config_mode", required=True)
    config.register(modes)
    return parser.parse_args(arguments)


def legacy_paths(tmp_path):
    paths = AppPaths.for_root(tmp_path)
    paths.secrets.mkdir(parents=True)
    (paths.secrets / "secrets.clixml").write_bytes(b"encrypted legacy data")
    return paths


def assisted_profile(identifier="campus"):
    return {"schema_version": 2, "id": identifier, "organization": "Example",
            "mode": "assisted", "entry_url": "https://library.example.edu/"}


def test_migration_exports_dpapi_api_values_instead_of_process_overrides(tmp_path, monkeypatch):
    paths = legacy_paths(tmp_path)
    manager = CredentialManager(paths, environ={"OPENALEX_API_KEY": "process-secret"},
        legacy_status=lambda: {"openalex": True},
        legacy_reader=lambda provider, host: "stored-secret")
    monkeypatch.setattr(config, "runtime_paths", lambda: paths)
    monkeypatch.setattr(config, "credential_manager", lambda *args, **kwargs: manager)
    monkeypatch.setattr(config, "migrate_legacy", lambda *args: None)

    result = config.dispatch(command("migrate", "--from", "dpapi"))

    assert result["status"] == "migrated"
    assert FileCredentialStore(paths.config_paths.env_file).snapshot()["OPENALEX_API_KEY"] == "stored-secret"
    assert "secret" not in repr(result)
    assert manager.api_provider("openalex", "api.openalex.org")() == "process-secret"


@pytest.mark.parametrize("retained_legacy", [False, True])
def test_migration_rejects_file_backend_without_overwriting_configuration(
    tmp_path, monkeypatch, retained_legacy
):
    paths = legacy_paths(tmp_path) if retained_legacy else AppPaths.for_root(tmp_path)
    paths.config.mkdir(parents=True)
    paths.config_paths.settings.write_text('[credentials]\nbackend = "file"\n')
    FileCredentialStore(paths.config_paths.env_file).update({"OPENALEX_API_KEY": "file-secret"})
    original = paths.config_paths.settings.read_bytes()
    monkeypatch.setattr(config, "runtime_paths", lambda: paths)

    with pytest.raises(ValueError, match="DPAPI|dpapi|already"):
        config.dispatch(command("migrate", "--from", "dpapi"))

    assert paths.config_paths.settings.read_bytes() == original
    assert FileCredentialStore(paths.config_paths.env_file).snapshot()["OPENALEX_API_KEY"] == "file-secret"


def test_migration_writes_only_explicitly_selected_env_file(tmp_path, monkeypatch):
    paths = legacy_paths(tmp_path)
    FileCredentialStore(paths.config_paths.env_file).update({"OPENALEX_API_KEY": "default-value"})
    environment_file = tmp_path / "environment.env"
    FileCredentialStore(environment_file).update({"OPENALEX_API_KEY": "environment-value"})
    selected = tmp_path / "explicit.env"
    FileCredentialStore(selected).update({"OTHER": "preserved"})
    monkeypatch.setattr(config, "runtime_paths", lambda: paths)
    monkeypatch.setattr(config, "migrate_legacy", lambda *args: None)
    monkeypatch.setattr(config, "credential_manager", lambda paths, **kwargs: CredentialManager(
        paths, **kwargs, environ={"ARP_ENV_FILE": str(environment_file)},
        legacy_status=lambda: {"openalex": True}, legacy_reader=lambda provider, host: "stored-value"))
    args = command("migrate", "--from", "dpapi")
    args.env_file = selected

    assert config.dispatch(args)["status"] == "migrated"

    assert FileCredentialStore(selected).snapshot() == {
        "OTHER": "preserved", "OPENALEX_API_KEY": "stored-value"}
    assert FileCredentialStore(environment_file).snapshot()["OPENALEX_API_KEY"] == "environment-value"
    assert FileCredentialStore(paths.config_paths.env_file).snapshot()["OPENALEX_API_KEY"] == "default-value"


def test_migration_reports_destination_profile_conflicts_without_overwriting(tmp_path, monkeypatch):
    paths = legacy_paths(tmp_path)
    source = InstitutionStore(paths.registry.parent / "institutions")
    source.save(assisted_profile())
    destination = InstitutionStore(paths.config_paths.institutions)
    destination.save({**assisted_profile(), "organization": "Existing university"})
    original = destination.path("campus").read_bytes()
    monkeypatch.setattr(config, "runtime_paths", lambda: paths)
    monkeypatch.setattr(config, "migrate_legacy", lambda *args: None)
    monkeypatch.setattr(config, "credential_manager", lambda *args, **kwargs: CredentialManager(
        paths, environ={}, legacy_status=lambda: {"openalex": True},
        legacy_reader=lambda provider, host: "stored-secret"))

    result = config.dispatch(command("migrate", "--from", "dpapi"))

    assert result == {"status": "conflict", "conflicts": ["institutions/campus.json"]}
    assert destination.path("campus").read_bytes() == original
    assert not paths.config_paths.env_file.exists()
    assert CredentialManager(paths, environ={}).backend == "dpapi"
    assert "Existing university" not in repr(result)


def test_migration_reports_active_profile_conflict_without_replacing_selection(tmp_path, monkeypatch):
    paths = legacy_paths(tmp_path)
    source = InstitutionStore(paths.registry.parent / "institutions")
    source.save(assisted_profile("one"))
    source.save(assisted_profile("two"))
    destination = InstitutionStore(paths.config_paths.institutions)
    destination.save(assisted_profile("two"))
    monkeypatch.setattr(config, "runtime_paths", lambda: paths)
    monkeypatch.setattr(config, "migrate_legacy", lambda *args: None)
    monkeypatch.setattr(config, "credential_manager", lambda *args, **kwargs: CredentialManager(
        paths, environ={}, legacy_status=lambda: {"openalex": True},
        legacy_reader=lambda provider, host: "stored-secret"))

    result = config.dispatch(command("migrate", "--from", "dpapi"))

    assert result == {"status": "conflict", "conflicts": ["institutions/active.json"]}
    assert destination.active()["id"] == "two"
    assert not destination.path("one").exists()
    assert not paths.config_paths.env_file.exists()


def test_profile_copy_failure_preserves_legacy_routing_and_allows_retry(tmp_path, monkeypatch):
    paths = legacy_paths(tmp_path)
    source = InstitutionStore(paths.registry.parent / "institutions")
    source.save(assisted_profile("one"))
    source.save(assisted_profile("two"))
    source.use("two")
    source_bytes = {path.name: path.read_bytes() for path in source.root.glob("*.json")}
    monkeypatch.setattr(config, "runtime_paths", lambda: paths)
    monkeypatch.setattr(config, "migrate_legacy", lambda *args: None)
    monkeypatch.setattr(config, "credential_manager", lambda *args, **kwargs: CredentialManager(
        paths, environ={}, legacy_status=lambda: {"openalex": True},
        legacy_reader=lambda provider, host: "stored-secret"))
    save = InstitutionStore.save
    failing = True

    def save_profile(store, profile, **kwargs):
        if failing and store.root == paths.config_paths.institutions and profile["id"] == "two":
            raise OSError("profile storage unavailable")
        return save(store, profile, **kwargs)

    monkeypatch.setattr(InstitutionStore, "save", save_profile)
    with pytest.raises(OSError, match="profile storage unavailable"):
        config.dispatch(command("migrate", "--from", "dpapi"))

    assert CredentialManager(paths, environ={}).backend == "dpapi"
    assert config.store_for(paths).root == source.root
    assert {path.name: path.read_bytes() for path in source.root.glob("*.json")} == source_bytes
    failing = False
    assert config.dispatch(command("migrate", "--from", "dpapi"))["status"] == "migrated"
    assert config.store_for(paths).active()["id"] == "two"
    assert (paths.secrets / "secrets.clixml").read_bytes() == b"encrypted legacy data"


def test_profile_copy_failure_restores_existing_current_profiles_and_active_pointer(
    tmp_path, monkeypatch
):
    paths = legacy_paths(tmp_path)
    source = InstitutionStore(paths.config_paths.institutions)
    for identifier in ("one", "two"):
        source.save({**assisted_profile(identifier), "credential_host": "login.example.edu",
                     "credential_ref": "legacy:ieee_institution"})
    source.use("two")
    originals = {path.name: path.read_bytes() for path in source.root.glob("*.json")}
    monkeypatch.setattr(config, "runtime_paths", lambda: paths)
    monkeypatch.setattr(config, "migrate_legacy", lambda *args: None)
    monkeypatch.setattr(config, "credential_manager", lambda *args, **kwargs: CredentialManager(
        paths, environ={}, legacy_status=lambda: {},
        legacy_reader=lambda provider, host: None,
        legacy_institution=lambda profile, host: {"username": "alice", "password": "stored-secret"}))
    use = InstitutionStore.use

    def fail_active(store, identifier):
        if store.root == source.root:
            raise OSError("active pointer unavailable")
        return use(store, identifier)

    monkeypatch.setattr(InstitutionStore, "use", fail_active)
    with pytest.raises(OSError, match="active pointer unavailable"):
        config.dispatch(command("migrate", "--from", "dpapi"))

    assert CredentialManager(paths, environ={}).backend == "dpapi"
    assert {path.name: path.read_bytes() for path in source.root.glob("*.json")} == originals


def test_backend_switch_failure_restores_copied_profile_metadata(tmp_path, monkeypatch):
    paths = legacy_paths(tmp_path)
    source = InstitutionStore(paths.config_paths.institutions)
    source.save({**assisted_profile(), "credential_host": "login.example.edu",
                 "credential_ref": "legacy:ieee_institution"})
    original = source.path("campus").read_bytes()
    manager = CredentialManager(paths, environ={}, legacy_status=lambda: {},
        legacy_reader=lambda provider, host: None,
        legacy_institution=lambda profile, host: {"username": "alice", "password": "stored-secret"})
    monkeypatch.setattr(config, "runtime_paths", lambda: paths)
    monkeypatch.setattr(config, "migrate_legacy", lambda *args: None)
    monkeypatch.setattr(config, "credential_manager", lambda *args, **kwargs: manager)

    def unavailable():
        raise OSError("backend switch unavailable")

    monkeypatch.setattr(manager, "_set_file_backend", unavailable)
    with pytest.raises(OSError, match="backend switch unavailable"):
        config.dispatch(command("migrate", "--from", "dpapi"))

    assert CredentialManager(paths, environ={}).backend == "dpapi"
    assert source.path("campus").read_bytes() == original


@pytest.mark.parametrize("interruption", ["between_profiles", "before_switch", "after_switch"])
def test_fresh_manager_recovers_interrupted_profile_migration(tmp_path, monkeypatch, interruption):
    class AbruptStop(BaseException):
        pass

    paths = legacy_paths(tmp_path)
    store = InstitutionStore(paths.config_paths.institutions)
    for identifier in ("one", "two"):
        store.save({**assisted_profile(identifier), "credential_host": "login.example.edu",
                    "credential_ref": "legacy:ieee_institution"})
    store.use("two")
    originals = {path.name: path.read_bytes() for path in store.root.glob("*.json")}
    manager = config.credential_manager(paths)
    manager.legacy_status = lambda: {}
    manager.legacy_reader = lambda provider, host: None
    manager.legacy_institution = lambda profile, host: {"username": "alice", "password": "stored-secret"}
    monkeypatch.setattr(config, "runtime_paths", lambda: paths)
    monkeypatch.setattr(config, "migrate_legacy", lambda *args: None)
    save = InstitutionStore.save
    switch = manager._set_file_backend

    def save_profile(destination, profile, **kwargs):
        if interruption == "between_profiles" and profile["id"] == "two":
            raise AbruptStop()
        return save(destination, profile, **kwargs)

    def interrupted_switch():
        if interruption == "after_switch":
            switch()
        raise AbruptStop()

    journal = paths.config / ".arp-profile-migration.json"
    with monkeypatch.context() as temporary:
        temporary.setattr(config, "credential_manager", lambda *args, **kwargs: manager)
        temporary.setattr(InstitutionStore, "save", save_profile)
        if interruption != "between_profiles":
            temporary.setattr(manager, "_set_file_backend", interrupted_switch)
        with pytest.raises(AbruptStop):
            config.dispatch(command("migrate", "--from", "dpapi"))

    assert journal.is_file()
    assert "stored-secret" not in journal.read_text()
    assert all(b"stored-secret" not in base64.b64decode(entry["content"])
               for entry in json.loads(journal.read_text())["originals"] if entry["content"])
    assert store.get("one")["credential_ref"] == "ieee_profiles:one"
    recovered = config.credential_manager(paths)

    assert not journal.exists()
    assert store.active()["id"] == "two"
    if interruption == "after_switch":
        assert recovered.backend == "file"
        assert store.get("one")["credential_ref"] == "ieee_profiles:one"
        assert store.get("two")["credential_ref"] == "ieee_profiles:two"
    else:
        assert recovered.backend == "dpapi"
        assert {path.name: path.read_bytes() for path in store.root.glob("*.json")} == originals


@pytest.mark.parametrize("name", ["../outside.json", "nested/campus.json", "config.toml", "aux.json"])
def test_migration_recovery_rejects_untrusted_paths_before_writing(tmp_path, name):
    paths = legacy_paths(tmp_path)
    paths.config.mkdir(parents=True)
    outside = tmp_path / "outside.json"
    outside.write_bytes(b"preserved outside metadata")
    journal = paths.config / ".arp-profile-migration.json"
    journal.write_text(json.dumps({"schema_version": 1, "originals": [{"name": name,
        "content": base64.b64encode(b"{}").decode("ascii")}]}))

    with pytest.raises(ValueError, match="migration.*journal|journal.*migration"):
        config.credential_manager(paths)

    assert outside.read_bytes() == b"preserved outside metadata"
    assert journal.exists()


def test_invalid_journal_record_does_not_partially_restore_valid_profile(tmp_path):
    paths = legacy_paths(tmp_path)
    store = InstitutionStore(paths.config_paths.institutions)
    store.save(assisted_profile())
    original = store.path("campus").read_bytes()
    journal = paths.config / ".arp-profile-migration.json"
    journal.write_text(json.dumps({"schema_version": 1, "originals": [
        {"name": "campus.json", "content": None},
        {"name": "other.json", "content": "invalid-base64"}]}))

    with pytest.raises(ValueError, match="migration.*journal|journal.*migration"):
        config.credential_manager(paths)

    assert store.path("campus").read_bytes() == original
    assert journal.exists()


def test_recovery_removes_only_profiles_created_by_the_interrupted_migration(tmp_path):
    paths = legacy_paths(tmp_path)
    store = InstitutionStore(paths.config_paths.institutions)
    store.save(assisted_profile())
    unrelated = store.root / "notes.txt"
    unrelated.write_bytes(b"preserve unrelated configuration")
    journal = paths.config / ".arp-profile-migration.json"
    journal.write_text(json.dumps({"schema_version": 1, "originals": [
        {"name": "campus.json", "content": None}, {"name": "active.json", "content": None}]}))

    assert config.credential_manager(paths).backend == "dpapi"

    assert not store.path("campus").exists()
    assert not (store.root / "active.json").exists()
    assert unrelated.read_bytes() == b"preserve unrelated configuration"
    assert not journal.exists()


def test_normal_command_does_not_rollback_a_live_migration(tmp_path):
    paths = legacy_paths(tmp_path)
    store = InstitutionStore(paths.config_paths.institutions)
    profile = {**assisted_profile(), "credential_host": "login.example.edu",
               "credential_ref": "legacy:ieee_institution"}
    store.save(profile)
    original = store.path("campus").read_bytes()
    journal = paths.config / ".arp-profile-migration.json"
    journal.write_text(json.dumps({"schema_version": 1, "originals": [{"name": "campus.json",
        "content": base64.b64encode(original).decode("ascii")}]}))
    store.save({**profile, "credential_ref": "ieee_profiles:campus",
                "credential_file": "credentials/campus.env"}, replace=True)

    with config._profile_migration_lock(paths):
        with pytest.raises(ValueError, match="migration.*progress"):
            config.credential_manager(paths)
        assert store.get("campus")["credential_ref"] == "ieee_profiles:campus"
        assert journal.exists()

    config.credential_manager(paths)
    assert store.path("campus").read_bytes() == original
    assert not journal.exists()


def test_interrupted_recovery_is_replayed_and_clears_known_partial_files(tmp_path, monkeypatch):
    class AbruptStop(BaseException):
        pass

    paths = legacy_paths(tmp_path)
    store = InstitutionStore(paths.config_paths.institutions)
    originals = {}
    for identifier in ("one", "two"):
        profile = {**assisted_profile(identifier), "credential_host": "login.example.edu",
                   "credential_ref": "legacy:ieee_institution"}
        store.save(profile)
        originals[identifier + ".json"] = store.path(identifier).read_bytes()
        store.save({**profile, "credential_ref": f"ieee_profiles:{identifier}",
                    "credential_file": f"credentials/{identifier}.env"}, replace=True)
    journal = paths.config / ".arp-profile-migration.json"
    journal.write_text(json.dumps({"schema_version": 1, "originals": [{"name": name,
        "content": base64.b64encode(content).decode("ascii")} for name, content in originals.items()]}))
    partial = store.path("one").with_suffix(".json.partial")
    partial.write_bytes(b"unfinished metadata publication")
    publish = config._atomic_profile_bytes

    def interrupted_publish(target, content):
        if target.name == "two.json":
            raise AbruptStop()
        publish(target, content)

    with monkeypatch.context() as temporary:
        temporary.setattr(config, "_atomic_profile_bytes", interrupted_publish)
        with pytest.raises(AbruptStop):
            config.credential_manager(paths)

    assert journal.exists()
    config.credential_manager(paths)
    assert not journal.exists()
    assert not partial.exists()
    assert {name: (store.root / name).read_bytes() for name in originals} == originals


def test_partial_current_profiles_do_not_hide_legacy_store_until_backend_switch(tmp_path):
    paths = legacy_paths(tmp_path)
    legacy = InstitutionStore(paths.registry.parent / "institutions")
    legacy.save(assisted_profile("legacy"))
    current = InstitutionStore(paths.config_paths.institutions)
    current.save(assisted_profile("current"))

    assert config.store_for(paths).active()["id"] == "legacy"
    paths.config_paths.settings.write_text('[credentials]\nbackend = "file"\n')
    assert config.store_for(paths).active()["id"] == "current"


def test_setup_inspection_and_login_share_one_credential_manager(tmp_path, monkeypatch):
    paths = AppPaths.for_root(tmp_path)
    monkeypatch.setattr(config, "runtime_paths", lambda: paths)
    original = config.credential_manager
    managers = []

    def make_manager(*args, **kwargs):
        manager = original(*args, **kwargs)
        managers.append(manager)
        return manager

    bridges = []

    def make_bridge(profile, paths, **kwargs):
        bridges.append(kwargs.get("manager"))
        return SimpleNamespace(operate=lambda action: {"hostname": "login.example.edu", "form": {}})

    monkeypatch.setattr(config, "credential_manager", make_manager)
    monkeypatch.setattr(config, "bridge_for", make_bridge)
    result = config.dispatch(command("setup", "ieee", "--organization", "Example",
                                    "--entry-url", "https://library.example.edu/", "--inspect"))

    assert result["profile"]["mode"] == "assisted"
    assert len(managers) == 1
    assert bridges == [managers[0], managers[0]]


def test_ieee_login_uses_the_command_credential_manager(tmp_path, monkeypatch):
    paths = AppPaths.for_root(tmp_path)
    manager = CredentialManager(paths, environ={})
    store = config.store_for(paths, manager=manager)
    store.save(assisted_profile())
    monkeypatch.setattr(config, "runtime_paths", lambda: paths)
    monkeypatch.setattr(config, "credential_manager", lambda *args, **kwargs: manager)
    managers = []

    def bridge(profile, paths, **kwargs):
        managers.append(kwargs.get("manager"))
        return SimpleNamespace(operate=lambda *args: {"status": "manual_required"})

    monkeypatch.setattr(config, "bridge_for", bridge)
    assert config.dispatch(command("ieee", "login"))["status"] == "manual_required"
    assert managers == [manager]


def test_assisted_setup_saves_account_without_enabling_automatic_login(tmp_path, monkeypatch):
    paths = AppPaths.for_root(tmp_path)
    monkeypatch.setattr(config, "runtime_paths", lambda: paths)
    monkeypatch.setattr("builtins.input", lambda prompt: "alice")
    monkeypatch.setattr(config.getpass, "getpass", lambda prompt: "private-password")
    contract = tmp_path / "contract.json"
    contract.write_text(json.dumps({"credentialHost": "login.example.edu"}))

    result = config.dispatch(command("setup", "ieee", "--profile", "campus",
        "--organization", "Example", "--entry-url", "https://library.example.edu/",
        "--contract", str(contract), "--save-credentials", "--no-login"))

    profile = result["profile"]
    assert profile["mode"] == "assisted"
    assert "private-password" not in repr(result)
    pair = CredentialManager(paths, environ={}).institution(profile, "login.example.edu")
    assert pair == {"username": "alice", "password": "private-password"}
    bridge = config.bridge_for(profile, paths)
    assert bridge.credential_provider is None


def test_assisted_setup_accepts_an_exact_host_without_an_automatic_form_contract(tmp_path, monkeypatch):
    paths = AppPaths.for_root(tmp_path)
    monkeypatch.setattr(config, "runtime_paths", lambda: paths)
    monkeypatch.setattr("builtins.input", lambda prompt: "alice")
    monkeypatch.setattr(config.getpass, "getpass", lambda prompt: "private-password")

    result = config.dispatch(command("setup", "ieee", "--organization", "Example",
        "--entry-url", "https://library.example.edu/", "--credential-host", "login.example.edu",
        "--save-credentials", "--no-login"))

    assert result["profile"]["mode"] == "assisted"
    assert result["profile"]["credential_host"] == "login.example.edu"
    assert result["profile"]["contract"] == {}
    assert CredentialManager(paths, environ={}).institution(result["profile"], "login.example.edu") == {
        "username": "alice", "password": "private-password"}


@pytest.mark.skipif(config.os.name != "nt", reason="Windows editor command contract")
def test_windows_editor_keeps_quoted_executable_and_quoted_target(tmp_path, monkeypatch):
    paths = AppPaths.for_root(tmp_path / "data with spaces")
    monkeypatch.setattr(config, "runtime_paths", lambda: paths)
    config.credential_manager(paths).initialize()
    editor = tmp_path / "editor probe.py"
    output = tmp_path / "editor arguments.json"
    editor.write_text("import json, sys\nfrom pathlib import Path\n"
                      "Path(sys.argv[1]).write_text(json.dumps(sys.argv[2:]))\n")
    monkeypatch.setenv("VISUAL", f'"{sys.executable}" "{editor}" "{output}" --label "Paper Keys"')
    popen = config.subprocess.Popen

    def launch(*args, **kwargs):
        process = popen(*args, **kwargs)
        assert process.wait(timeout=15) == 0
        return process

    monkeypatch.setattr(config.subprocess, "Popen", launch)

    config.dispatch(command("edit"))

    assert json.loads(output.read_text()) == ["--label", "Paper Keys", str(paths.config_paths.env_file)]


def test_dpapi_browser_credentials_use_the_selected_manager_snapshot(tmp_path, monkeypatch):
    paths = legacy_paths(tmp_path)
    manager = CredentialManager(paths, environ={}, legacy_institution=lambda profile, host: {
        "username": "alice", "password": "stored-secret"})
    profile = {**assisted_profile(), "mode": "carsi", "credential_host": "login.example.edu",
               "credential_ref": "legacy:ieee_institution"}

    bridge = config.bridge_for(profile, paths, manager=manager)

    assert callable(bridge.credential_provider)
    assert bridge.credential_provider("login.example.edu") == {
        "username": "alice", "password": "stored-secret"}
    with pytest.raises(ValueError, match="host"):
        bridge.credential_provider("login.example.edu.attacker")


@pytest.mark.parametrize("reference", ["legacy:ieee_institution", "ieee_profiles:campus"])
def test_missing_dpapi_institution_credentials_are_optional_and_snapshotted(
    tmp_path, monkeypatch, reference
):
    paths = legacy_paths(tmp_path)
    calls = []

    def powershell(name, arguments):
        calls.append((name, arguments))
        return None

    monkeypatch.setattr(config, "_powershell", powershell)
    manager = config.credential_manager(paths)
    profile = {**assisted_profile(), "credential_host": "login.example.edu",
               "credential_ref": reference}

    assert manager.institution(profile, "login.example.edu") is None
    assert manager.institution(profile, "login.example.edu") is None
    expected = ["-SecretPath", str(paths.secrets / "secrets.clixml"),
                "-ExpectedHost", "login.example.edu", "-Optional"]
    if reference != "legacy:ieee_institution":
        expected += ["-ProfileId", "campus"]
    assert calls == [("read-browser-credential.ps1", expected)]


@pytest.mark.skipif(config.os.name != "nt", reason="DPAPI transport requires Windows")
def test_legacy_transport_reads_are_snapshotted_once(tmp_path, monkeypatch):
    from acquire_research_papers import credentials as legacy

    paths = legacy_paths(tmp_path)
    calls = []
    token_values = iter(["first", "changed"])

    class Provider:
        def __init__(self, **kwargs):
            pass

        def optional(self):
            calls.append("api")
            return next(token_values)

    def powershell(name, arguments):
        calls.append("institution")
        return {"username": "alice", "password": str(len(calls))}

    monkeypatch.setattr(legacy, "DpapiApiKeyProvider", Provider)
    monkeypatch.setattr(config, "_powershell", powershell)
    manager = config.credential_manager(paths)
    profile = {**assisted_profile(), "credential_host": "login.example.edu",
               "credential_ref": "legacy:ieee_institution"}
    host = API_PROVIDER_HOSTS["openalex"]

    assert manager.legacy_reader("openalex", host) == "first"
    assert manager.legacy_reader("openalex", host) == "first"
    first = manager.institution(profile, "login.example.edu")
    assert manager.institution(profile, "login.example.edu") == first
    assert calls == ["api", "institution"]
