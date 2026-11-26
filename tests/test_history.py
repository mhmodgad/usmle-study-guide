import random

from conftest import snapshot


def test_structure_change_has_undo_toast_payload(env):
    c, ids = env["client"], env["ids"]
    r = c.patch(f"/api/structure/section/{ids['sections'][0]}", json={"title": "Renamed"}).get_json()
    assert r["changeset"]["label"] == "Renamed section 'Section 0.0' to 'Renamed'"


def test_random_ops_undo_all_and_redo_all(env):
    c, ids, db = env["client"], env["ids"], env["db"]
    rnd = random.Random(42)
    start = snapshot(db)
    secs, tops = list(ids["sections"]), list(ids["topics"])
    made = 0
    for i in range(30):
        op = rnd.choice(["rename", "move", "delete", "create", "icon", "edit"])
        if op == "rename":
            r = c.patch(f"/api/structure/section/{rnd.choice(secs)}", json={"title": f"S{i}"})
        elif op == "move":
            r = c.patch(f"/api/structure/topic/{rnd.choice(tops)}", json={"parent_id": rnd.choice(secs), "index": 0})
        elif op == "delete":
            r = c.delete(f"/api/structure/topic/{rnd.choice(tops)}")
        elif op == "icon":
            r = c.patch(f"/api/structure/section/{rnd.choice(secs)}", json={"icon_path": "/assets/icons/x.webp"})
        elif op == "edit":
            r = c.put(f"/api/topics/{rnd.choice(tops)}/content", json={"html": f"<p>v{i}</p>", "checkpoint": True})
        else:
            r = c.post("/api/structure/section", json={"parent_id": ids["chapters"][0], "title": f"N{i}"})
            secs.append(r.get_json()["id"])
        if (r.get_json() or {}).get("changeset"):
            made += 1
    end = snapshot(db)
    for _ in range(made):
        assert c.post("/api/history/undo/latest", json={"force": True}).status_code == 200
    assert snapshot(db) == start
    for _ in range(made):
        assert c.post("/api/history/redo/latest", json={"force": True}).status_code == 200
    assert snapshot(db) == end


def test_delete_section_and_undo_brings_topics_back(env):
    c, ids, db = env["client"], env["ids"], env["db"]
    before = snapshot(db)
    r = c.delete(f"/api/structure/section/{ids['sections'][1]}").get_json()
    assert len(snapshot(db)["topics"]) == len(before["topics"]) - 3
    c.post(f"/api/history/undo/{r['changeset']['id']}")
    assert snapshot(db) == before


def test_autosaves_coalesce_and_versions_restore(env):
    c, ids = env["client"], env["ids"]
    t = ids["topics"][0]
    a = c.put(f"/api/topics/{t}/content", json={"html": "<p>one</p>", "checkpoint": True, "session": "s1"}).get_json()
    b = c.put(f"/api/topics/{t}/content", json={"html": "<p>one two</p>", "session": "s1"}).get_json()
    assert a["changeset"]["id"] == b["changeset"]["id"]             # one entry per editing session
    d = c.put(f"/api/topics/{t}/content", json={"html": "<p>three</p>", "checkpoint": True, "session": "s2"}).get_json()
    assert d["changeset"]["id"] != a["changeset"]["id"]
    versions = c.get(f"/api/topics/{t}/history").get_json()
    assert [v["current"] for v in versions][:2] == [True, False] and versions[-1]["original"]
    diff = c.get(f"/api/topics/{t}/history/{versions[1]['id']}").get_json()["diff_html"]
    assert "<ins>one two</ins>" in diff or "<ins>one" in diff
    c.post(f"/api/topics/{t}/history/{versions[1]['id']}/restore")
    assert "one two" in c.get(f"/api/topics/{t}/content").get_json()["html"]
    c.delete(f"/api/topics/{t}/content")                               # restore original, undoable
    assert c.get(f"/api/topics/{t}/content").get_json()["edited"] is False
    c.post("/api/history/undo/latest")
    assert "one two" in c.get(f"/api/topics/{t}/content").get_json()["html"]


def test_undo_keeps_later_changes_and_reports_them(env):
    c, ids = env["client"], env["ids"]
    s = ids["sections"][2]
    first = c.patch(f"/api/structure/section/{s}", json={"title": "A", "icon_path": "/assets/i.webp"}).get_json()
    c.patch(f"/api/structure/section/{s}", json={"title": "B"})
    r = c.post(f"/api/history/undo/{first['changeset']['id']}")
    assert r.status_code == 409 and r.get_json()["needs_confirm"]
    r = c.post(f"/api/history/undo/{first['changeset']['id']}", json={"force": True})
    assert r.status_code == 200
    tree = c.get("/api/structure/tree/8f7b96f9-7778-4908-af76-a8ad722cd68a").get_json()
    sec = [x for ch in tree for x in ch["sections"] if x["id"] == s][0]
    assert sec["title"] == "B" and sec["icon"] in (None, "")       # later rename kept, icon reverted


def test_checkpoint_restore_and_undo_it(env):
    c, ids, db = env["client"], env["ids"], env["db"]
    cp = c.post("/api/history/checkpoints", json={"name": "before"}).get_json()["id"]
    at_cp = snapshot(db)
    c.patch(f"/api/structure/section/{ids['sections'][0]}", json={"title": "X"})
    c.delete(f"/api/structure/topic/{ids['topics'][4]}")
    after = snapshot(db)
    c.post(f"/api/history/checkpoints/{cp}/restore")
    assert snapshot(db) == at_cp
    c.post("/api/history/undo/latest")
    assert snapshot(db) == after


def test_failed_change_rolls_back(env):
    c, ids, db = env["client"], env["ids"], env["db"]
    before = snapshot(db)
    r = c.patch(f"/api/structure/section/{ids['sections'][0]}", json={"title": "  ", "icon_path": "/x.webp"})
    assert r.status_code == 400
    assert snapshot(db) == before


def test_pages_render(env):
    c, ids = env["client"], env["ids"]
    for u in ["/settings/history", "/settings/backup", f"/sections/{ids['sections'][0]}", "/libraries"]:
        assert c.get(u).status_code == 200, u
