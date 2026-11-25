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
        "SELECT * FROM chapters WHERE library_id=? ORDER BY sort_order", (library_id,)
    ).fetchall()


def section_rows(chapter_id):
    return g.db.execute(
        "SELECT * FROM sections WHERE chapter_id=? ORDER BY sort_order", (chapter_id,)
    ).fetchall()


def topic_rows(section_id):
    return g.db.execute(
        "SELECT * FROM topics WHERE section_id=? ORDER BY sort_order", (section_id,)
    ).fetchall()


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
        "WHERE c.library_id=? GROUP BY s.id ORDER BY s.sort_order",
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
    if icon_path.startswith("preset/icons/medical/"):
        return "/assets/icons/medical/" + icon_path.split("/")[-1]
    if icon_path.startswith("content/") or icon_path.endswith((".png", ".webp")):
        return "/assets/icons/" + icon_path.split("/")[-1]
    return "/assets/icons/medical/" + icon_path.split("/")[-1]
