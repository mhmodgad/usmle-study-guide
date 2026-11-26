"""Regression tests for the version history (journal, undo/redo, checkpoints)."""
import sqlite3

from conftest import snapshot
from tempu import db as dbmod
from tempu import history as H


def _html(c, t):
    return c.get(f"/api/topics/{t}/content").get_json()["html"]


def test_checkpoint_after_autosave_is_respected(env):
    """An autosave right after a checkpoint used to merge into the changeset from
    BEFORE the checkpoint, so restoring the checkpoint did not undo it."""
    c, t = env["client"], env["ids"]["topics"][0]
    c.put(f"/api/topics/{t}/content", json={"html": "<p>before checkpoint</p>", "checkpoint": True, "session": "s"})
    cp = c.post("/api/history/checkpoints", json={"name": "cp"}).get_json()["id"]
    c.put(f"/api/topics/{t}/content", json={"html": "<p>after checkpoint</p>", "session": "s"})
    c.post(f"/api/history/checkpoints/{cp}/restore")
    assert "before checkpoint" in _html(c, t)


def test_restore_checkpoint_does_not_bring_back_undone_changes(env):
    """Change A, undo A, restore a checkpoint taken before A: A must stay gone."""
    c, ids, db = env["client"], env["ids"], env["db"]
    cp = c.post("/api/history/checkpoints", json={"name": "cp"}).get_json()["id"]
    at_cp = snapshot(db)
    a = c.patch(f"/api/structure/section/{ids['sections'][0]}", json={"title": "A"}).get_json()
    c.post(f"/api/history/undo/{a['changeset']['id']}")
    assert snapshot(db) == at_cp
    c.post(f"/api/history/checkpoints/{cp}/restore")
    assert snapshot(db) == at_cp
    # and undoing the restore gives back exactly what was there before it
    c.post("/api/history/undo/latest")
    assert snapshot(db) == at_cp
    lst = c.get("/api/history/checkpoints").get_json()
    assert lst[0]["changes_since"] == 0


def test_checkpoint_count_is_zero_right_after_restoring_it(env):
    c, ids = env["client"], env["ids"]
    cp = c.post("/api/history/checkpoints", json={"name": "cp"}).get_json()["id"]
    c.patch(f"/api/structure/section/{ids['sections'][0]}", json={"title": "A"})
    c.patch(f"/api/structure/section/{ids['sections'][1]}", json={"title": "B"})
    assert c.get("/api/history/checkpoints").get_json()[0]["changes_since"] == 2
    c.post(f"/api/history/checkpoints/{cp}/restore")
    assert c.get("/api/history/checkpoints").get_json()[0]["changes_since"] == 0


def test_redo_one_change_after_a_restore_brings_back_only_that_change(env):
    c, ids, db = env["client"], env["ids"], env["db"]
    s0, s1 = ids["sections"][0], ids["sections"][1]
    cp = c.post("/api/history/checkpoints", json={"name": "cp"}).get_json()["id"]
    a = c.patch(f"/api/structure/section/{s0}", json={"title": "A"}).get_json()["changeset"]["id"]
    c.patch(f"/api/structure/section/{s1}", json={"title": "B"})
    c.post(f"/api/history/checkpoints/{cp}/restore")
    r = c.post(f"/api/history/redo/{a}")
    assert r.status_code == 200, r.get_json()
    titles = {r[0]: r[2] for r in snapshot(db)["sections"]}
    assert titles[s0] == "A" and titles[s1] == "Section 0.1"
    rows = {x["id"]: x for x in c.get("/api/history/changesets").get_json()}
    assert rows[a]["undone"] is False
    c.post("/api/history/undo/latest")                    # undo that redo
    titles = {r[0]: r[2] for r in snapshot(db)["sections"]}
    assert titles[s0] == "Section 0.0"
    rows = {x["id"]: x for x in c.get("/api/history/changesets").get_json()}
    assert rows[a]["undone"] is True


def test_long_editing_session_keeps_intermediate_versions(env, monkeypatch):
    """Autosaves merge, but one session no longer swallows hours of work into one version."""
    c, t = env["client"], env["ids"]["topics"][0]
    clock = [1_800_000_000.0]
    monkeypatch.setattr(H.time, "time", lambda: clock[0])
    real_now = H._now
    import datetime as dt
    monkeypatch.setattr(H, "_now", lambda: dt.datetime.fromtimestamp(clock[0], dt.timezone.utc).isoformat().replace("+00:00", "Z"))
    ids = set()
    for i in range(40):                                   # a save every 60 s for 40 minutes
        r = c.put(f"/api/topics/{t}/content", json={"html": f"<p>v{i}</p>", "session": "s"}).get_json()
        ids.add(r["changeset"]["id"])
        clock[0] += 60
    assert 3 <= len(ids) <= 6, len(ids)                   # ~one version per 10 minutes
    monkeypatch.setattr(H, "_now", real_now)


def test_autosaves_do_not_leave_orphan_text_copies(env):
    c, t, db = env["client"], env["ids"]["topics"][0], env["db"]
    big = "<p>" + ("lorem ipsum dolor sit amet " * 200) + "%d</p>"
    for i in range(15):
        c.put(f"/api/topics/{t}/content", json={"html": big % i, "session": "s"})
    conn = dbmod.connect(db, journal=False)
    orphans = conn.execute(
        "SELECT COUNT(*) FROM doc_texts WHERE '@'||hash NOT IN "
        "(SELECT before FROM revisions WHERE before LIKE '@%' UNION SELECT after FROM revisions WHERE after LIKE '@%')"
    ).fetchone()[0]
    conn.close()
    assert orphans == 0


def test_nested_change_records_into_the_outer_one(env):
    conn = dbmod.connect(env["db"])
    sid = env["ids"]["sections"][0]
    with H.Change(conn, "outer", kind="structure") as outer:
        conn.execute("UPDATE sections SET title='X' WHERE id=?", (sid,))
        with H.Change(conn, "inner", kind="structure"):
            conn.execute("UPDATE sections SET title='Y' WHERE id=?", (sid,))
        conn.execute("UPDATE sections SET title='Z' WHERE id=?", (sid,))
    n = conn.execute("SELECT COUNT(*) FROM changesets").fetchone()[0]
    assert n == 1 and outer.id
    H.undo(conn, outer.id)
    assert conn.execute("SELECT title FROM sections WHERE id=?", (sid,)).fetchone()[0] == "Section 0.0"
    conn.close()
