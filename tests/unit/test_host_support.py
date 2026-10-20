from __future__ import annotations

import argparse
import json
import subprocess

import pytest


def subject():
    from acquire_research_papers import host_support
    return host_support


def arguments(*values):
    parser = argparse.ArgumentParser()
    subject().register(parser.add_subparsers(dest="command", required=True))
    return parser.parse_args(values)


def skill(tmp_path):
    root = tmp_path / "skill"
    (root / "scripts").mkdir(parents=True)
    (root / "SKILL.md").write_text("---\nname: acquire-research-papers\n---\n")
    (root / "scripts" / "arp.py").write_text("")
    (root / "runtime.json").write_text(json.dumps({
        "schema_version": 1, "package": "acquire-research-papers", "version": "0.5.0",
        "wheel": {"sha256": "a" * 64},
    }))
    return root


@pytest.mark.parametrize(("host", "relative"), [
    ("codex", ".agents/skills/acquire-research-papers"),
    ("claude-code", ".claude/skills/acquire-research-papers"),
    ("kiro-ide", ".kiro/skills/acquire-research-papers"),
    ("kiro-cli", ".kiro/skills/acquire-research-papers"),
])
def test_host_paths_resolve_user_and_project_installations(tmp_path, host, relative):
    assert subject().skill_directory(host, home=tmp_path) == tmp_path / relative
    assert subject().skill_directory(host, project_root=tmp_path) == tmp_path / relative


def test_doctor_is_local_and_does_not_claim_host_load_or_entitlement(tmp_path, monkeypatch):
    module = subject()
    monkeypatch.setenv("ARP_CONFIG_ROOT", str(tmp_path / "config"))
    monkeypatch.setenv("ARP_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setattr(module, "urlopen", lambda *a, **k: pytest.fail("unexpected network"))
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **k: pytest.fail("unexpected process"))
    monkeypatch.setattr(module.platform, "uname", lambda: pytest.fail("process-capable platform API"))
    report = module.dispatch(arguments("doctor", "--host", "kiro-cli", "--skill-directory",
                                       str(skill(tmp_path))))
    assert report["skill"]["status"] == "present"
    assert report["runtime"]["version"] == "0.5.0"
    assert report["platform"]["system"]
    assert report["platform"]["release"]
    assert report["schemas"]["status"] == "valid"
    assert report["remote"]["status"] == "unknown"
    assert report["institution_access"]["status"] == "unverified"
    assert report["host_load"]["status"] == "unverified"
    assert not (tmp_path / "config").exists()


def test_doctor_reports_config_presence_without_secret_values(tmp_path, monkeypatch):
    monkeypatch.setenv("ARP_CONFIG_ROOT", str(tmp_path / "config"))
    monkeypatch.setenv("ARP_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
    config = tmp_path / "config"
    config.mkdir()
    (config / ".env").write_text("SEMANTIC_SCHOLAR_API_KEY=private-sentinel\nOPENALEX_API_KEY=\n")
    report = subject().dispatch(arguments("doctor", "--host", "codex", "--skill-directory",
                                          str(skill(tmp_path))))
    assert report["configuration"]["api_keys"]["semantic_scholar"] is True
    assert report["configuration"]["api_keys"]["openalex"] is False
    assert "private-sentinel" not in json.dumps(report)
    assert report["remote"]["status"] == "unknown"


def test_doctor_checks_executable_version_only_when_requested(tmp_path, monkeypatch):
    module = subject()
    monkeypatch.setenv("ARP_CONFIG_ROOT", str(tmp_path / "config"))
    monkeypatch.setenv("ARP_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setattr(module.shutil, "which", lambda name: "/tools/" + name)
    def version(command, **kwargs):
        assert command == ["/tools/claude", "--version"]
        assert kwargs["timeout"] == 10
        return subprocess.CompletedProcess(command, 0, "Claude Code 1.2.3\n", "")
    monkeypatch.setattr(module.subprocess, "run", version)
    report = module.dispatch(arguments("doctor", "--host", "claude-code", "--skill-directory",
                                       str(skill(tmp_path)), "--check-host-version"))
    assert report["host_executable"]["version"] == "Claude Code 1.2.3"
    assert report["host_load"]["status"] == "unverified"


def test_doctor_missing_skill_is_actionable_and_never_bootstraps(tmp_path, monkeypatch):
    monkeypatch.setenv("ARP_CONFIG_ROOT", str(tmp_path / "config"))
    monkeypatch.setenv("ARP_DATA_ROOT", str(tmp_path / "data"))
    report = subject().dispatch(arguments("doctor", "--host", "kiro-ide", "--skill-directory",
                                          str(tmp_path / "absent")))
    assert report["status"] == "attention_required"
    assert report["skill"]["status"] == "missing"
    assert report["next_actions"]
    assert not (tmp_path / "absent").exists()


def test_doctor_remote_probe_requires_opt_in_and_has_no_credentials(tmp_path, monkeypatch):
    module = subject()
    monkeypatch.setenv("ARP_CONFIG_ROOT", str(tmp_path / "config"))
    monkeypatch.setenv("ARP_DATA_ROOT", str(tmp_path / "data"))
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): return False
    def request(value, *, timeout):
        assert value.full_url == "https://api.crossref.org/works?rows=0"
        assert value.get_header("Authorization") is None
        assert timeout == 10
        return Response()
    monkeypatch.setattr(module, "urlopen", request)
    report = module.dispatch(arguments("doctor", "--host", "codex", "--skill-directory",
                                       str(skill(tmp_path)), "--remote-check"))
    assert report["remote"]["status"] == "reachable"
    assert report["institution_access"]["status"] == "unverified"


def test_doctor_checks_the_explicitly_selected_env_file(tmp_path, monkeypatch):
    monkeypatch.setenv("ARP_CONFIG_ROOT", str(tmp_path / "config"))
    monkeypatch.setenv("ARP_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    selected = tmp_path / "selected.env"
    selected.write_text("OPENALEX_API_KEY=selected-private-value\n")
    args = arguments("doctor", "--host", "codex", "--skill-directory", str(skill(tmp_path)))
    args.env_file = selected
    report = subject().dispatch(args)
    assert report["configuration"]["api_keys"]["openalex"] is True
    assert report["configuration"]["env_file"] == str(selected.resolve())
    assert "selected-private-value" not in json.dumps(report)


def test_failed_remote_check_does_not_expose_exception_values(tmp_path, monkeypatch):
    monkeypatch.setenv("ARP_CONFIG_ROOT", str(tmp_path / "config"))
    monkeypatch.setenv("ARP_DATA_ROOT", str(tmp_path / "data"))
    def failure(*args, **kwargs):
        raise OSError("secret-sentinel https://private.example/?token=hidden")
    monkeypatch.setattr(subject(), "urlopen", failure)
    report = subject().dispatch(arguments("doctor", "--host", "codex", "--skill-directory",
                                          str(skill(tmp_path)), "--remote-check"))
    assert report["remote"]["status"] == "unavailable"
    assert "secret-sentinel" not in json.dumps(report)
    assert "private.example" not in json.dumps(report)
