"""Shared data-access + rendering helpers used by both page and API routes."""
import json

from flask import g

from .render import card_render
from .loader import _web_media_from_objectkey


def card_media(object_key):
    return _web_media_from_objectkey(object_key)


def row_to_card(row):
    """DB cards row -> dict understood by card_render.face()."""
    front = json.loads(row["front_json"]) if row["front_json"] else None
    back = json.loads(row["back_json"]) if row["back_json"] else None
    return {
        "card_id": row["id"],
        "note_id": row["note_id"],
        "ordinal": row["ordinal"],
        "kind": row["kind"],
        "is_beta": bool(row["is_beta"]),
        "front_document": front,
        "back_document": back,
    }


def render_card(row):
    """Return front/back HTML + metadata for one card row."""
    card = row_to_card(row)
    return {
        "id": row["id"],
        "topic_id": row["topic_id"],
        "topic_title": row["topic_title"] if "topic_title" in row.keys() else None,
        "note_id": row["note_id"],
        "kind": row["kind"],
        "ordinal": row["ordinal"],
        "is_beta": bool(row["is_beta"]),
        "front_html": card_render.face(card, False, media=card_media),
        "back_html": card_render.face(card, True, media=card_media),
        "has_back": bool(row["back_json"]),
        "front_text": row["front_text"],
    }


# ------------------------------------------------------------------ queries
def library_rows():
    return g.db.execute(
        "SELECT * FROM libraries ORDER BY sort_order, title"
    ).fetchall()


def chapter_rows(library_id):
    return g.db.execute(
        "SELECT * FROM chapters WHERE library_id=? ORDER BY sort_order, rowid", (library_id,)
    ).fetchall()


def section_rows(chapter_id):
    return g.db.execute(
        "SELECT * FROM sections WHERE chapter_id=? ORDER BY sort_order, rowid", (chapter_id,)
    ).fetchall()


def topic_rows(section_id):
    """Topics of a section; document_html is the user's edited version when one exists."""
    return g.db.execute(
        "SELECT t.id, t.section_id, t.sort_order, t.document_version, t.icon_url, "
        "       t.plain_text, t.has_cards, t.updated_at, "
        "       COALESCE(e.html, t.document_html) AS document_html, "
        "       COALESCE(e.title, t.title) AS title, t.title AS original_title, "
        "       e.updated_at AS edited_at, "
        "       (e.base_version IS NOT NULL AND t.document_version IS NOT NULL "
        "        AND e.base_version <> t.document_version) AS base_changed "
        "FROM topics t LEFT JOIN topic_edits e ON e.topic_id=t.id "
        "WHERE t.section_id=? ORDER BY t.sort_order", (section_id,)
    ).fetchall()


def resolve_topic(topic_id):
    """topic id -> {topic, section, chapter, library} rows for cross references, or None."""
    row = g.db.execute(
        "SELECT t.id topic_id, t.title topic_title, s.id section_id, s.title section_title, "
        "       c.id chapter_id, c.title chapter_title, c.library_id "
        "FROM topics t JOIN sections s ON s.id=t.section_id "
        "LEFT JOIN chapters c ON c.id=s.chapter_id WHERE t.id=?", (topic_id,)
    ).fetchone()
    return dict(row) if row else None


def sections_by_chapter(library_id):
    """All sections of a library grouped by chapter_id, each with studied status.
    One query -> {chapter_id: [ {id,title,icon,done,total,pct,studied}, ... ]}."""
    rows = g.db.execute(
        "SELECT s.chapter_id, s.id, s.title, s.icon_path, s.sort_order, "
        "       COUNT(t.id) total, "
        "       SUM(CASE WHEN p.completed=1 THEN 1 ELSE 0 END) done "
        "FROM sections s JOIN chapters c ON s.chapter_id=c.id "
        "LEFT JOIN topics t ON t.section_id=s.id "
        "LEFT JOIN progress p ON p.topic_id=t.id "
        "WHERE c.library_id=? GROUP BY s.id ORDER BY s.sort_order, s.rowid",
        (library_id,)).fetchall()
    out = {}
    for r in rows:
        total = r["total"] or 0
        done = r["done"] or 0
        out.setdefault(r["chapter_id"], []).append({
            "id": r["id"], "title": r["title"],
            "icon": icon_web_path(r["icon_path"]),
            "done": done, "total": total,
            "pct": round(100 * done / total) if total else 0,
            "studied": total > 0 and done >= total,
        })
    return out


def section_progress(section_id):
    """(#completed topics, #total topics) for a section, from live progress."""
    row = g.db.execute(
        "SELECT COUNT(*) total, "
        "SUM(CASE WHEN p.completed=1 THEN 1 ELSE 0 END) done "
        "FROM topics t LEFT JOIN progress p ON p.topic_id=t.id WHERE t.section_id=?",
        (section_id,),
    ).fetchone()
    total = row["total"] or 0
    done = row["done"] or 0
    return done, total


def chapter_progress(chapter_id):
    row = g.db.execute(
        "SELECT COUNT(*) total, "
        "SUM(CASE WHEN p.completed=1 THEN 1 ELSE 0 END) done "
        "FROM topics t JOIN sections s ON t.section_id=s.id "
        "LEFT JOIN progress p ON p.topic_id=t.id WHERE s.chapter_id=?",
        (chapter_id,),
    ).fetchone()
    return (row["done"] or 0), (row["total"] or 0)


def library_progress(library_id):
    row = g.db.execute(
        "SELECT COUNT(*) total, "
        "SUM(CASE WHEN p.completed=1 THEN 1 ELSE 0 END) done "
        "FROM topics t JOIN sections s ON t.section_id=s.id "
        "JOIN chapters c ON s.chapter_id=c.id "
        "LEFT JOIN progress p ON p.topic_id=t.id WHERE c.library_id=?",
        (library_id,),
    ).fetchone()
    return (row["done"] or 0), (row["total"] or 0)


def _step2ck():
    r = g.db.execute("SELECT id FROM libraries WHERE exam_scope='step2ck'").fetchone()
    return r["id"] if r else "8f7b96f9-7778-4908-af76-a8ad722cd68a"


def sections_studied(library_id=None, chapter_id=None):
    """(#sections fully studied, #total sections) where a section counts as
    studied when every one of its topics is completed. Live from progress."""
    where = "WHERE 1=1"
    params = []
    if library_id:
        where += " AND c.library_id=?"
        params.append(library_id)
    if chapter_id:
        where += " AND s.chapter_id=?"
        params.append(chapter_id)
    rows = g.db.execute(
        "SELECT s.id, COUNT(t.id) total, "
        "SUM(CASE WHEN p.completed=1 THEN 1 ELSE 0 END) done "
        "FROM sections s JOIN chapters c ON s.chapter_id=c.id "
        "LEFT JOIN topics t ON t.section_id=s.id "
        "LEFT JOIN progress p ON p.topic_id=t.id " + where +
        " GROUP BY s.id", params).fetchall()
    total = len(rows)
    studied = sum(1 for r in rows if (r["total"] or 0) > 0 and r["done"] == r["total"])
    return studied, total


def get_setting(key, default=None):
    r = g.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return r["value"] if r else default


def all_settings():
    return {r["key"]: r["value"] for r in g.db.execute("SELECT key,value FROM settings")}


def notif_unread():
    import json
    from .notifications_data import NOTIFICATIONS
    r = g.db.execute("SELECT value FROM settings WHERE key='notif_read_ids'").fetchone()
    try:
        read = set(json.loads(r["value"])) if r else set()
    except (ValueError, TypeError):
        read = set()
    return sum(1 for n in NOTIFICATIONS if n["id"] not in read)


def icon_web_path(icon_path):
    """iconPath 'preset/icons/medical/<x>.webp' -> local asset URL."""
    if not icon_path:
        return None
    if icon_path.startswith(("/blobs/", "/uploads/", "/assets/", "http://", "https://")):
        return icon_path
    if icon_path.startswith("preset/icons/medical/"):
        return "/assets/icons/medical/" + icon_path.split("/")[-1]
    if icon_path.startswith("content/") or icon_path.endswith((".png", ".webp")):
        return "/assets/icons/" + icon_path.split("/")[-1]
    return "/assets/icons/medical/" + icon_path.split("/")[-1]


def library_overview(library_id):
    """Per-section facts for the library page: progress, revisions, notes,
    highlights, edits, bookmark, last opened, topic titles (for search)."""
    q = lambda sql: {r[0]: r for r in g.db.execute(sql, (library_id,)).fetchall()}
    base = ("FROM topics t JOIN sections s ON s.id=t.section_id JOIN chapters c ON c.id=s.chapter_id "
            "WHERE c.library_id=? ")
    revised = q("SELECT t.section_id, MIN(COALESCE(p.reopened,0)) mn, MAX(COALESCE(p.reopened,0)) mx "
                "FROM topics t JOIN sections s ON s.id=t.section_id JOIN chapters c ON c.id=s.chapter_id "
                "LEFT JOIN progress p ON p.topic_id=t.id WHERE c.library_id=? GROUP BY t.section_id")
    notes = q("SELECT t.section_id, COUNT(*) n FROM topic_notes n JOIN topics t ON t.id=n.topic_id "
              "JOIN sections s ON s.id=t.section_id JOIN chapters c ON c.id=s.chapter_id "
              "WHERE c.library_id=? AND COALESCE(n.plain_text,'')<>'' GROUP BY t.section_id")
    hls = q("SELECT t.section_id, COUNT(*) n FROM (SELECT topic_id FROM highlights UNION ALL "
            "SELECT topic_id FROM inline_notes) h JOIN topics t ON t.id=h.topic_id "
            "JOIN sections s ON s.id=t.section_id JOIN chapters c ON c.id=s.chapter_id "
            "WHERE c.library_id=? GROUP BY t.section_id")
    edits = q("SELECT t.section_id, COUNT(*) n FROM topic_edits e JOIN topics t ON t.id=e.topic_id "
              "JOIN sections s ON s.id=t.section_id JOIN chapters c ON c.id=s.chapter_id "
              "WHERE c.library_id=? GROUP BY t.section_id")
    state = q("SELECT st.section_id, st.* FROM section_state st JOIN sections s ON s.id=st.section_id "
              "JOIN chapters c ON c.id=s.chapter_id WHERE c.library_id=?")
    titles = {}
    for r in g.db.execute("SELECT t.section_id, t.id, COALESCE(e.title, t.title) title "
                          "FROM topics t LEFT JOIN topic_edits e ON e.topic_id=t.id "
                          "JOIN sections s ON s.id=t.section_id JOIN chapters c ON c.id=s.chapter_id "
                          "WHERE c.library_id=? ORDER BY t.sort_order", (library_id,)):
        titles.setdefault(r["section_id"], []).append([r["id"], r["title"]])
    mine = {r[0] for r in g.db.execute("SELECT id FROM struct_overrides WHERE kind='section' AND created=1")}
    out = {}
    for sid in set(list(revised) + list(state) + list(titles)):
        rv, st = revised.get(sid), state.get(sid)
        out[sid] = {
            "revised": (rv["mn"] or 0) if rv else 0,
            "notes": notes[sid]["n"] if sid in notes else 0,
            "highlights": hls[sid]["n"] if sid in hls else 0,
            "edited": edits[sid]["n"] if sid in edits else 0,
            "bookmarked": bool(st and st["bookmarked"]),
            "last_opened": st["last_opened_at"] if st else None,
            "opens": (st["open_count"] or 0) if st else 0,
            "last_topic": st["last_topic_id"] if st else None,
            "topics": titles.get(sid, []),
        }
    for sid in mine:
        out.setdefault(sid, {"topics": []})["mine"] = True
    return out


def continue_reading(library_id=None, limit=1):
    """Most recently opened sections (with where the user stopped)."""
    sql = ("SELECT st.*, s.title section_title, s.chapter_id, c.title chapter_title, c.library_id, "
           "       (SELECT COALESCE(e.title,t.title) FROM topics t LEFT JOIN topic_edits e ON e.topic_id=t.id "
           "        WHERE t.id=st.last_topic_id) topic_title "
           "FROM section_state st JOIN sections s ON s.id=st.section_id JOIN chapters c ON c.id=s.chapter_id "
           "WHERE st.last_opened_at IS NOT NULL ")
    args = []
    if library_id:
        sql += "AND c.library_id=? "
        args.append(library_id)
    sql += "ORDER BY st.last_opened_at DESC LIMIT ?"
    args.append(limit)
    rows = []
    for r in g.db.execute(sql, args).fetchall():
        d = dict(r)
        done, total = section_progress(r["section_id"])
        d.update(done=done, total=total, pct=round(100 * done / total) if total else 0)
        d["url"] = "/libraries/%s/chapters/%s/sections/%s%s" % (
            r["library_id"], r["chapter_id"], r["section_id"],
            ("#topic-" + r["last_topic_id"]) if r["last_topic_id"] else "")
        rows.append(d)
    return rows


def bookmarked_sections(library_id):
    return [dict(r) for r in g.db.execute(
        "SELECT s.id, s.title, s.chapter_id, c.title chapter_title FROM section_state st "
        "JOIN sections s ON s.id=st.section_id JOIN chapters c ON c.id=s.chapter_id "
        "WHERE st.bookmarked=1 AND c.library_id=? ORDER BY c.sort_order, s.sort_order", (library_id,))]


def section_neighbours(section_id):
    """(previous, next) section in reading order across the whole library,
    following the user's current structure (not the source's next link)."""
    sec = g.db.execute("SELECT s.id, c.library_id FROM sections s JOIN chapters c ON c.id=s.chapter_id "
                       "WHERE s.id=?", (section_id,)).fetchone()
    if not sec:
        return None, None
    order = g.db.execute(
        "SELECT s.id, s.title, s.chapter_id, c.title chapter_title FROM sections s "
        "JOIN chapters c ON c.id=s.chapter_id WHERE c.library_id=? "
        "AND EXISTS (SELECT 1 FROM topics t WHERE t.section_id=s.id) "
        "ORDER BY c.sort_order, c.rowid, s.sort_order, s.rowid", (sec["library_id"],)).fetchall()
    ids = [r["id"] for r in order]
    if section_id not in ids:
        return None, None
    i = ids.index(section_id)
    prev = dict(order[i - 1]) if i > 0 else None
    nxt = dict(order[i + 1]) if i + 1 < len(order) else None
    return prev, nxt


# ------------------------------------------------------------------ cards you made
def _esc(t):
    import html as _h
    return _h.escape(t or "").replace("\n", "<br>")


def render_my_card(row):
    """A card you made while reading -> the same shape as render_card()."""
    topic_title = row["topic_title"] if "topic_title" in row.keys() else None
    front = ('<div class="my-card"><p class="my-card-q">%s</p></div>' % _esc(row["front"]))
    back = ('<div class="my-card"><p class="my-card-q">%s</p><hr><p class="my-card-a">%s</p>%s</div>'
            % (_esc(row["front"]), _esc(row["back"]),
               ('<blockquote class="my-card-src">%s</blockquote>' % _esc(row["quote"])) if row["quote"] else ""))
    return {"id": row["id"], "topic_id": row["topic_id"], "topic_title": topic_title, "note_id": None,
            "kind": "mine", "ordinal": 0, "is_beta": False, "front_html": front, "back_html": back,
            "has_back": True, "front_text": row["front"], "mine": True}


def my_cards_for_scope(scope, scope_id, now=None):
    base = ("SELECT m.*, COALESCE(e.title, t.title) topic_title FROM my_cards m "
            "LEFT JOIN topics t ON t.id=m.topic_id LEFT JOIN topic_edits e ON e.topic_id=m.topic_id ")
    if scope == "topic":
        q, a = base + "WHERE m.topic_id=?", [scope_id]
    elif scope == "section":
        q, a = base + "WHERE t.section_id=?", [scope_id]
    elif scope == "chapter":
        q, a = base + "WHERE t.section_id IN (SELECT id FROM sections WHERE chapter_id=?)", [scope_id]
    elif scope == "deck":
        q, a = base + "JOIN deck_cards dc ON dc.card_id=m.id WHERE dc.deck_id=?", [scope_id]
    elif scope == "due":
        q, a = base + "JOIN card_reviews r ON r.card_id=m.id WHERE r.due_at<=?", [now]
    elif scope == "weak":
        q = base + "JOIN card_reviews r ON r.card_id=m.id WHERE (r.lapses>0 OR r.last_rating=1)"
        q, a = (q + " AND m.topic_id=?", [scope_id]) if scope_id else (q, [])
    elif scope == "mine":
        q, a = base + "WHERE 1=1", []
    else:
        q, a = base + "WHERE 1=1", []
    try:
        return g.db.execute(q + " ORDER BY m.created_at", a).fetchall()
    except Exception:  # noqa: BLE001 - table missing on a very old db
        return []
