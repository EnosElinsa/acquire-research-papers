import os

import pytest

from acquire_research_papers import file_credentials as fc
from acquire_research_papers.paths import AppPaths


def manager(tmp_path, **kwargs):
    return fc.CredentialManager(AppPaths.for_root(tmp_path), environ={}, **kwargs)


@pytest.mark.parametrize('text', [
    'credentials = ["private-sentinel"]',
    '[credentials]\nbackend = ["private-sentinel"]',
    '[credentials]\nbackend = {value="private-sentinel"}',
])
def test_malformed_backend_shape_returns_a_sanitized_configuration_error(tmp_path, text):
    paths = AppPaths.for_root(tmp_path)
    paths.config.mkdir()
    paths.config_paths.settings.write_text(text, encoding='utf-8')
    with pytest.raises(ValueError, match='credentials.backend') as error:
        manager(tmp_path)
    assert 'private-sentinel' not in str(error.value)


def test_snapshot_uses_one_file_and_process_precedence_without_interpolation(tmp_path):
    paths = AppPaths.for_root(tmp_path)
    paths.config.mkdir()
    (paths.config / '.env').write_text('OPENALEX_API_KEY=default\n', encoding='utf-8')
    selected = tmp_path / 'chosen.env'
    selected.write_text('OPENALEX_API_KEY="中文 # $HOME ${HOME}"\nMINERU_TOKEN=\n', encoding='utf-8')
    env = {'ARP_ENV_FILE': str(selected), 'ELSEVIER_API_KEY': 'process-key'}
    credentials = fc.CredentialManager(paths, environ=env)
    selected.write_text('OPENALEX_API_KEY=changed\n', encoding='utf-8')
    env['ELSEVIER_API_KEY'] = 'changed'
    assert credentials.api_provider('openalex', 'api.openalex.org')() == '中文 # $HOME ${HOME}'
    assert credentials.api_provider('elsevier', 'api.elsevier.com')() == 'process-key'
    assert credentials.api_provider('mineru', 'mineru.net').optional() is None
    assert credentials.status()['openalex'] is True
    with pytest.raises(ValueError, match='host'):
        credentials.api_provider('openalex', 'api.openalex.org.evil.example')


def test_explicit_file_wins_and_empty_process_value_does_not_fall_back(tmp_path):
    selected = tmp_path / 'selected.env'
    selected.write_text('OPENALEX_API_KEY=file\n', encoding='utf-8')
    credentials = fc.CredentialManager(AppPaths.for_root(tmp_path), env_file=selected,
        environ={'ARP_ENV_FILE': str(tmp_path / 'absent'), 'OPENALEX_API_KEY': ''})
    assert credentials.api_provider('openalex', 'api.openalex.org').optional() is None


@pytest.mark.parametrize('line', ['not an assignment secret-material', 'OPENALEX_API_KEY="secret-material'])
def test_malformed_lines_fail_without_values(tmp_path, line):
    selected = tmp_path / 'bad.env'
    selected.write_text('# comment\n' + line + '\n', encoding='utf-8')
    with pytest.raises(ValueError) as error:
        manager(tmp_path, env_file=selected)
    assert 'secret-material' not in str(error.value)
    assert 'line 2' in str(error.value)


def test_updates_preserve_comments_other_keys_and_roundtrip_special_values(tmp_path):
    path = tmp_path / 'settings.env'
    path.write_text('# retained\nOTHER="untouched"\nOPENALEX_API_KEY=old # keep note\n', encoding='utf-8')
    store = fc.FileCredentialStore(path)
    store.update({'OPENALEX_API_KEY': "中文 ' # $ ${HOME} \\value\nline"})
    text = path.read_text(encoding='utf-8')
    assert '# retained\nOTHER="untouched"\n' in text
    assert '# keep note' in text
    assert store.snapshot()['OPENALEX_API_KEY'] == "中文 ' # $ ${HOME} \\value\nline"


def test_institution_credentials_are_bound_to_ref_host_and_profile(tmp_path):
    credentials = manager(tmp_path)
    profile = {'id': 'campus', 'credential_ref': 'ieee_profiles:campus', 'credential_file':'credentials/campus.env',
               'credential_host': 'login.example.edu'}
    credentials.save_institution(profile, username='alice', password='secret')
    assert credentials.institution(profile, 'login.example.edu') == {'username':'alice', 'password':'secret'}
    with pytest.raises(ValueError, match='host'):
        credentials.institution(profile, 'login.example.edu.evil')
    with pytest.raises(ValueError, match='reference'):
        credentials.institution({**profile, 'credential_ref':'ieee_profiles:other', 'credential_file':'credentials/other.env'}, 'login.example.edu')
    assert credentials.institution({**profile, 'id':'other', 'credential_ref':'ieee_profiles:other', 'credential_file':'credentials/other.env'}, 'login.example.edu') is None
    assert 'secret' not in repr(credentials)
    assert credentials.status(profile)['ieee'] is True


def test_legacy_install_does_not_mix_file_values_and_migration_preserves_payload(tmp_path):
    paths = AppPaths.for_root(tmp_path)
    paths.secrets.mkdir(parents=True)
    old = paths.secrets / 'secrets.clixml'
    old.write_bytes(b'old encrypted payload')
    paths.config.mkdir()
    (paths.config / '.env').write_text('OPENALEX_API_KEY=file\n', encoding='utf-8')
    credentials = fc.CredentialManager(paths, environ={}, legacy_reader=lambda p,h: None)
    assert credentials.backend == 'dpapi'
    assert credentials.api_provider('openalex', 'api.openalex.org').optional() is None
    result = credentials.migrate_from_dpapi(lambda: {'api': {'openalex':'legacy'}})
    assert result == {'status':'conflict', 'conflicts':['OPENALEX_API_KEY']}
    assert credentials.backend == 'dpapi'
    assert old.read_bytes() == b'old encrypted payload'
    assert 'legacy' not in repr(result)


def test_migration_is_explicit_and_switches_only_after_complete_success(tmp_path):
    credentials = manager(tmp_path)
    profile = {'id':'campus', 'credential_ref':'ieee_profiles:campus', 'credential_file':'credentials/campus.env', 'credential_host':'login.example.edu'}
    result = credentials.migrate_from_dpapi(lambda: {'api': {'openalex':'legacy-key'},
        'institutions':[{'profile':profile, 'expected_host':'login.example.edu', 'username':'alice','password':'secret'}]})
    assert result['status'] == 'migrated'
    fresh = manager(tmp_path)
    assert fresh.backend == 'file'
    assert fresh.api_provider('openalex', 'api.openalex.org')() == 'legacy-key'
    assert fresh.institution(profile, 'login.example.edu')['password'] == 'secret'
    assert 'secret' not in repr(result)


def test_init_never_overwrites_and_new_files_are_private(tmp_path):
    credentials = manager(tmp_path)
    credentials.initialize()
    path = credentials.config.env_file
    fc.FileCredentialStore(path).update({'OPENALEX_API_KEY':'existing'})
    credentials.initialize()
    assert fc.FileCredentialStore(path).snapshot()['OPENALEX_API_KEY'] == 'existing'
    if os.name != 'nt':
        assert path.stat().st_mode & 0o777 == 0o600


def test_config_and_data_roots_are_isolated_and_legacy_layout_retained(tmp_path, monkeypatch):
    monkeypatch.setenv('ARP_DATA_ROOT', str(tmp_path / 'data'))
    monkeypatch.delenv('ARP_CONFIG_ROOT', raising=False)
    assert AppPaths.default().config == tmp_path / 'data' / 'config'
    monkeypatch.setenv('ARP_CONFIG_ROOT', str(tmp_path / 'explicit'))
    assert AppPaths.default().config == tmp_path / 'explicit'
    from acquire_research_papers.paths import ConfigPaths
    assert ConfigPaths.for_root(tmp_path).env_file == tmp_path / '.env'

def test_profile_file_reference_rejects_cross_profile_or_arbitrary_path(tmp_path):
    credentials = manager(tmp_path)
    profile = {'id':'campus', 'credential_ref':'ieee_profiles:campus',
               'credential_host':'login.example.edu', 'credential_file':'credentials/other.env'}
    with pytest.raises(ValueError, match='file'):
        credentials.save_institution(profile, username='alice', password='secret')


def test_assisted_status_does_not_require_saved_credentials(tmp_path):
    credentials = manager(tmp_path)
    assert credentials.status({'id':'campus','mode':'assisted'})['ieee'] is False


def test_legacy_institution_reference_is_exactly_bound_before_bridge_release(tmp_path):
    paths = AppPaths.for_root(tmp_path)
    paths.secrets.mkdir(parents=True)
    (paths.secrets / 'secrets.clixml').write_bytes(b'encrypted')
    credentials = fc.CredentialManager(paths, environ={},
        legacy_institution=lambda profile, host: {'username':'alice','password':'secret'})
    profile = {'id':'legacy-default','credential_ref':'legacy:ieee_institution',
               'credential_host':'login.example.edu'}
    assert credentials.institution(profile, 'login.example.edu')['username'] == 'alice'
    with pytest.raises(ValueError, match='host'):
        credentials.institution(profile, 'login.example.edu.evil')


def test_migration_snapshot_reflects_migrated_values_without_environment_overwrite(tmp_path):
    credentials = fc.CredentialManager(AppPaths.for_root(tmp_path), environ={'MINERU_TOKEN':'process'})
    credentials.migrate_from_dpapi(lambda: {'api':{'openalex':'migrated','mineru':'file'}})
    assert credentials.api_provider('openalex', 'api.openalex.org')() == 'migrated'
    assert credentials.api_provider('mineru', 'mineru.net')() == 'process'


def test_migration_invalid_secret_type_makes_no_partial_writes(tmp_path):
    credentials = manager(tmp_path)
    with pytest.raises(ValueError):
        credentials.migrate_from_dpapi(lambda: {'api':{'openalex':'valid','mineru':{'secret':'x'}}})
    assert not credentials.env_file.exists()


def test_default_paths_use_application_name_but_retain_detected_legacy_root(tmp_path, monkeypatch):
    from acquire_research_papers import paths as path_module
    monkeypatch.delenv('ARP_DATA_ROOT', raising=False)
    monkeypatch.delenv('ARP_CONFIG_ROOT', raising=False)
    monkeypatch.setattr(path_module, 'user_data_dir', lambda name, appauthor=False: str(tmp_path/name))
    monkeypatch.setattr(path_module, 'user_config_dir', lambda name, appauthor=False: str(tmp_path/'settings'/name))
    assert AppPaths.default().registry == tmp_path/'acquire-research-papers'/'paper-acquisition'/'registry.sqlite'
    legacy = tmp_path/'Codex'/'paper-acquisition'/'institutions'
    legacy.mkdir(parents=True)
    assert AppPaths.default().registry == tmp_path/'Codex'/'paper-acquisition'/'registry.sqlite'
    assert AppPaths.default().config == tmp_path/'settings'/'acquire-research-papers'

def test_export_failure_suppresses_secret_exception_and_writes_nothing(tmp_path):
    import traceback
    credentials = manager(tmp_path)
    def export():
        raise RuntimeError('secret-marker')
    with pytest.raises(ValueError) as error:
        credentials.migrate_from_dpapi(export)
    assert 'secret-marker' not in ''.join(traceback.format_exception(error.value))
    assert not credentials.config.settings.exists()
    assert not credentials.env_file.exists()


def test_institution_migration_conflict_preflights_before_writing_api_keys(tmp_path):
    credentials = manager(tmp_path)
    profile = {'id':'campus','credential_ref':'ieee_profiles:campus', 'credential_file':'credentials/campus.env','credential_host':'login.example.edu'}
    credentials.save_institution(profile, username='old-user', password='old-password')
    result = credentials.migrate_from_dpapi(lambda: {'api':{'openalex':'new-api-key'},
        'institutions':[{'profile':profile,'expected_host':'login.example.edu',
                         'username':'new-user','password':'new-password'}]})
    assert result == {'status':'conflict', 'conflicts':['INSTITUTION_PASSWORD','INSTITUTION_USERNAME']}
    assert not credentials.env_file.exists()
    assert credentials.institution(profile, 'login.example.edu')['password'] == 'old-password'


def test_institution_file_symlink_cannot_release_another_profiles_values(tmp_path):
    credentials = manager(tmp_path)
    root = credentials.config.credentials
    root.mkdir(parents=True)
    fc.FileCredentialStore(root/'other.env').update({'INSTITUTION_USERNAME':'other','INSTITUTION_PASSWORD':'secret'})
    try:
        (root/'campus.env').symlink_to(root/'other.env')
    except OSError:
        pytest.skip('Current Windows account does not have symlink permission')
    profile = {'id':'campus','credential_ref':'ieee_profiles:campus', 'credential_file':'credentials/campus.env','credential_host':'login.example.edu'}
    with pytest.raises(ValueError, match='file'):
        credentials.institution(profile, 'login.example.edu')

def test_process_api_environment_overrides_dpapi_without_per_value_file_fallback(tmp_path):
    paths = AppPaths.for_root(tmp_path)
    paths.secrets.mkdir(parents=True)
    (paths.secrets/'secrets.clixml').write_bytes(b'encrypted')
    calls = []
    def legacy(provider, host):
        calls.append(provider)
        return 'legacy'
    credentials = fc.CredentialManager(paths, environ={'OPENALEX_API_KEY':'process','MINERU_TOKEN':''},
                                        legacy_reader=legacy)
    assert credentials.api_provider('openalex', 'api.openalex.org')() == 'process'
    assert credentials.api_provider('mineru', 'mineru.net').optional() is None
    assert calls == []
    assert credentials.status()['openalex'] is True


def test_file_institution_requires_an_explicit_credential_file_reference(tmp_path):
    credentials = manager(tmp_path)
    profile = {'id':'campus','credential_ref':'ieee_profiles:campus','credential_host':'login.example.edu'}
    with pytest.raises(ValueError, match='file'):
        credentials.save_institution(profile, username='alice', password='secret')


@pytest.mark.parametrize('configuration', [
    '# local configuration\n[credentials] # keep section comment\nbackend = "dpapi" # backend note\nmode = "manual"\n[display]\ntheme = "dark"\n',
    'credentials={backend="dpapi", mode="manual"} # inline note\n[display]\ntheme = "dark"\n',
    'credentials.backend = "dpapi"\ncredentials.mode = "manual"\n[display]\ntheme = "dark"\n',
])
def test_migration_updates_valid_toml_forms_and_preserves_other_configuration(tmp_path, configuration):
    import tomllib
    paths = AppPaths.for_root(tmp_path)
    paths.config.mkdir()
    settings = paths.config_paths.settings
    settings.write_text(configuration, encoding='utf-8')
    expected = tomllib.loads(configuration)
    expected['credentials']['backend'] = 'file'
    credentials = fc.CredentialManager(paths, environ={})

    result = credentials.migrate_from_dpapi(lambda: {'api': {'openalex': 'synthetic-key'}})

    assert result['status'] == 'migrated'
    updated = settings.read_text(encoding='utf-8')
    assert tomllib.loads(updated) == expected
    assert updated == configuration.replace('"dpapi"', '"file"')
    assert manager(tmp_path).api_provider('openalex', 'api.openalex.org')() == 'synthetic-key'


def test_migration_rejects_invalid_configuration_before_replacing_settings(tmp_path):
    credentials = manager(tmp_path)
    settings = credentials.config.settings
    settings.parent.mkdir()
    invalid = '[credentials] # malformed external edit\nbackend = "dpapi"\n[credentials]\n'
    settings.write_text(invalid, encoding='utf-8')

    with pytest.raises(ValueError, match='configuration'):
        credentials.migrate_from_dpapi(lambda: {'api': {}})

    assert settings.read_text(encoding='utf-8') == invalid


def test_migration_runs_profile_callback_before_switching_backend(tmp_path):
    paths = AppPaths.for_root(tmp_path)
    paths.secrets.mkdir(parents=True)
    (paths.secrets / 'secrets.clixml').write_bytes(b'synthetic-encrypted')
    credentials = fc.CredentialManager(paths, environ={})
    seen = []
    def copy_profiles():
        seen.append(manager(tmp_path).backend)
        assert fc.FileCredentialStore(credentials.env_file).snapshot()['OPENALEX_API_KEY'] == 'test'

    credentials.migrate_from_dpapi(lambda: {'api': {'openalex': 'test'}}, before_switch=copy_profiles)

    assert seen == ['dpapi']
    assert manager(tmp_path).backend == 'file'


def test_migration_callback_failure_leaves_legacy_backend_authoritative(tmp_path):
    paths = AppPaths.for_root(tmp_path)
    paths.secrets.mkdir(parents=True)
    (paths.secrets / 'secrets.clixml').write_bytes(b'synthetic-encrypted')
    credentials = fc.CredentialManager(paths, environ={})
    def copy_profiles():
        raise OSError('synthetic-profile-write-failure')

    with pytest.raises(OSError):
        credentials.migrate_from_dpapi(lambda: {'api': {'openalex': 'test'}}, before_switch=copy_profiles)

    assert credentials.backend == manager(tmp_path).backend == 'dpapi'
