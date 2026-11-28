import io
import os
import shutil
import sqlite3

import pytest

from conftest import build_tiny, snapshot
from tempu import backup as B, db as dbmod, migrate

PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082")


def test_migration_from_single_file(tmp_path):
    data = str(tmp_path / "data")
    ids = build_tiny(data, legacy=True)
    os.makedirs(os.path.join(data, "uploads"))
    with open(os.path.join(data, "uploads", "a.png"), "wb") as f:
        f.write(PNG)
    c = sqlite3.connect(os.path.join(data, "tempu.db"))
    t = ids["topics"][0]
    c.execute("INSERT INTO topic_edit_history(topic_id,html,title,saved_at) VALUES(?,?,NULL,'2026-01-01T00:00:00Z')",
              (t, "<p>Original text 000 words here</p>"))
    c.execute("INSERT INTO topic_edits(topic_id,html,title,plain_text,base_version,updated_at) VALUES(?,?,?,?,1,?)",
              (t, '<p>mine <img src="/uploads/a.png"></p>', "Mine", "mine", "2026-01-02T00:00:00Z"))
    c.execute("INSERT INTO struct_overrides(kind,id,title,icon_path) VALUES('section',?,?,?)",
              (ids["sections"][0], "Renamed", "/uploads/a.png"))
    c.execute("INSERT INTO progress(topic_id,completed) VALUES(?,1)", (t,))
    c.commit(); c.close()

    assert migrate.ensure(data, quiet=True) is True
    assert sorted(os.listdir(data)) == ["base.db", "blobs", "tempu.db.pre-migration", "uploads.migrated", "user.db"]
    conn = dbmod.connect(os.path.join(data, "user.db"))
    html = conn.execute("SELECT html FROM topic_edits").fetchone()[0]
    assert "/blobs/" in html and "/uploads/" not in html
    assert conn.execute("SELECT icon_path FROM struct_overrides").fetchone()[0].startswith("/blobs/")
    assert conn.execute("SELECT COUNT(*) FROM progress").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0] == len(ids["topics"])
    labels = [r[0] for r in conn.execute("SELECT label FROM changesets ORDER BY id")]
    assert "Edited 'Mine' (imported)" in labels and any(l.startswith('Structure changes made before') for l in labels)
    base_tables = {r[0] for r in conn.execute("SELECT name FROM base.sqlite_master WHERE type='table'")}
    assert "progress" not in base_tables and "topics" in base_tables
    conn.close()
    assert migrate.ensure(data, quiet=True) is False            # runs once


def test_blob_store_dedupes_and_serves(env):
    c = env["client"]
    a = c.post("/api/uploads", data={"file": (io.BytesIO(PNG), "x.png")}, content_type="multipart/form-data").get_json()
    b = c.post("/api/uploads", data={"file": (io.BytesIO(PNG), "y.png")}, content_type="multipart/form-data").get_json()
    assert a["url"] == b["url"] and a["url"].startswith("/blobs/")
    r = c.get(a["url"])
    assert r.status_code == 200 and r.data == PNG and "immutable" in r.headers["Cache-Control"]


def test_retention_keeps_recent_daily_monthly():
    import datetime as dt
    now = dt.datetime(2026, 11, 26, 12, tzinfo=dt.timezone.utc)
    names = [f"user-202611{d:02d}T{h:02d}0000Z.db.gz" for d in range(1, 27) for h in (8, 20)] + \
            ["user-20260115T000000Z.db.gz", "user-20250101T000000Z.db.gz"]
    keep = B.keep_set(names, keep_recent=3, keep_daily=7, keep_monthly=12, now=now)
    assert "user-20261126T200000Z.db.gz" in keep and "user-20260115T000000Z.db.gz" in keep
    assert "user-20261101T080000Z.db.gz" not in keep
    assert "user-20250101T000000Z.db.gz" not in keep              # older than 12 months


@pytest.mark.skipif(not shutil.which("rclone"), reason="rclone not installed")
def test_backup_and_selective_restore(env, tmp_path):
    db, c = env["db"], env["client"]
    ids = env["ids"]
    up = c.post("/api/uploads", data={"file": (io.BytesIO(PNG), "x.png")}, content_type="multipart/form-data").get_json()
    c.put(f"/api/topics/{ids['topics'][0]}/content", json={"html": f'<p>edited <img src="{up["url"]}"></p>', "checkpoint": True})
    c.post("/api/progress/topic", json={"topic_id": ids["topics"][0], "completed": True})
    remote = str(tmp_path / "remote" / "tempu-backup")
    conn = dbmod.connect(db)
    B.save_config(conn, {"enabled": True, "remote": remote, "categories": {"flashcards": False}})
    conn.close()
    res = B.run(db)
    assert res["ok"] == 1, res
    assert os.path.isfile(os.path.join(remote, "manifest.json"))
    assert os.listdir(os.path.join(remote, "blobs"))

    # lose the edit and progress locally, restore only the edits
    conn = dbmod.connect(db, journal=False)
    conn.execute("DELETE FROM topic_edits"); conn.execute("DELETE FROM progress"); conn.commit(); conn.close()
    shutil.rmtree(os.path.join(env["data"], "blobs"))
    out = B.restore(db, None, only=["edits", "files"], rebuild=False)
    assert out["ok"], out
    conn = dbmod.connect(db, journal=False)
    assert conn.execute("SELECT COUNT(*) FROM topic_edits").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM progress").fetchone()[0] == 0      # not chosen: untouched
    conn.close()
    assert c.get(up["url"]).status_code == 200                                    # file downloaded again


def test_backup_off_does_nothing(env):
    conn = dbmod.connect(env["db"])
    cfg = B.get_config(conn)
    assert cfg["enabled"] is False
    assert B._due(conn, env["db"], cfg) is False
    conn.close()
    assert B.run(env["db"])["ok"] == 0


@pytest.mark.skipif(not shutil.which("rclone"), reason="rclone not installed")
def test_finished_backup_is_not_pending_again(env, tmp_path):
    """Regression: the backup's own writes (log row, upload stamps, settings) made
    every backup look 'pending' again, so it re-ran every 10 minutes forever."""
    db, c, ids = env["db"], env["client"], env["ids"]
    c.post("/api/progress/topic", json={"topic_id": ids["topics"][0], "completed": True})
    remote = str(tmp_path / "remote" / "tempu-backup")
    conn = dbmod.connect(db, journal=False)
    B.save_config(conn, {"enabled": True, "remote": remote})
    conn.close()
    assert B.run(db)["ok"] == 1
    conn = dbmod.connect(db, journal=False)
    has, n, files = B.pending(conn, db)
    assert (has, files) == (False, 0)
    assert B.status(conn, db)["state"] == "ok"
    assert B._due(conn, db, B.get_config(conn)) is False
    B.save_config(conn, {"keep_recent": 5})             # changing backup settings is not "your data"
    assert B.pending(conn, db)[0] is False
    conn.close()
    c.post("/api/progress/topic", json={"topic_id": ids["topics"][1], "completed": True})   # real change
    conn = dbmod.connect(db, journal=False)
    assert B.pending(conn, db)[0] is True
    assert B.status(conn, db)["state"] == "pending"
    assert B._due(conn, db, B.get_config(conn)) is False   # quiet period after a change
    conn.close()
    # one listing call, details on demand
    d = c.get("/api/backup/snapshots").get_json()
    assert d["ok"] and len(d["snapshots"]) == 1 and d["snapshots"][0]["bytes"] > 0
    info = c.get("/api/backup/snapshots/" + d["snapshots"][0]["name"]).get_json()
    assert info["ok"] and "study" in info["categories"]
    assert c.get("/api/backup/snapshots/..%2Fsecret").status_code in (400, 404)


def test_back_up_now_without_a_place_logs_nothing(env):
    c = env["client"]
    r = c.post("/api/backup/run")
    assert r.status_code == 400
    conn = dbmod.connect(env["db"], journal=False)
    assert conn.execute("SELECT COUNT(*) FROM backup_log").fetchone()[0] == 0
    assert B.status(conn, env["db"])["state"] == "off"
    conn.close()
    assert B.run(env["db"], force=True)["ok"] == 0          # direct call: refused, not logged as a failure
    conn = dbmod.connect(env["db"], journal=False)
    assert conn.execute("SELECT COUNT(*) FROM backup_log").fetchone()[0] == 0
    conn.close()


def test_connect_status_expires_and_restore_waits_for_backup(env, monkeypatch):
    B._set_connect(state="error", message="boom")
    assert B.connect_status()["state"] == "error"
    monkeypatch.setattr(B, "CONNECT_STALE_SECONDS", -1)
    assert B.connect_status()["state"] == "idle"
    assert B._RUN_LOCK.acquire(blocking=False)
    try:
        assert B.restore(env["db"], "x")["ok"] is False      # never overlaps a running backup
    finally:
        B._RUN_LOCK.release()


PNG2 = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
        b"\x00\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04\x00\x01\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82")


@pytest.mark.skipif(not shutil.which("rclone"), reason="rclone not installed")
def test_files_off_or_missing_never_keep_backup_pending(env, tmp_path):
    """With 'Files you added' unticked (or a file gone from disk), files that are
    never uploaded used to keep the backup 'pending' and re-running forever."""
    db, c = env["db"], env["client"]
    up = c.post("/api/uploads", data={"file": (io.BytesIO(PNG2), "y.png")}, content_type="multipart/form-data").get_json()
    remote = str(tmp_path / "remote" / "tempu-backup")
    conn = dbmod.connect(db, journal=False)
    B.save_config(conn, {"enabled": True, "remote": remote, "categories": {"files": False}})
    conn.close()
    assert B.run(db)["ok"] == 1
    conn = dbmod.connect(db, journal=False)
    assert B.pending(conn, db)[0] is False and B.status(conn, db)["files_waiting"] == 0
    # files on again, but the file was deleted from disk meanwhile
    B.save_config(conn, {"categories": {"files": True}})
    conn.close()
    shutil.rmtree(os.path.join(env["data"], "blobs"))
    assert B.run(db)["ok"] == 1
    conn = dbmod.connect(db, journal=False)
    assert B.pending(conn, db)[0] is False, B.pending(conn, db)
    conn.close()


@pytest.mark.skipif(not shutil.which("rclone"), reason="rclone not installed")
def test_content_database_uploaded_only_when_it_changed(env, tmp_path, monkeypatch):
    db = env["db"]
    remote = str(tmp_path / "remote" / "tempu-backup")
    conn = dbmod.connect(db, journal=False)
    B.save_config(conn, {"enabled": True, "remote": remote, "categories": {"base": True}})
    conn.close()
    calls = []
    real = B._rclone
    monkeypatch.setattr(B, "_rclone", lambda cfg, *a, **k: (calls.append(a), real(cfg, *a, **k))[1])
    assert B.run(db, force=True)["ok"] == 1
    assert any(a[0] == "copyto" and a[-1].endswith("content/base.db") for a in calls)
    calls.clear()
    assert B.run(db, force=True)["ok"] == 1
    assert not any(a[0] == "copyto" and a[-1].endswith("content/base.db") for a in calls), calls


@pytest.mark.skipif(not shutil.which("rclone"), reason="rclone not installed")
def test_pruning_keeps_exactly_what_retention_says(env, tmp_path):
    import time
    db = env["db"]
    remote = str(tmp_path / "remote" / "tempu-backup")
    conn = dbmod.connect(db, journal=False)
    B.save_config(conn, {"enabled": True, "remote": remote, "keep_recent": 2, "keep_daily": 0, "keep_monthly": 0})
    cfg = B.get_config(conn)
    conn.close()
    for _ in range(4):
        assert B.run(db, force=True)["ok"] == 1
        time.sleep(1.1)                                   # snapshot names have 1-second resolution
    left = B.list_remote(cfg)
    assert len(left) == 2
    files = [f for _, _, fs in os.walk(os.path.join(remote, "snapshots")) for f in fs]
    assert sorted(f for f in files if f.endswith(".json")) == sorted(n[:-3] + ".json" for n in left)


@pytest.mark.skipif(not shutil.which("rclone"), reason="rclone not installed")
def test_restore_without_the_snapshot_info_never_wipes_what_was_not_backed_up(env, tmp_path):
    """The .json next to a snapshot says what it holds. Without it, every
    category was restored - and categories left out of the backup (empty in
    the file) wiped your local data, e.g. all your decks."""
    db, c, ids = env["db"], env["client"], env["ids"]
    c.post("/api/decks", json={"name": "Mine"})
    c.post("/api/progress/topic", json={"topic_id": ids["topics"][0], "completed": True})
    remote = str(tmp_path / "remote" / "tempu-backup")
    conn = dbmod.connect(db, journal=False)
    B.save_config(conn, {"enabled": True, "remote": remote, "categories": {"flashcards": False}})
    conn.close()
    assert B.run(db)["ok"] == 1
    for dp, _, fs in os.walk(os.path.join(remote, "snapshots")):
        for f in fs:
            if f.endswith(".json"):
                os.remove(os.path.join(dp, f))
    out = B.restore(db, None, None, rebuild=False)
    assert out["ok"], out
    assert "flashcards" in out["skipped"] and "study" in out["categories"]
    conn = dbmod.connect(db, journal=False)
    assert conn.execute("SELECT COUNT(*) FROM decks").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM progress").fetchone()[0] == 1
    conn.close()


@pytest.mark.skipif(not shutil.which("rclone"), reason="rclone not installed")
def test_restore_everything_when_you_never_added_a_file(env, tmp_path):
    """No files added = no blobs folder in the cloud; restoring with "Files you
    added" ticked (the default) used to fail the whole restore."""
    db, c, ids = env["db"], env["client"], env["ids"]
    c.post("/api/progress/topic", json={"topic_id": ids["topics"][0], "completed": True})
    remote = str(tmp_path / "remote" / "tempu-backup")
    conn = dbmod.connect(db, journal=False)
    B.save_config(conn, {"enabled": True, "remote": remote})
    conn.close()
    assert B.run(db)["ok"] == 1
    assert not os.path.exists(os.path.join(remote, "blobs"))
    out = B.restore(db, None, None, rebuild=False)
    assert out["ok"], out
