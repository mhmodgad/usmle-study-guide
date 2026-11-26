"""Both layouts render every page, load only their own assets, and switching
back and forth leaves the other layout untouched."""
import pytest

from conftest import LIB


def _pages(ids):
    ch, sec, top = ids["chapters"][0], ids["sections"][0], ids["topics"][0]
    return ["/", "/libraries", f"/libraries/{LIB}", f"/libraries/{LIB}/chapters/{ch}",
            f"/libraries/{LIB}/chapters/{ch}/sections/{sec}", f"/sections/{sec}", f"/libraries/{LIB}/organize",
            "/notes", "/notes?view=inline", "/collections", "/flashcards", "/flashcards/library",
            "/flashcards/review?scope=due", "/consistency", "/search?q=topic",
            "/settings/preferences", "/settings/history", "/settings/backup"]


@pytest.mark.parametrize("mode", ["classic", "new", "classic"])
def test_every_page_renders_in_layout(env, mode):
    c, ids = env["client"], env["ids"]
    r = c.get(f"/ui/{mode}?next=/")
    assert r.status_code == 302 and r.headers["Location"].endswith("/")
    for u in _pages(ids):
        r = c.get(u, follow_redirects=True)
        assert r.status_code == 200, (mode, u, r.status_code)
        html = r.get_data(as_text=True)
        chrome = "/flashcards/review" not in u      # the review screen is full-screen, no menu
        if mode == "new":
            assert 'data-ui="new"' in html, u
            if chrome:
                assert "/static/new/new-ui.js" in html and "/ui/classic" in html, u   # a way back
        else:
            assert 'data-ui="new"' not in html and "/static/new/" not in html, u
            if chrome:
                assert "/ui/new" in html, u


def test_switch_rejects_open_redirect(env):
    c = env["client"]
    for bad in ["https://evil.example/", "//evil.example/x", "/\\evil.example"]:
        r = c.get("/ui/new", query_string={"next": bad})
        assert r.status_code == 302
        loc = r.headers["Location"]
        assert "evil.example" not in loc, (bad, loc)
    assert c.get("/ui/nonsense").status_code in (302, 404)


def test_new_layout_apis(env):
    c, ids = env["client"], env["ids"]
    top = ids["topics"][0]
    r = c.post("/api/my-cards", json={"topic_id": top, "front": "Original _____ 000", "back": "text"})
    assert r.status_code in (200, 201), r.get_data(as_text=True)
    d = c.get("/api/search/all?q=Original").get_json()
    assert d["topics"] and d["cards"], d
    assert c.get("/api/search/all?q=Original&kind=cards").get_json()["topics"] == []
    assert c.get("/api/day/2026-01-01").status_code == 200
    assert c.get("/api/day/not-a-day").status_code == 400
    md = c.get("/notes/export.md")
    assert md.status_code == 200 and md.mimetype == "text/markdown"
    assert c.get("/api/cards?scope=weak").status_code == 200
