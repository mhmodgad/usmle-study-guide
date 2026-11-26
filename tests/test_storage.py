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
