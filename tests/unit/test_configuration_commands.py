import json

import pytest

from acquire_research_papers.cli import run_cli
from acquire_research_papers.paths import AppPaths


def test_schema_cli_does_not_initialize_application(capsys):
    assert run_cli(["schema", "paper-record.schema.json"]) == 0
    assert json.loads(capsys.readouterr().out)["type"] == "object"


def test_profile_setup_defaults_to_assisted_without_touching_secrets(tmp_path, monkeypatch, capsys):
    from acquire_research_papers import configuration_commands as config
    monkeypatch.setattr(config, "runtime_paths", lambda: AppPaths.for_root(tmp_path))
    assert run_cli(["config", "setup", "ieee", "--profile", "campus-one",
                    "--organization", "Example", "--entry-url", "https://library.example.edu/",
                    "--no-login"]) == 0
    saved = json.loads(capsys.readouterr().out)
    assert saved["profile"]["mode"] == "assisted"
    assert not (tmp_path / "secrets").exists()
    assert run_cli(["config", "ieee", "list"]) == 0
    assert json.loads(capsys.readouterr().out)["profiles"][0]["id"] == "campus-one"


def test_config_details_reports_history_separately(tmp_path, monkeypatch, capsys):
    from acquire_research_papers import configuration_commands as config
    monkeypatch.setattr(config, "runtime_paths", lambda: AppPaths.for_root(tmp_path))
    assert run_cli(["config", "status", "--details"],
                   credential_status=lambda: {"ieee": False}) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["ieee_details"]["live_check"] is False


def test_profile_setup_rejects_conflicts_as_json(tmp_path, monkeypatch, capsys):
    from acquire_research_papers import configuration_commands as config
    monkeypatch.setattr(config, "runtime_paths", lambda: AppPaths.for_root(tmp_path))
    args = ["config", "setup", "ieee", "--profile", "campus", "--organization", "Example",
            "--entry-url", "https://library.example.edu/", "--no-login"]
    assert run_cli(args) == 0
    capsys.readouterr()
    assert run_cli(args) == 78
    assert json.loads(capsys.readouterr().out)["status"] == "error"


def test_normal_fetch_selects_the_named_profile_without_switching_active(tmp_path, monkeypatch):
    from acquire_research_papers import configuration_commands as config
    from acquire_research_papers.cli import Application
    paths = AppPaths.for_root(tmp_path)
    monkeypatch.setattr(AppPaths, "default", classmethod(lambda cls: paths))
    store = config.store_for(paths)
    for identifier in ("one", "two"):
        store.save({"schema_version": 2, "id": identifier, "organization": identifier,
                    "mode": "assisted", "entry_url": "https://library.example.edu/"})
    app = Application.default(ieee_profile="two", load_discovery_api_keys=False)
    adapter = app.resolver.router.adapter_for("https://ieeexplore.ieee.org/document/1")
    assert adapter.bridge.access_profile == store.path("two")
    assert adapter.bridge.profile_root == paths.profiles / "ieee-profiles" / "two"
    assert store.active()["id"] == "one"


def test_library_audit_cli_avoids_initializing_browser_capabilities(tmp_path, monkeypatch, capsys):
    from acquire_research_papers.cli import Application
    def unexpected(**kwargs):
        raise AssertionError("offline library operations must not initialize application")
    monkeypatch.setattr(Application, "default", unexpected)
    library = tmp_path / "library"
    library.mkdir()
    assert run_cli(["library", "audit", str(library), "--metadata", str(tmp_path / "metadata.json"),
                    "--output", str(tmp_path / "report")]) == 64
    assert json.loads(capsys.readouterr().out)["status"] == "error"


def test_inspection_suggests_typed_locators_without_enabling_automatic_login():
    from acquire_research_papers.configuration_commands import candidate_contract
    candidate = candidate_contract({'hostname':'login.example.edu', 'form':{'inputs':[
        {'type':'text','labels':['Account'], 'id':'u'},
        {'type':'password','labels':[], 'placeholder':'Password'}],
        'controls':[{'role':'button','text':'Sign in'}]}})
    assert candidate['usernameLocator'] == {'kind':'label','value':'Account'}
    assert candidate['passwordLocator']['kind'] == 'placeholder'
    assert candidate['loginLocator']['role'] == 'button'
    assert candidate['requires_review'] is True


def test_doctor_distinguishes_public_download_from_subscription(tmp_path, monkeypatch, capsys):
    from acquire_research_papers import configuration_commands as config
    from types import SimpleNamespace
    paths = AppPaths.for_root(tmp_path)
    monkeypatch.setattr(config, 'runtime_paths', lambda: paths)
    store = config.store_for(paths)
    store.save({'schema_version':2,'id':'campus','organization':'Example','mode':'assisted',
                'entry_url':'https://library.example.edu/'})
    bridge = SimpleNamespace(retrieve=lambda ref: SimpleNamespace(access='public'))
    monkeypatch.setattr(config, 'bridge_for', lambda *args, **kwargs: bridge)
    monkeypatch.setattr(config.IeeeXploreAdapter, '_pair', lambda self, result:
        SimpleNamespace(document=SimpleNamespace(metadata=None), bibtex_text='@article{k,title={Work}}'))
    monkeypatch.setattr(config, 'verify_bibliography', lambda *args: None)
    assert run_cli(['config','ieee','doctor','--reference','10.1234/example']) == 0
    output = json.loads(capsys.readouterr().out)
    assert output['configuration_valid'] is True
    assert output['download_verified'] is True
    assert output['institutional_entitlement_verified'] is False
    assert output['institution_login_completed'] is None


@pytest.mark.parametrize('failure,code,returned', [
    ('transport', 75, None), ('citation', 78, True), ('authentication', 69, None),
    ('artifact_io', 78, None), ('dependency_timeout', 75, None),
])
def test_doctor_failure_reports_layers_and_replaces_historical_success(
    tmp_path, monkeypatch, capsys, failure, code, returned
):
    from acquire_research_papers import configuration_commands as config
    from acquire_research_papers.bibliography import MetadataMismatch
    from acquire_research_papers.http import NetworkTransient
    from types import SimpleNamespace
    paths = AppPaths.for_root(tmp_path)
    monkeypatch.setattr(config, 'runtime_paths', lambda: paths)
    store = config.store_for(paths)
    store.save({'schema_version':2, 'id':'campus', 'organization':'Example', 'mode':'assisted',
                'entry_url':'https://library.example.edu/'})
    store.record_validation('campus', {'download_verified':True, 'access':'institutional'})
    def retrieve(reference):
        import subprocess
        if failure == 'transport':
            raise NetworkTransient('Publisher request timed out')
        if failure == 'authentication':
            raise config.IeeeBridgeError('authentication-not-complete', 'User action required')
        if failure == 'artifact_io':
            raise FileNotFoundError('Publisher PDF artifact is missing')
        if failure == 'dependency_timeout':
            raise subprocess.TimeoutExpired(['private-helper-command'], 30)
        return SimpleNamespace(access='institutional')
    monkeypatch.setattr(config, 'bridge_for', lambda *args, **kwargs: SimpleNamespace(retrieve=retrieve))
    def invalid_pair(self, result):
        raise MetadataMismatch('Citation identity mismatch')
    monkeypatch.setattr(config.IeeeXploreAdapter, '_pair', invalid_pair)
    assert run_cli(['config', 'ieee', 'doctor', '--reference', '10.1234/example']) == code
    output = json.loads(capsys.readouterr().out)
    diagnostic = output['diagnostics']
    assert diagnostic['configuration_valid'] is True
    assert diagnostic['returned_to_ieee'] is returned
    assert diagnostic['download_verified'] is False
    assert diagnostic['institutional_entitlement_verified'] is False
    assert diagnostic['checked_at']
    assert store.get('campus')['last_validation'] == diagnostic
