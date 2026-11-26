"""Regression tests from the app-logic review (security, flashcards, progress, notes)."""
import datetime

from tempu import db as dbmod
from tempu import sanitize


# ---------------------------------------------------------------- security
def test_cross_site_writes_are_refused(env):
    c = env["client"]
    r = c.post("/api/history/checkpoints", data='{"name":"x"}', content_type="text/plain",
               headers={"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    assert c.get("/api/history/checkpoints").get_json() == []
    r = c.post("/api/history/undo/latest", headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    # the app itself (same origin) still works
    r = c.post("/api/history/checkpoints", json={"name": "ok"},
               headers={"Origin": "http://localhost", "Sec-Fetch-Site": "same-origin"})
    assert r.status_code == 200


def test_foreign_host_names_are_refused(env):
    c = env["client"]
    assert c.get("/api/history/changesets", headers={"Host": "attacker-rebind.example:5077"}).status_code == 403
    for ok in ("127.0.0.1:5077", "localhost:5077", "192.168.1.20:5077", "[::1]:5077"):
        assert c.get("/api/history/changesets", headers={"Host": ok}).status_code == 200, ok


def test_note_text_cannot_break_out_of_the_reader_data_block(env):
    c, ids = env["client"], env["ids"]
    c.post("/api/inline-notes", json={"topic_id": ids["topics"][0], "note_text": "</script><b id=pwn>x</b>",
                                      "selected_text": "Original"})
    html = c.get(f"/sections/{ids['sections'][0]}", follow_redirects=True).get_data(as_text=True)
    block = html[html.index('id="annotations-data"'):]
    block = block[:block.index("</script>")]
    assert "<b id=pwn>" not in block and "\\u003c/script" in block.lower()


def test_sanitizer_drops_page_level_and_svg_script_tricks():
    dirty = ('<base href="https://evil.example/"><meta http-equiv="refresh" content="0;url=https://evil.example">'
             '<link rel="stylesheet" href="https://evil.example/x.css">'
             '<svg><a><animate attributeName="href" to="javascript:alert(1)"/><set attributeName="href" to="javascript:alert(1)"/>'
             '<text>t</text></a></svg><form action="https://evil.example"><p>kept</p></form>'
             '<a href="data:image/svg+xml;base64,PHN2Zz4=">x</a><img src="data:image/png;base64,AAAA">')
    out = sanitize.clean_html(dirty).lower()
    for bad in ("<base", "<meta", "<link", "<animate", "<set", "<form", "javascript:", 'href="data:'):
        assert bad not in out, (bad, out)
    assert "<p>kept</p>" in out and 'src="data:image/png' in out


def test_topic_notes_are_sanitized_and_empty_notes_removed(env):
    c, t = env["client"], env["ids"]["topics"][0]
    c.post(f"/api/notes/topic/{t}", json={"body_html": '<p onclick="x()">hi<script>bad()</script></p>', "plain_text": "hi"})
    body = c.get(f"/api/notes/topic/{t}").get_json()["body_html"]
    assert "onclick" not in body and "script" not in body and "hi" in body
    c.post(f"/api/notes/topic/{t}", json={"body_html": "<p><br></p>", "plain_text": "  "})
    conn = dbmod.connect(env["db"], journal=False)
    assert conn.execute("SELECT COUNT(*) FROM topic_notes").fetchone()[0] == 0
    conn.close()


def test_blobs_are_served_inert(env):
    import io
    c = env["client"]
    from test_storage import PNG2
    url = c.post("/api/uploads", data={"file": (io.BytesIO(PNG2), "x.png")}, content_type="multipart/form-data").get_json()["url"]
    r = c.get(url)
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert "sandbox" in r.headers.get("Content-Security-Policy", "")


# ---------------------------------------------------------------- flashcards
def test_due_counts_ignore_reviews_of_cards_that_no_longer_exist(env):
    c, t = env["client"], env["ids"]["topics"][0]
    cid = c.post("/api/my-cards", json={"topic_id": t, "front": "q", "back": "a"}).get_json()["id"]
    c.post("/api/review", json={"card_id": cid, "rating": 1})
    conn = dbmod.connect(env["db"], journal=False)
    conn.execute("UPDATE card_reviews SET due_at='2000-01-01T00:00:00Z'")
    conn.commit(); conn.close()
    assert "1 cards due" in c.get("/flashcards").get_data(as_text=True)
    c.delete(f"/api/my-cards/{cid}")
    assert "cards due" not in c.get("/flashcards").get_data(as_text=True)


def test_review_rejects_bad_ratings_and_unknown_cards(env):
    c, t = env["client"], env["ids"]["topics"][0]
    cid = c.post("/api/my-cards", json={"topic_id": t, "front": "q", "back": "a"}).get_json()["id"]
    for bad in ("abc", 0, 5, None):
        assert c.post("/api/review", json={"card_id": cid, "rating": bad}).status_code == 400, bad
    assert c.post("/api/review", json={"card_id": "no-such-card", "rating": 3}).status_code == 404
    r = c.post("/api/review", json={"card_id": cid, "rating": 3}).get_json()
    assert r["ok"] and set(r["previews"]) == {"1", "2", "3", "4"}


def test_hard_always_moves_a_review_card_forward():
    from tempu import srs
    row = {"state": "review", "reps": 3, "lapses": 0, "ease": 1.3, "interval_days": 2}
    assert srs.schedule(row, 2, fuzz=False)["interval_days"] >= 3


# ---------------------------------------------------------------- progress / study log
def test_completing_again_keeps_the_first_completion_day(env):
    c, ids = env["client"], env["ids"]
    t = ids["topics"][0]
    c.post("/api/progress/topic", json={"topic_id": t, "completed": True})
    conn = dbmod.connect(env["db"], journal=False)
    conn.execute("UPDATE progress SET completed_at='2026-01-01T10:00:00Z' WHERE topic_id=?", (t,))
    conn.commit()
    c.post("/api/progress/topic", json={"topic_id": t, "completed": True})
    c.post("/api/progress/section", json={"section_id": ids["sections"][0], "completed": True})
    assert conn.execute("SELECT completed_at FROM progress WHERE topic_id=?", (t,)).fetchone()[0].startswith("2026-01-01")
    c.post("/api/progress/section", json={"section_id": ids["sections"][0], "completed": False})
    assert conn.execute("SELECT reopened FROM progress WHERE topic_id=?", (t,)).fetchone()[0] == 1
    conn.close()


def test_study_log_validates_input(env):
    c = env["client"]
    for bad in ({"englishMinutes": "abc"}, {"englishMinutes": -30}, {"day": "2026-13-45", "englishMinutes": 5},
                {"day": "../x", "englishMinutes": 5}):
        assert c.post("/api/consistency/log", json=bad).status_code == 400, bad
    assert c.post("/api/consistency/log", json={"day": "2026-11-20", "englishMinutes": 15}).status_code == 200
    conn = dbmod.connect(env["db"], journal=False)
    r = conn.execute("SELECT app_seconds, credit_seconds FROM study_log WHERE day='2026-11-20'").fetchone()
    conn.close()
    assert r["app_seconds"] == 0 and r["credit_seconds"] == 900


def test_day_detail_uses_local_days(env, monkeypatch):
    """A topic completed at 00:30 local time (22:30 UTC the day before) belongs to the local day."""
    import time
    c, t = env["client"], env["ids"]["topics"][0]
    monkeypatch.setenv("TZ", "Africa/Cairo"); time.tzset()
    try:
        c.post("/api/progress/topic", json={"topic_id": t, "completed": True})
        conn = dbmod.connect(env["db"], journal=False)
        conn.execute("UPDATE progress SET completed_at='2026-11-25T22:30:00Z' WHERE topic_id=?", (t,))
        conn.commit(); conn.close()
        assert len(c.get("/api/day/2026-11-26").get_json()["completed"]) == 1
        assert len(c.get("/api/day/2026-11-25").get_json()["completed"]) == 0
    finally:
        monkeypatch.delenv("TZ"); time.tzset()


# ---------------------------------------------------------------- collections
def test_collections_survive_a_library_rebuild_and_count_once(env):
    c, t = env["client"], env["ids"]["topics"][0]
    cid = c.post("/api/collections", json={"title": "Mine"}).get_json()["id"]
    assert c.post(f"/api/collections/{cid}/items", json={"topic_id": t}).get_json()["added"] is True
    assert c.post(f"/api/collections/{cid}/items", json={"topic_id": t}).get_json()["added"] is False
    assert c.post("/api/collections/nope/items", json={"topic_id": t}).status_code == 404
    from tempu import loader
    conn = dbmod.connect(env["db"], journal=False)
    loader.reset_content(conn)                       # what a rebuild does to base.db
    conn.close()
    cols = c.get("/api/collections").get_json()["collections"]
    assert [(x["title"], x["item_count"]) for x in cols] == [("Mine", 1)]


def test_personal_collections_in_base_are_adopted_once(env):
    conn = dbmod.connect(env["db"], journal=False)
    conn.execute("DELETE FROM user_meta WHERE key='collections_adopted'")
    conn.execute("INSERT INTO base.collections(id,kind,title,item_count) VALUES('pc1','personal','Captured',1)")
    conn.execute("INSERT INTO base.collection_items(collection_id,item_type,topic_id,sort_order) VALUES('pc1','topic',?,0)",
                 (env["ids"]["topics"][0],))
    conn.commit()
    dbmod.ensure_user_tables(conn)
    assert conn.execute("SELECT COUNT(*) FROM my_collection_items WHERE collection_id='pc1'").fetchone()[0] == 1
    conn.execute("DELETE FROM my_collections WHERE id='pc1'"); conn.commit()      # you delete it...
    dbmod.ensure_user_tables(conn)                                               # ...it stays deleted
    assert conn.execute("SELECT COUNT(*) FROM my_collections WHERE id='pc1'").fetchone()[0] == 0
    conn.close()


# ---------------------------------------------------------------- structure
def test_structure_api_refuses_bad_parents_with_a_reason(env):
    c, ids = env["client"], env["ids"]
    r = c.post("/api/structure/topic", json={"parent_id": "nope", "title": "x"})
    assert r.status_code == 400 and "doesn't exist" in r.get_json()["error"]
    r = c.patch(f"/api/structure/topic/{ids['topics'][0]}", json={"parent_id": ids["chapters"][0]})
    assert r.status_code == 400
    c.delete(f"/api/structure/section/{ids['sections'][1]}")
    c.delete(f"/api/structure/chapter/{ids['chapters'][0]}")
    r = c.post(f"/api/structure/section/{ids['sections'][1]}/restore")
    assert r.status_code == 409 and "Restore it first" in r.get_json()["error"]
    r = c.post(f"/api/structure/topic", json={"parent_id": ids["sections"][0], "title": "x"})
    assert r.status_code == 400 and "in the trash inside chapter 'Chapter 0'" in r.get_json()["error"], r.get_json()


def test_reorder_never_pulls_in_items_from_elsewhere(env):
    c, ids = env["client"], env["ids"]
    t, s = ids["topics"], ids["sections"]
    c.patch(f"/api/structure/topic/{t[1]}", json={"order": [t[6], t[2], t[1]]})
    conn = dbmod.connect(env["db"], journal=False)
    where = {r[0]: r[1] for r in conn.execute("SELECT id, section_id FROM topics")}
    order = [r[0] for r in conn.execute("SELECT id FROM topics WHERE section_id=? ORDER BY sort_order", (s[0],))]
    conn.close()
    assert where[t[6]] == s[2]                      # stayed in its own section
    assert order == [t[2], t[1], t[0]]              # the forgotten child keeps a place at the end


# ---------------------------------------------------------------- search
def test_header_search_escapes_snippets_and_handles_symbols(env):
    c, t = env["client"], env["ids"]["topics"][0]
    c.put(f"/api/topics/{t}/content", json={"html": "<p>EF &lt;40% means &lt;b&gt;reduced</p>", "checkpoint": True})
    for q in ["<40%", '"', "EF <40", "(reduced"]:
        r = c.get("/api/search", query_string={"q": q})
        assert r.status_code == 200, q
        for it in r.get_json()["items"]:
            assert "<b>" not in (it["snippet"] or ""), (q, it["snippet"])
    items = c.get("/api/search", query_string={"q": "EF <40"}).get_json()["items"]
    assert items and items[0]["id"] == t
