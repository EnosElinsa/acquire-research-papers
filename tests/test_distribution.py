from __future__ import annotations

import hashlib
import importlib.util
import json
import tomllib
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT/'skills'/'acquire-research-papers'


def module(path):
    spec = importlib.util.spec_from_file_location('distribution_subject', path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def wheel(path):
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('acquire_research_papers-0.4.0.dist-info/METADATA',
                         'Metadata-Version: 2.3\nName: acquire-research-papers\nVersion: 0.4.0\n')
    return path


def test_one_canonical_nested_skill_entrypoint():
    assert (SKILL/'SKILL.md').is_file()
    assert not (ROOT/'SKILL.md').exists()
    assert (SKILL/'scripts'/'arp.py').is_file()
    assert not (SKILL/'pyproject.toml').exists()
    assert not (SKILL/'.git').exists()


def test_launcher_rejects_local_wheel_digest_before_running_uv(tmp_path, monkeypatch):
    launcher = module(SKILL/'scripts'/'arp.py')
    manifest = {'schema_version':1,'package':'acquire-research-papers','version':'0.4.0',
        'wheel':{'url':'https://github.com/EnosElinsa/acquire-research-papers/releases/download/v0.4.0/acquire_research_papers-0.4.0-py3-none-any.whl',
                 'sha256':'a'*64}}
    path = tmp_path/'release.json'
    path.write_text(json.dumps(manifest))
    local = tmp_path/'wrong.whl'
    local.write_bytes(b'wrong')
    monkeypatch.setenv('ARP_LOCAL_WHEEL', str(local))
    monkeypatch.setenv('ARP_RUNTIME_ROOT', str(tmp_path/'runtime'))
    with pytest.raises(ValueError, match='SHA-256'):
        launcher.prepare_runtime(path)
    assert not list((tmp_path/'runtime').rglob('installed.json'))


def test_builder_exports_only_allowlisted_assets_and_matching_digest(tmp_path):
    builder = module(ROOT/'scripts'/'build_distribution.py')
    local = wheel(tmp_path/'acquire_research_papers-0.4.0-py3-none-any.whl')
    result = builder.build(ROOT, tmp_path/'output', wheel=local)
    exported = Path(result['skill'])
    manifest = json.loads((exported/'runtime.json').read_text())
    assert manifest['wheel']['sha256'] == hashlib.sha256(local.read_bytes()).hexdigest()
    assert not (exported/'src').exists()
    assert not (exported/'pyproject.toml').exists()
    assert not (exported/'scripts'/'validate_skill.py').exists()
    assert not (exported/'scripts'/'secret-store.ps1').exists()
    with zipfile.ZipFile(result['zip']) as archive:
        names = archive.namelist()
    assert 'acquire-research-papers/SKILL.md' in names
    assert all('.git' not in Path(name).parts for name in names)
    assert set(builder.SKILL_FILES) == {p.relative_to(exported).as_posix()
                                     for p in exported.rglob('*') if p.is_file()}


def test_builder_refuses_git_or_source_skill_destinations(tmp_path):
    builder = module(ROOT/'scripts'/'build_distribution.py')
    local = wheel(tmp_path/'acquire_research_papers-0.4.0-py3-none-any.whl')
    with pytest.raises(ValueError, match='git'):
        builder.build(ROOT, tmp_path/'.git'/'export', wheel=local)
    with pytest.raises(ValueError, match='source'):
        builder.build(ROOT, SKILL, wheel=local)


def test_wheel_scripts_are_explicit_and_exclude_developer_tools():
    data = tomllib.loads((ROOT/'pyproject.toml').read_text())
    included = data['tool']['hatch']['build']['targets']['wheel']['force-include']
    assert 'scripts' not in included
    assert included['scripts/setup-ieee-profile-credential.ps1'].endswith('/setup-ieee-profile-credential.ps1')
    assert 'scripts/build_distribution.py' not in included
    assert 'scripts/validate_skill.py' not in included


def test_safe_copy_installer_refuses_git_and_preserves_clean_previous_skill(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT/'scripts'))
    builder = module(ROOT/'scripts'/'build_distribution.py')
    local = wheel(tmp_path/'acquire_research_papers-0.4.0-py3-none-any.whl')
    source = Path(builder.build(ROOT,tmp_path/'build',wheel=local)['skill'])
    installer = module(ROOT/'scripts'/'install_skill.py')
    checkout = tmp_path/'checkout'
    (checkout/'.git').mkdir(parents=True)
    marker = checkout/'keep.txt'
    marker.write_text('developer checkout')
    with pytest.raises(ValueError,match='git'):
        installer.install(source,checkout,replace=True)
    with pytest.raises(ValueError,match='git'):
        installer.install(source,checkout/'skills'/'installed')
    assert marker.read_text() == 'developer checkout'
    target = tmp_path/'installed'
    assert installer.install(source,target)['status'] == 'installed'
    with pytest.raises(ValueError,match='replace'):
        installer.install(source,target)
    result = installer.install(source,target,replace=True)
    assert Path(result['backup']).is_dir()
    assert (target/'SKILL.md').is_file()


def test_builder_rejects_empty_git_directory_and_git_file_in_target(tmp_path):
    builder = module(ROOT/'scripts'/'build_distribution.py')
    local = wheel(tmp_path/'acquire_research_papers-0.4.0-py3-none-any.whl')
    directory = tmp_path/'directory'
    (directory/'skills'/'acquire-research-papers'/'.git').mkdir(parents=True)
    with pytest.raises(ValueError,match='git'):
        builder.build(ROOT,directory,wheel=local)
    worktree = tmp_path/'worktree'
    worktree.mkdir()
    (worktree/'.git').write_text('gitdir: somewhere')
    with pytest.raises(ValueError,match='git'):
        builder.build(ROOT,worktree,wheel=local)
