"""The launcher: data check after the update, and updates that a hand-edited
start script used to block."""
import os
import shutil
import sqlite3
import subprocess

import pytest

from tempu import launch

GIT = shutil.which("git")


def test_data_problem_accepts_current_and_legacy_layouts(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    assert "No library database" in launch.data_problem(str(d))

    # an empty base.db (e.g. left by an interrupted build) is not a library
    sqlite3.connect(d / "base.db").close()
    assert "empty or unreadable" in launch.data_problem(str(d))
    assert not (d / "base.db-wal").exists()            # the check never writes

    c = sqlite3.connect(d / "base.db")
    c.execute("CREATE TABLE topics(id TEXT)")
    c.execute("INSERT INTO topics VALUES('t')")
    c.commit()
    c.close()
    assert launch.data_problem(str(d)) is None

    (d / "base.db").unlink()
    (d / "tempu.db").write_bytes(b"")                  # old single-file layout: upgraded on start
    assert launch.data_problem(str(d)) is None


def test_launcher_scripts_do_not_check_the_database_themselves():
    """A database check in the .bat/.sh runs BEFORE the update, so a wrong one
    (data\\tempu.db after the switch to base.db) could never be fixed by an update."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for name in ("run-windows.bat", "run.sh"):
        text = open(os.path.join(root, name), encoding="utf-8").read()
        assert "tempu.db" not in text and "base.db" not in text, name
    bat = open(os.path.join(root, "run-windows.bat"), "rb").read()
    assert b"\r\n\r\n" not in bat and b"\r\r" not in bat


def _git(cwd, *args):
    subprocess.run([GIT, "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=cwd, check=True,
                   capture_output=True)


@pytest.mark.skipif(not GIT, reason="git not installed")
def test_update_replaces_a_hand_edited_start_script(tmp_path, monkeypatch):
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    _git(upstream, "init", "-q", "-b", "main")
    (upstream / "run-windows.bat").write_text("if not exist data\\tempu.db exit\n")
    (upstream / "app.py").write_text("v1\n")
    _git(upstream, "add", "-A")
    _git(upstream, "commit", "-qm", "v1")

    local = tmp_path / "local"
    _git(tmp_path, "clone", "-q", str(upstream), str(local))
    # the user's own workaround
    (local / "run-windows.bat").write_text("if not exist data\\base.db exit\n")

    (upstream / "run-windows.bat").write_text("REM fixed upstream\n")
    (upstream / "app.py").write_text("v2\n")
    _git(upstream, "commit", "-qam", "v2")

    monkeypatch.setattr(launch, "PROJECT", str(local))
    monkeypatch.setattr(launch, "REPO_URL", str(upstream))
    monkeypatch.delenv("TEMPU_NO_UPDATE", raising=False)
    assert launch.selfupdate(verbose=False) is True
    assert (local / "app.py").read_text() == "v2\n"
    assert (local / "run-windows.bat").read_text() == "REM fixed upstream\n"
    assert "base.db" in (local / "run-windows.bat.local-edit").read_text()


@pytest.mark.skipif(not GIT, reason="git not installed")
def test_update_still_refuses_to_overwrite_edits_to_app_code(tmp_path, monkeypatch):
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    _git(upstream, "init", "-q", "-b", "main")
    (upstream / "app.py").write_text("v1\n")
    _git(upstream, "add", "-A")
    _git(upstream, "commit", "-qm", "v1")
    local = tmp_path / "local"
    _git(tmp_path, "clone", "-q", str(upstream), str(local))
    (local / "app.py").write_text("mine\n")
    (upstream / "app.py").write_text("v2\n")
    _git(upstream, "commit", "-qam", "v2")

    monkeypatch.setattr(launch, "PROJECT", str(local))
    monkeypatch.setattr(launch, "REPO_URL", str(upstream))
    monkeypatch.delenv("TEMPU_NO_UPDATE", raising=False)
    assert launch.selfupdate(verbose=False) is False
    assert (local / "app.py").read_text() == "mine\n"


def test_second_start_opens_the_running_app_instead_of_failing(monkeypatch):
    import threading
    from werkzeug.serving import make_server
    from flask import Flask, redirect
    a = Flask("x")
    a.add_url_rule("/", "i", lambda: redirect("/dashboard"))
    srv = make_server("127.0.0.1", 0, a)
    port = srv.server_port
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        assert launch._is_this_app("http://127.0.0.1:%d/" % port) is True
        opened = []
        monkeypatch.setattr("webbrowser.open", opened.append)
        assert launch.main(["--no-update", "--port", str(port)]) == 0
        assert opened == ["http://127.0.0.1:%d/" % port]
    finally:
        srv.shutdown()
    assert launch._is_this_app("http://127.0.0.1:%d/" % port) is False
