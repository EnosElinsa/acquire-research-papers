from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[2]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


@pytest.mark.parametrize(("host", "folder"), [
    ("codex", ".agents"), ("claude-code", ".claude"),
    ("kiro-ide", ".kiro"), ("kiro-cli", ".kiro"),
])
def test_installer_selects_user_host_directory_without_overwriting(tmp_path, monkeypatch, capsys,
                                                                  host, folder):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    builder = module("build_distribution")
    wheel = tmp_path / "acquire_research_papers-0.6.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("acquire_research_papers-0.6.0.dist-info/METADATA",
                         "Metadata-Version: 2.3\nName: acquire-research-papers\nVersion: 0.6.0\n")
    source = Path(builder.build(ROOT, tmp_path / "build", wheel=wheel)["skill"])
    installer = module("install_skill")
    assert installer.main(["--source", str(source), "--host", host]) == 0
    result = json.loads(capsys.readouterr().out)
    target = tmp_path / "home" / folder / "skills" / "acquire-research-papers"
    assert Path(result["target"]) == target
    assert (target / "SKILL.md").read_bytes() == (source / "SKILL.md").read_bytes()
    with pytest.raises(SystemExit) as failure:
        installer.main(["--source", str(source), "--host", host])
    assert failure.value.code == 1
    assert (target / "SKILL.md").read_bytes() == (source / "SKILL.md").read_bytes()
