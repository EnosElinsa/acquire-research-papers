from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path

import pytest

from acquire_research_papers import jobs
from acquire_research_papers.cli import run_cli

SOURCE = Path(__file__).resolve().parents[2] / "src"


def test_a_background_command_runs_in_its_own_process_and_reports_its_result(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("ARP_CONFIG_ROOT", str(tmp_path / "config"))
    monkeypatch.setenv("ARP_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(
        filter(None, (str(SOURCE), os.environ.get("PYTHONPATH")))))
    job = tmp_path / "job"
    argv = ["fetch", "--input", "not a reference", "--output", str(tmp_path / "out")]

    started = jobs.start(job, "fetch", argv)
    report = jobs.status(job, wait_seconds=90)

    assert started["status"] == "started"
    assert report["status"] == "finished", report
    assert report["exit_code"] == 64
    assert report["result"]["error_code"] == "invalid_input"
    assert json.loads((job / jobs.JOB_FILE).read_text())["command"] == argv


def test_stop_ends_the_command_like_ctrl_c_and_is_reported(tmp_path):
    job = tmp_path / "job"
    job.mkdir()
    (job / jobs.JOB_FILE).write_text(json.dumps(
        {"schema_version": 1, "command": ["manual-fetch"], "pid": os.getpid(), "started_at": "x"}))

    def runner(argv):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            time.sleep(0.05)
        pytest.fail("the stop request did not interrupt the command")

    threading.Timer(0.3, lambda: jobs.stop(job, alive=lambda pid: True)).start()
    code = jobs.run(job, ["manual-fetch"], runner=runner)

    assert code == 130
    report = jobs.status(job, alive=lambda pid: False)
    assert (report["status"], report["exit_code"]) == ("stopped", 130)


def test_a_vanished_process_without_an_exit_record_is_reported_as_crashed(tmp_path):
    job = tmp_path / "job"
    job.mkdir()
    (job / jobs.JOB_FILE).write_text(json.dumps(
        {"schema_version": 1, "command": ["acquire", "corpus"], "pid": 12345, "started_at": "x"}))
    (job / jobs.PROGRESS_FILE).write_text("first\n\nsecond\n", encoding="utf-8")

    running = jobs.status(job, alive=lambda pid: True)
    crashed = jobs.status(job, alive=lambda pid: False)

    assert running["status"] == "running"
    assert running["progress"] == ["first", "second"]
    assert crashed["status"] == "crashed"


def test_waiting_returns_as_soon_as_the_job_ends(tmp_path):
    job = tmp_path / "job"
    job.mkdir()
    (job / jobs.JOB_FILE).write_text(json.dumps(
        {"schema_version": 1, "command": ["discover"], "pid": 1, "started_at": "x"}))
    clock = {"now": 0.0}

    def sleeper(seconds):
        clock["now"] += seconds
        if clock["now"] >= 3:
            (job / jobs.OUTPUT_FILE).write_text('{"status": "review_required"}\n')
            (job / jobs.EXIT_FILE).write_text('{"exit_code": 0, "stop_requested": false}')

    report = jobs.status(job, wait_seconds=60, alive=lambda pid: True, sleeper=sleeper,
                         monotonic=lambda: clock["now"])
    assert report["status"] == "finished"
    assert report["result"] == {"status": "review_required"}
    assert clock["now"] == 3


def test_the_child_is_detached_from_the_calling_shell(tmp_path):
    calls = []

    class Process:
        pid = 4321

    def popen(command, **options):
        calls.append((command, options))
        return Process()

    started = jobs.start(tmp_path / "job", "acquire", ["acquire", "corpus"], popen=popen,
                         executable="python")

    command, options = calls[-1]
    assert command[:7] == ["python", "-m", "acquire_research_papers", "job", "run", "--job",
                           str((tmp_path / "job").resolve())]
    assert command[7:] == ["--", "acquire", "corpus"]
    assert options["stdin"] == subprocess.DEVNULL
    assert options["env"]["PYTHONIOENCODING"] == "utf-8"
    if os.name == "nt":
        assert options["creationflags"] & subprocess.DETACHED_PROCESS
    else:
        assert options["start_new_session"] is True
    assert started["pid"] == 4321


def test_background_rejects_interactive_commands_and_reused_directories(tmp_path, capsys):
    used = tmp_path / "used"
    used.mkdir()
    (used / "file").write_text("x")

    assert run_cli(["--background", str(tmp_path / "job"), "config", "status"]) == 64
    assert "--background runs only" in json.loads(capsys.readouterr().out)["message"]
    assert run_cli(["--background", str(used), "discover", "corpus", "--spec", "s.yaml",
                    "--output", str(tmp_path / "out")]) == 64
    assert "new or empty" in json.loads(capsys.readouterr().out)["message"]


def test_job_list_reports_indexed_jobs_newest_first_and_skips_removed_ones(tmp_path):
    index = tmp_path / "data" / jobs.INDEX_FILE

    class Process:
        pid = 777

    for name in ("old", "removed", "new"):
        jobs.start(tmp_path / name, "acquire", ["acquire", "corpus"], index=index,
                   popen=lambda command, **options: Process(), executable="python")
    (tmp_path / "old" / jobs.EXIT_FILE).write_text('{"exit_code": 0, "stop_requested": false}')
    (tmp_path / "old" / jobs.OUTPUT_FILE).write_text('{"status": "delivered"}\n')
    for path in (tmp_path / "removed").iterdir():
        path.unlink()
    (tmp_path / "removed").rmdir()

    listed = jobs.list_jobs(index, alive=lambda pid: True)

    assert [Path(job["job"]).name for job in listed["jobs"]] == ["new", "old"]
    assert [job["status"] for job in listed["jobs"]] == ["running", "finished"]
    assert listed["jobs"][1]["result_status"] == "delivered"
    assert listed["running"] == 1


def test_the_background_option_is_removed_from_the_child_command():
    assert jobs.strip_background_option(
        ["--background", "j", "acquire", "corpus", "--output", "o"]) == [
        "acquire", "corpus", "--output", "o"]
    assert jobs.strip_background_option(["--background=j", "fetch", "--input", "x"]) == [
        "fetch", "--input", "x"]


def test_force_stop_kills_the_process_and_records_the_request(tmp_path):
    job = tmp_path / "job"
    job.mkdir()
    (job / jobs.JOB_FILE).write_text(json.dumps(
        {"schema_version": 1, "command": ["fetch"], "pid": 999999, "started_at": "x"}))
    killed = []
    result = jobs.stop(job, force=True, alive=lambda pid: True, kill=killed.append)
    assert result["status"] == "killed"
    assert killed == [999999]
    assert (job / jobs.STOP_FILE).exists()
