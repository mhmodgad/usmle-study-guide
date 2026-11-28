"""Your structure changes must look the same after the library is rebuilt
(``python -m tempu.loader``, setup, or restoring a backup), and the trash must
bring back exactly what you put in it."""
import random

from conftest import LIB, snapshot


def rebuild(env):
    """What the loader does: reset the content to the source, then replay."""
    from tempu import db as dbmod, structure
    ids = env["ids"]
    conn = dbmod.connect(env["db"], journal=False)
    for t in ("topics", "sections", "chapters"):
        conn.execute(f"DELETE FROM base.{t}")
    for ci, cid in enumerate(ids["chapters"]):
        conn.execute("INSERT INTO chapters(id,library_id,title,sort_order) VALUES(?,?,?,?)",
                     (cid, LIB, f"Chapter {ci}", ci))
    for sid in ids["sections"]:
        c, s = int(sid[1]), int(sid[2])
        conn.execute("INSERT INTO sections(id,chapter_id,title,sort_order) VALUES(?,?,?,?)",
                     (sid, ids["chapters"][c], f"Section {c}.{s}", s))
    for tid in ids["topics"]:
        c, s, t = int(tid[1]), int(tid[2]), int(tid[3])
        conn.execute("INSERT INTO topics(id,section_id,title,sort_order,document_version,document_html,plain_text) "
                     "VALUES(?,?,?,?,1,?,?)", (tid, ids["sections"][c * 3 + s], f"Topic {c}.{s}.{t}", t,
                                               f"<p>Original text {c}{s}{t} words here</p>",
                                               f"Original text {c}{s}{t} words here"))
    conn.commit()
    structure.replay(conn)
    conn.close()


def structure_of(env):
    s = snapshot(env["db"])
    return {k: sorted(s[k]) for k in ("chapters", "sections", "topics")}


def assert_survives_rebuild(env):
    before = structure_of(env)
    rebuild(env)
    assert structure_of(env) == before


def test_icon_cannot_be_set_on_an_item_in_the_trash(env):
    c, ids = env["client"], env["ids"]
    c.delete(f"/api/structure/chapter/{ids['chapters'][1]}")
    r = c.patch(f"/api/structure/section/{ids['sections'][4]}", json={"icon_path": "/assets/icons/x.webp"})
    assert r.status_code == 404
    c.post(f"/api/structure/chapter/{ids['chapters'][1]}/restore")
    assert_survives_rebuild(env)


def test_renamed_item_restored_after_a_rebuild_keeps_its_name(env):
    c, ids = env["client"], env["ids"]
    sec = ids["sections"][3]
    c.patch(f"/api/structure/section/{sec}", json={"title": "My name"})
    c.delete(f"/api/structure/section/{sec}")
    rebuild(env)
    assert c.post(f"/api/structure/section/{sec}/restore").get_json()["ok"]
    assert [s for s in structure_of(env)["sections"] if s[0] == sec][0][2] == "My name"
    assert_survives_rebuild(env)


def test_section_trashed_on_its_own_stays_out_when_its_chapter_is_restored(env):
    c, ids = env["client"], env["ids"]
    ch, sec = ids["chapters"][0], ids["sections"][2]
    c.delete(f"/api/structure/section/{sec}")
    c.delete(f"/api/structure/chapter/{ch}")
    rebuild(env)
    c.post(f"/api/structure/chapter/{ch}/restore")
    assert sec not in {s[0] for s in structure_of(env)["sections"]}
    assert sec in {t["id"] for t in c.get("/api/structure/trash").get_json()}
    assert_survives_rebuild(env)


def test_topic_moved_out_of_a_section_that_went_to_the_trash_survives_a_rebuild(env):
    c, ids = env["client"], env["ids"]
    new_sec = c.post("/api/structure/section", json={"parent_id": ids["chapters"][1], "title": "Mine"}).get_json()["id"]
    topic = ids["topics"][11]                       # in section 1.0
    c.patch(f"/api/structure/topic/{topic}", json={"parent_id": new_sec, "index": 0})
    new_ch = c.post("/api/structure/chapter", json={"parent_id": LIB, "title": "Mine"}).get_json()["id"]
    c.patch(f"/api/structure/section/{ids['sections'][3]}", json={"parent_id": new_ch})
    c.delete(f"/api/structure/chapter/{new_ch}")    # section 1.0 goes to the trash with it
    assert_survives_rebuild(env)
    assert topic in {t[0] for t in structure_of(env)["topics"]}


def test_changes_in_the_same_millisecond_undo_in_order(env, monkeypatch):
    from tempu import history
    monkeypatch.setattr(history.time, "time", lambda: 1795000000.0)   # a frozen (or set back) clock
    c, ids = env["client"], env["ids"]
    sec = ids["sections"][0]
    for name in ("A", "B", "C"):
        c.patch(f"/api/structure/section/{sec}", json={"title": name})
    for expect in ("B", "A", "Section 0.0"):
        assert c.post("/api/history/undo/latest", json={"force": True}).status_code == 200
        assert [s for s in structure_of(env)["sections"] if s[0] == sec][0][2] == expect


def test_random_edits_always_survive_a_rebuild(env):
    """Random structure edits, undo/redo, trash/restore and rebuilds: after every
    rebuild the library is exactly what you had before it."""
    c, ids = env["client"], env["ids"]
    rnd = random.Random(7)
    chs, secs, tops = list(ids["chapters"]), list(ids["sections"]), list(ids["topics"])
    for i in range(150):
        op = rnd.randrange(14)
        if op == 0:
            c.patch(f"/api/structure/section/{rnd.choice(secs)}", json={"title": f"S{i}"})
        elif op == 1:
            c.patch(f"/api/structure/topic/{rnd.choice(tops)}", json={"parent_id": rnd.choice(secs), "index": rnd.randint(0, 3)})
        elif op == 2:
            c.patch(f"/api/structure/section/{rnd.choice(secs)}", json={"parent_id": rnd.choice(chs), "index": rnd.randint(0, 3)})
        elif op == 3:
            c.patch(f"/api/structure/chapter/{rnd.choice(chs)}", json={"index": rnd.randint(0, 2)})
        elif op == 4:
            c.delete(f"/api/structure/topic/{rnd.choice(tops)}")
        elif op == 5:
            c.delete(f"/api/structure/section/{rnd.choice(secs)}")
        elif op == 6:
            c.delete(f"/api/structure/chapter/{rnd.choice(chs)}")
        elif op == 7:
            r = c.post("/api/structure/section", json={"parent_id": rnd.choice(chs), "title": f"N{i}"})
            if r.status_code == 200:
                secs.append(r.get_json()["id"])
        elif op == 8:
            r = c.post("/api/structure/chapter", json={"parent_id": LIB, "title": f"C{i}"})
            if r.status_code == 200:
                chs.append(r.get_json()["id"])
        elif op == 9:
            c.patch(f"/api/structure/section/{rnd.choice(secs)}", json={"icon_path": "/assets/icons/x.webp"})
        elif op in (10, 11):
            items = sorted(c.get("/api/structure/trash").get_json(), key=lambda x: (x["kind"], x["id"]))
            if items:
                it = rnd.choice(items)
                c.post(f"/api/structure/{it['kind']}/{it['id']}/{'restore' if op == 10 else 'purge'}")
        elif op == 12:
            c.post("/api/history/undo/latest", json={"force": True})
        else:
            assert_survives_rebuild(env)
    assert_survives_rebuild(env)
