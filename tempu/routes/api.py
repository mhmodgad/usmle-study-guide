"""JSON API: flashcard decks/review, progress, notes, highlights, consistency,
settings, search. All state is persisted server-side in SQLite."""
import datetime
import json
import uuid

from flask import Blueprint, g, request, jsonify, abort

from .. import service as S
from .. import srs

bp = Blueprint("api", __name__, url_prefix="/api")


def _now():
    return datetime.datetime.utcnow().isoformat() + "Z"


def _uid():
    return str(uuid.uuid4())


# ------------------------------------------------------------- cards / review
def _cards_for_scope(scope, scope_id, limit=None, order="ordinal"):
    base = ("SELECT c.*, t.title topic_title FROM cards c "
            "LEFT JOIN topics t ON t.id=c.topic_id ")
    params = []
    if scope == "topic":
        where = "WHERE c.topic_id=?"
        params = [scope_id]
    elif scope == "section":
        where = ("WHERE c.topic_id IN (SELECT id FROM topics WHERE section_id=?)")
        params = [scope_id]
    elif scope == "chapter":
        where = "WHERE c.chapter_id=?"
        params = [scope_id]
    elif scope == "deck":
        base = ("SELECT c.*, t.title topic_title FROM deck_cards dc "
                "JOIN cards c ON c.id=dc.card_id LEFT JOIN topics t ON t.id=c.topic_id ")
        where = "WHERE dc.deck_id=?"
        params = [scope_id]
    elif scope == "due":
        base = ("SELECT c.*, t.title topic_title FROM card_reviews r "
                "JOIN cards c ON c.id=r.card_id LEFT JOIN topics t ON t.id=c.topic_id ")
        where = "WHERE r.due_at<=?"
        params = [_now()]
    elif scope == "weak":   # cards you forgot at least once, or last answered "Again"
        base = ("SELECT c.*, t.title topic_title FROM card_reviews r "
                "JOIN cards c ON c.id=r.card_id LEFT JOIN topics t ON t.id=c.topic_id ")
        where = "WHERE (r.lapses>0 OR r.last_rating=1)" + (" AND c.topic_id=?" if scope_id else "")
        params = [scope_id] if scope_id else []
    else:  # all (whole 2CK library)
        where = "WHERE c.library_id=(SELECT id FROM libraries WHERE exam_scope='step2ck')"
    sql = base + where + " ORDER BY " + (
        "c.chapter_id, c.topic_id, c.sort_order" if order == "ordinal" else "RANDOM()")
    if limit:
        sql += f" LIMIT {int(limit)}"
    return g.db.execute(sql, params).fetchall()


@bp.route("/cards")
def cards():
    scope = request.args.get("scope", "all")
    scope_id = request.args.get("id", "")
    limit = request.args.get("limit")
    order = request.args.get("order", "ordinal")
    rows = [] if scope == "mine" else _cards_for_scope(scope, scope_id, limit=limit, order=order)
    out = [S.render_card(r) for r in rows]
    out += [S.render_my_card(r) for r in S.my_cards_for_scope(scope, scope_id, _now())]
    if order != "ordinal":
        import random as _r
        _r.shuffle(out)
    if limit:
        out = out[:int(limit)]
    # attach review state
    ids = [c["id"] for c in out]
    rev = {}
    if ids:
        rr = g.db.execute(
            "SELECT * FROM card_reviews WHERE card_id IN (%s)" % ",".join("?" * len(ids)),
            ids).fetchall()
        rev = {r["card_id"]: dict(r) for r in rr}
    # topic -> reader href (for "Open topic")
    tids = list({c["topic_id"] for c in out if c["topic_id"]})
    hrefs = {}
    if tids:
        rows = g.db.execute(
            "SELECT t.id tid, c.library_id lib, s.chapter_id chap, s.id sec "
            "FROM topics t JOIN sections s ON t.section_id=s.id "
            "JOIN chapters c ON s.chapter_id=c.id "
            "WHERE t.id IN (%s)" % ",".join("?" * len(tids)), tids).fetchall()
        for r in rows:
            hrefs[r["tid"]] = "/libraries/%s/chapters/%s/sections/%s#topic-%s" % (
                r["lib"], r["chap"], r["sec"], r["tid"])
    for c in out:
        r = rev.get(c["id"])
        c["review"] = {"state": r["state"] if r else "new",
                       "due_at": r["due_at"] if r else None}
        c["previews"] = srs.preview(r)
        c["topic_href"] = hrefs.get(c["topic_id"])
    return jsonify({"count": len(out), "cards": out})


@bp.route("/review", methods=["POST"])
def review():
    data = request.get_json(force=True) or {}
    card_id = data.get("card_id")
    try:
        rating = int(data.get("rating"))
    except (TypeError, ValueError):
        rating = 0
    if not card_id or rating not in (1, 2, 3, 4):
        return jsonify({"ok": False, "error": "card_id and a rating 1-4 are required"}), 400
    if not (g.db.execute("SELECT 1 FROM cards WHERE id=?", (card_id,)).fetchone()
            or g.db.execute("SELECT 1 FROM my_cards WHERE id=?", (card_id,)).fetchone()):
        return jsonify({"ok": False, "error": "no such card"}), 404
    row = g.db.execute("SELECT * FROM card_reviews WHERE card_id=?", (card_id,)).fetchone()
    upd = srs.schedule(row, rating)
    g.db.execute(
        "INSERT INTO card_reviews(card_id,state,reps,lapses,ease,interval_days,due_at,"
        "last_rating,last_reviewed_at) VALUES(?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(card_id) DO UPDATE SET state=excluded.state,reps=excluded.reps,"
        "lapses=excluded.lapses,ease=excluded.ease,interval_days=excluded.interval_days,"
        "due_at=excluded.due_at,last_rating=excluded.last_rating,"
        "last_reviewed_at=excluded.last_reviewed_at",
        (card_id, upd["state"], upd["reps"], upd["lapses"], upd["ease"],
         upd["interval_days"], upd["due_at"], upd["last_rating"], upd["last_reviewed_at"]))
    g.db.commit()
    # what each button would do NOW (the study screen shows these if the card comes back)
    return jsonify({"ok": True, "review": upd, "previews": srs.preview(upd)})


# ------------------------------------------------------------- progress
@bp.route("/progress/topic", methods=["POST"])
def progress_topic():
    data = request.get_json(force=True)
    tid = data.get("topic_id")
    completed = 1 if data.get("completed") else 0
    if not tid:
        abort(400)
    existing = g.db.execute("SELECT * FROM progress WHERE topic_id=?", (tid,)).fetchone()
    reopened = (existing["reopened"] if existing else 0) or 0
    if existing and existing["completed"] and not completed:
        reopened += 1
    g.db.execute(
        "INSERT INTO progress(topic_id,completed,reopened,completed_at,last_opened_at) "
        "VALUES(?,?,?,?,?) ON CONFLICT(topic_id) DO UPDATE SET completed=excluded.completed,"
        "reopened=excluded.reopened,"
        # completing an already-completed topic keeps the day it was first completed
        "completed_at=CASE WHEN excluded.completed=1 AND progress.completed=1 THEN progress.completed_at "
        "ELSE excluded.completed_at END,"
        "last_opened_at=excluded.last_opened_at",
        (tid, completed, reopened, _now() if completed else None, _now()))
    g.db.commit()
    return jsonify({"ok": True, "completed": bool(completed)})


@bp.route("/progress/section", methods=["POST"])
def progress_section():
    data = request.get_json(force=True)
    sid = data.get("section_id")
    completed = 1 if data.get("completed") else 0
    if not sid:
        abort(400)
    tids = [r["id"] for r in g.db.execute("SELECT id FROM topics WHERE section_id=?", (sid,))]
    for tid in tids:
        g.db.execute(
            "INSERT INTO progress(topic_id,completed,completed_at,last_opened_at) "
            "VALUES(?,?,?,?) ON CONFLICT(topic_id) DO UPDATE SET completed=excluded.completed,"
            "completed_at=CASE WHEN excluded.completed=1 AND progress.completed=1 THEN progress.completed_at "
            "ELSE excluded.completed_at END,"
            "reopened=COALESCE(progress.reopened,0) + CASE WHEN progress.completed=1 AND excluded.completed=0 "
            "THEN 1 ELSE 0 END,"
            "last_opened_at=excluded.last_opened_at",
            (tid, completed, _now() if completed else None, _now()))
    g.db.commit()
    return jsonify({"ok": True, "topics": len(tids), "completed": bool(completed)})


@bp.route("/progress/open", methods=["POST"])
def progress_open():
    """Mark a section opened (updates last_opened_at + consistency)."""
    data = request.get_json(force=True)
    sid = data.get("section_id")
    if sid:
        g.db.execute(
            "UPDATE progress SET last_opened_at=? WHERE topic_id IN "
            "(SELECT id FROM topics WHERE section_id=?)", (_now(), sid))
        g.db.execute(
            "INSERT INTO section_state(section_id,last_opened_at,open_count,updated_at) VALUES(?,?,1,?) "
            "ON CONFLICT(section_id) DO UPDATE SET last_opened_at=excluded.last_opened_at, "
            "open_count=open_count+1, updated_at=excluded.updated_at", (sid, _now(), _now()))
        g.db.commit()
    return jsonify({"ok": True})


# ------------------------------------------------------------- topic notes
@bp.route("/notes/topic/<topic_id>", methods=["GET", "POST", "DELETE"])
def topic_note(topic_id):
    if request.method == "GET":
        r = g.db.execute("SELECT * FROM topic_notes WHERE topic_id=?", (topic_id,)).fetchone()
        return jsonify(dict(r) if r else {"topic_id": topic_id, "body_html": "", "plain_text": ""})
    if request.method == "DELETE":
        g.db.execute("DELETE FROM topic_notes WHERE topic_id=?", (topic_id,))
        g.db.commit()
        return jsonify({"ok": True})
    data = request.get_json(force=True) or {}
    body = _san.clean_html(data.get("body_html") or "")
    plain = (data.get("plain_text") or "").strip() or _san.plain_text(body)
    if not plain and "<img" not in body:          # an emptied note is a deleted note
        g.db.execute("DELETE FROM topic_notes WHERE topic_id=?", (topic_id,))
        g.db.commit()
        return jsonify({"ok": True, "deleted": True, "updated_at": _now()})
    g.db.execute(
        "INSERT INTO topic_notes(topic_id,body_html,plain_text,updated_at) VALUES(?,?,?,?) "
        "ON CONFLICT(topic_id) DO UPDATE SET body_html=excluded.body_html,"
        "plain_text=excluded.plain_text,updated_at=excluded.updated_at",
        (topic_id, body, plain, _now()))
    g.db.commit()
    return jsonify({"ok": True, "updated_at": _now()})


# ------------------------------------------------------------- highlights
@bp.route("/highlights", methods=["POST"])
def add_highlight():
    d = request.get_json(force=True)
    hid = d.get("id") or _uid()
    g.db.execute(
        "INSERT OR REPLACE INTO highlights(id,topic_id,color,selected_text,prefix_text,"
        "suffix_text,start_block_id,end_block_id,start_offset,end_offset,document_version,"
        "created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (hid, d.get("topic_id"), d.get("color", "yellow"), d.get("selected_text"),
         d.get("prefix_text"), d.get("suffix_text"), d.get("start_block_id"),
         d.get("end_block_id"), d.get("start_offset"), d.get("end_offset"),
         d.get("document_version"), _now()))
    g.db.commit()
    return jsonify({"ok": True, "id": hid})


@bp.route("/highlights/<hid>", methods=["PATCH"])
def patch_highlight(hid):
    d = request.get_json(force=True)
    if "color" in d:
        g.db.execute("UPDATE highlights SET color=? WHERE id=?", (d["color"], hid))
        g.db.commit()
    return jsonify({"ok": True})


@bp.route("/highlights/<hid>", methods=["DELETE"])
def del_highlight(hid):
    g.db.execute("DELETE FROM highlights WHERE id=?", (hid,))
    g.db.commit()
    return jsonify({"ok": True})


# ------------------------------------------------------------- inline notes
@bp.route("/inline-notes", methods=["POST"])
def add_inline_note():
    d = request.get_json(force=True)
    nid = d.get("id") or _uid()
    g.db.execute(
        "INSERT OR REPLACE INTO inline_notes(id,topic_id,note_text,selected_text,prefix_text,"
        "suffix_text,start_block_id,end_block_id,start_offset,end_offset,document_version,"
        "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (nid, d.get("topic_id"), d.get("note_text"), d.get("selected_text"),
         d.get("prefix_text"), d.get("suffix_text"), d.get("start_block_id"),
         d.get("end_block_id"), d.get("start_offset"), d.get("end_offset"),
         d.get("document_version"), _now(), _now()))
    g.db.commit()
    return jsonify({"ok": True, "id": nid})


@bp.route("/inline-notes/<nid>", methods=["PATCH"])
def patch_inline_note(nid):
    d = request.get_json(force=True)
    if "note_text" in d:
        g.db.execute("UPDATE inline_notes SET note_text=?, updated_at=? WHERE id=?",
                     (d["note_text"], _now(), nid))
        g.db.commit()
    return jsonify({"ok": True})


@bp.route("/inline-notes/<nid>", methods=["DELETE"])
def del_inline_note(nid):
    g.db.execute("DELETE FROM inline_notes WHERE id=?", (nid,))
    g.db.commit()
    return jsonify({"ok": True})


# ------------------------------------------------------------- decks
@bp.route("/decks", methods=["GET", "POST"])
def decks():
    if request.method == "GET":
        rows = g.db.execute("SELECT * FROM decks ORDER BY created_at").fetchall()
        return jsonify([dict(r) for r in rows])
    d = request.get_json(force=True)
    did = _uid()
    g.db.execute("INSERT INTO decks(id,name,color_key,parent_deck_id,created_at) "
                 "VALUES(?,?,?,?,?)",
                 (did, d.get("name", "New deck"), d.get("color_key"),
                  d.get("parent_deck_id"), _now()))
    g.db.commit()
    return jsonify({"ok": True, "id": did})


@bp.route("/decks/<deck_id>/cards", methods=["POST"])
def deck_add(deck_id):
    d = request.get_json(force=True)
    ids = d.get("card_ids")
    if not ids:
        # scope-based add
        scope, scope_id = d.get("scope"), d.get("scope_id")
        rows = _cards_for_scope(scope, scope_id)
        ids = [r["id"] for r in rows]
    n = 0
    for cid in ids:
        g.db.execute("INSERT OR IGNORE INTO deck_cards(deck_id,card_id,added_at) "
                     "VALUES(?,?,?)", (deck_id, cid, _now()))
        n += 1
    g.db.commit()
    return jsonify({"ok": True, "added": n})


@bp.route("/decks/<deck_id>/cards/<card_id>", methods=["DELETE"])
def deck_remove(deck_id, card_id):
    g.db.execute("DELETE FROM deck_cards WHERE deck_id=? AND card_id=?", (deck_id, card_id))
    g.db.commit()
    return jsonify({"ok": True})


@bp.route("/decks/<deck_id>", methods=["DELETE"])
def deck_delete(deck_id):
    g.db.execute("DELETE FROM decks WHERE id=?", (deck_id,))
    g.db.commit()
    return jsonify({"ok": True})


# ------------------------------------------------------------- collections
@bp.route("/collections", methods=["GET"])
def list_collections():
    rows = g.db.execute(
        "SELECT m.id, m.title, (SELECT COUNT(*) FROM my_collection_items i WHERE i.collection_id=m.id) item_count "
        "FROM my_collections m ORDER BY m.created_at DESC, m.rowid DESC").fetchall()
    return jsonify({"collections": [dict(r) for r in rows]})


@bp.route("/collections", methods=["POST"])
def create_collection():
    d = request.get_json(force=True) or {}
    title = (d.get("title") or "").strip()[:200] or "New collection"
    cid = _uid()
    g.db.execute("INSERT INTO my_collections(id,title,description,exam_scope,share_state,created_at) "
                 "VALUES(?,?,?,?,?,?)", (cid, title, d.get("description"), "step2ck", "private", _now()))
    g.db.commit()
    return jsonify({"ok": True, "id": cid})


@bp.route("/collections/<cid>/items", methods=["POST"])
def add_collection_item(cid):
    d = request.get_json(force=True) or {}
    if not g.db.execute("SELECT 1 FROM my_collections WHERE id=?", (cid,)).fetchone():
        return jsonify({"ok": False, "error": "That collection doesn't exist."}), 404
    kind = d.get("item_type") or "topic"
    if kind not in ("topic", "section") or not (d.get("topic_id") if kind == "topic" else d.get("section_id")):
        return jsonify({"ok": False, "error": "Say which topic or section to add."}), 400
    cur = g.db.execute(
        "INSERT OR IGNORE INTO my_collection_items(collection_id,item_type,topic_id,section_id,chapter_id,"
        "entry_id,sort_order,added_at) VALUES(?,?,?,?,?,?,"
        "(SELECT COALESCE(MAX(sort_order)+1,0) FROM my_collection_items WHERE collection_id=?),?)",
        (cid, kind, d.get("topic_id") if kind == "topic" else None, d.get("section_id"),
         d.get("chapter_id"), _uid(), cid, _now()))
    g.db.commit()
    return jsonify({"ok": True, "added": cur.rowcount == 1})      # added=false: it was already there


# ------------------------------------------------------------- chapter pins
@bp.route("/pin", methods=["POST"])
def pin():
    d = request.get_json(force=True)
    cid = d.get("chapter_id")
    want = d.get("pinned")
    key = f"pin:{cid}"
    if want:
        npins = g.db.execute("SELECT COUNT(*) n FROM settings WHERE key LIKE 'pin:%'").fetchone()["n"]
        if npins >= 3:
            return jsonify({"ok": False, "error": "You can pin up to 3 chapters"}), 400
        g.db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, "1"))
    else:
        g.db.execute("DELETE FROM settings WHERE key=?", (key,))
    g.db.commit()
    return jsonify({"ok": True})


# ------------------------------------------------------------- consistency
@bp.route("/consistency/log", methods=["POST"])
def consistency_log():
    d = request.get_json(force=True) or {}
    day = d.get("day") or datetime.date.today().isoformat()
    try:
        datetime.date.fromisoformat(day)
        eng = int(d.get("englishMinutes") or 0) * 60
        ara = int(d.get("arabicMinutes") or 0) * 60
        q = int(d.get("questionsAnswered") or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Use a date like 2026-11-26 and whole numbers."}), 400
    if min(eng, ara, q) < 0 or max(eng, ara) > 24 * 3600 or q > 5000:
        return jsonify({"ok": False, "error": "Numbers must be between 0 and one day's worth."}), 400
    # credit: 1 unit = 15 min english = 40 min arabic = 5 questions
    credit = eng + round(ara * (15 / 40)) + q * (15 * 60 / 5)
    g.db.execute(
        "INSERT INTO study_log(day,english_video_seconds,arabic_video_seconds,"
        "questions_answered,app_seconds,credit_seconds) VALUES(?,?,?,?,?,?) "
        "ON CONFLICT(day) DO UPDATE SET "
        "english_video_seconds=english_video_seconds+excluded.english_video_seconds,"
        "arabic_video_seconds=arabic_video_seconds+excluded.arabic_video_seconds,"
        "questions_answered=questions_answered+excluded.questions_answered,"
        "credit_seconds=credit_seconds+excluded.credit_seconds",
        (day, eng, ara, q, 0, int(credit)))
    g.db.commit()
    return jsonify({"ok": True})


# ------------------------------------------------------------- notifications
def _read_ids():
    r = g.db.execute("SELECT value FROM settings WHERE key='notif_read_ids'").fetchone()
    try:
        return set(json.loads(r["value"])) if r else set()
    except (ValueError, TypeError):
        return set()


def _save_read_ids(ids):
    g.db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('notif_read_ids',?)",
                 (json.dumps(sorted(ids)),))
    g.db.commit()


@bp.route("/notifications")
def notifications():
    from ..notifications_data import NOTIFICATIONS
    read = _read_ids()
    items = []
    for n in NOTIFICATIONS:
        items.append({**n, "status": "read" if n["id"] in read else "unread"})
    unread = sum(1 for i in items if i["status"] == "unread")
    return jsonify({"items": items, "unread": unread})


@bp.route("/notifications/read", methods=["POST"])
def notifications_read():
    from ..notifications_data import NOTIFICATIONS
    d = request.get_json(force=True) or {}
    read = _read_ids()
    if d.get("all"):
        read = {n["id"] for n in NOTIFICATIONS}
    elif d.get("id"):
        read.add(d["id"])
    _save_read_ids(read)
    unread = sum(1 for n in NOTIFICATIONS if n["id"] not in read)
    return jsonify({"ok": True, "unread": unread})


# ------------------------------------------------------------- avatar
@bp.route("/avatar", methods=["POST", "DELETE"])
def avatar():
    if request.method == "DELETE":
        g.db.execute("DELETE FROM settings WHERE key='avatar'")
        g.db.commit()
        return jsonify({"ok": True})
    d = request.get_json(force=True) or {}
    data = d.get("data", "")
    if not data.startswith("data:image/") or len(data) > 3_000_000:
        return jsonify({"ok": False, "error": "Invalid or too-large image"}), 400
    g.db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('avatar',?)", (data,))
    g.db.commit()
    return jsonify({"ok": True})


# ------------------------------------------------------------- settings
@bp.route("/settings", methods=["POST"])
def save_settings():
    d = request.get_json(force=True)
    for k, v in d.items():
        g.db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (k, str(v)))
    g.db.commit()
    return jsonify({"ok": True})


# ------------------------------------------------------------- search
@bp.route("/search")
def search():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"items": []})
    import html as _h
    import re as _re
    items, rows = [], []
    # words only, each quoted: symbols like < " ( - used to make the query invalid
    toks = _re.findall(r"\w+", q, flags=_re.UNICODE)
    if toks:
        try:
            rows = g.db.execute(
                "SELECT ref, title, chapter_id, section_id, library_id, "
                "snippet(search_fts,3,'\x02','\x03','…',8) snip "
                "FROM search_fts WHERE search_fts MATCH ? ORDER BY rank LIMIT 20",
                (" ".join('"%s"*' % t for t in toks),)).fetchall()
        except Exception:  # noqa: BLE001 - no FTS5: LIKE below
            rows = []
    for r in rows:
        snip = _h.escape(r["snip"] or "").replace("\x02", "<mark>").replace("\x03", "</mark>")
        items.append(_search_item(r["ref"], r["title"], r["section_id"], r["chapter_id"], r["library_id"], snip))
    if not items:
        like = f"%{q}%"
        for r in g.db.execute(
                "SELECT t.id ref, COALESCE(e.title,t.title) title, COALESCE(e.plain_text,t.plain_text) body, "
                "s.id section_id, s.chapter_id, c.library_id "
                "FROM topics t JOIN sections s ON t.section_id=s.id JOIN chapters c ON s.chapter_id=c.id "
                "LEFT JOIN topic_edits e ON e.topic_id=t.id "
                "WHERE COALESCE(e.title,t.title) LIKE ? OR COALESCE(e.plain_text,t.plain_text) LIKE ? LIMIT 20",
                (like, like)).fetchall():
            items.append(_search_item(r["ref"], r["title"], r["section_id"], r["chapter_id"], r["library_id"],
                                      _snip(r["body"], q, 50)))
    return jsonify({"items": items})


def _search_item(topic_id, title, section_id, chapter_id, library_id, snip):
    chap = g.db.execute("SELECT title FROM chapters WHERE id=?", (chapter_id,)).fetchone()
    return {
        "id": topic_id, "title": title, "snippet": snip,
        "breadcrumb": ["USMLE STEP 2CK", chap["title"] if chap else ""],
        "href": f"/libraries/{library_id}/chapters/{chapter_id}/sections/{section_id}#topic-{topic_id}",
    }


# ------------------------------------------------------------- cross references
@bp.route("/xref/<topic_id>")
def xref_lookup(topic_id):
    hit = S.resolve_topic(topic_id)
    if not hit:
        return jsonify({"found": False, "topic_id": topic_id})
    hit["found"] = True
    hit["url"] = "/libraries/%s/chapters/%s/sections/%s" % (
        hit["library_id"], hit["chapter_id"], hit["section_id"])
    return jsonify(hit)


# ------------------------------------------------------------- content editor
# Edits live in topic_edits (user state), never in the content tables, so a
# content rebuild (python -m tempu.loader) keeps them.
import os as _os
from flask import current_app as _app
from .. import sanitize as _san
from .. import history as _hist
from .. import blobs as _blobs

_IMG_EXT = {"png", "jpg", "jpeg", "gif", "webp", "avif", "bmp"}


def _topic_or_404(topic_id):
    t = g.db.execute("SELECT * FROM topics WHERE id=?", (topic_id,)).fetchone()
    if not t:
        abort(404)
    return t


def _reindex_topic(topic_id, title, plain):
    try:
        r = g.db.execute(
            "SELECT t.section_id, s.chapter_id, c.library_id FROM topics t "
            "JOIN sections s ON s.id=t.section_id JOIN chapters c ON c.id=s.chapter_id "
            "WHERE t.id=?", (topic_id,)).fetchone()
        if not r:
            return
        g.db.execute("DELETE FROM search_fts WHERE ref=? AND kind='topic'", (topic_id,))
        g.db.execute(
            "INSERT INTO search_fts(ref,kind,title,body,library_id,chapter_id,section_id) "
            "VALUES(?,?,?,?,?,?,?)",
            (topic_id, "topic", title or "", plain or "", r["library_id"], r["chapter_id"], r["section_id"]))
    except Exception:  # noqa: BLE001 - FTS missing: search falls back to LIKE on topics
        pass


@bp.route("/topics/<topic_id>/content", methods=["GET"])
def topic_content_get(topic_id):
    t = _topic_or_404(topic_id)
    e = g.db.execute("SELECT * FROM topic_edits WHERE topic_id=?", (topic_id,)).fetchone()
    return jsonify({
        "topic_id": topic_id,
        "html": e["html"] if e else t["document_html"],
        "title": (e["title"] if e and e["title"] else t["title"]),
        "edited": bool(e),
        "edited_at": e["updated_at"] if e else None,
        "history": len(_hist.topic_versions(g.db, topic_id)),
        "base_changed": bool(e and e["base_version"] is not None
                             and t["document_version"] is not None
                             and e["base_version"] != t["document_version"]),
    })


def _topic_title(t, e=None):
    if e is None:
        e = g.db.execute("SELECT title FROM topic_edits WHERE topic_id=?", (t["id"],)).fetchone()
    return (e["title"] if e and e["title"] else None) or t["title"] or "Untitled topic"


@bp.route("/topics/<topic_id>/content", methods=["PUT", "POST"])
def topic_content_save(topic_id):
    """Autosave from the editor. Saves within 2 minutes of each other (same
    editing session) are one history entry; ``checkpoint`` starts a new one."""
    t = _topic_or_404(topic_id)
    d = request.get_json(force=True) or {}
    html = _san.clean_html(d.get("html") or "")
    title = (d.get("title") or "").strip() or None
    if title == t["title"]:
        title = None
    now = _now()
    plain = _san.plain_text(html)
    label = "Edited '%s'" % (title or _topic_title(t))
    with _hist.Change(g.db, label, kind="edit", scope=("topic", topic_id),
                      session=d.get("session"), coalesce=not d.get("checkpoint")) as ch:
        g.db.execute(
            "INSERT INTO topic_edits(topic_id,html,title,plain_text,base_version,updated_at) "
            "VALUES(?,?,?,?,?,?) ON CONFLICT(topic_id) DO UPDATE SET "
            "html=excluded.html, title=excluded.title, plain_text=excluded.plain_text, "
            "updated_at=excluded.updated_at",
            (topic_id, html, title, plain, t["document_version"], now))
        _reindex_topic(topic_id, title or t["title"], plain)
    return jsonify({"ok": True, "updated_at": now, "changeset": ch.info()})


@bp.route("/topics/<topic_id>/content", methods=["DELETE"])
def topic_content_restore(topic_id):
    """Drop the user's edits and go back to the original document (undoable)."""
    t = _topic_or_404(topic_id)
    with _hist.Change(g.db, "Restored original of '%s'" % t["title"], kind="edit",
                      scope=("topic", topic_id)) as ch:
        g.db.execute("DELETE FROM topic_edits WHERE topic_id=?", (topic_id,))
        _reindex_topic(topic_id, t["title"], t["plain_text"])
    return jsonify({"ok": True, "changeset": ch.info()})


@bp.route("/topics/<topic_id>/history", methods=["GET"])
def topic_history(topic_id):
    """Saved versions of this topic, newest first; the original is always last."""
    _topic_or_404(topic_id)
    out = _hist.topic_versions(g.db, topic_id)
    if not out or not out[-1]["original"]:
        out.append({"id": 0, "changeset": None, "label": "Original", "saved_at": None, "original": True,
                    "title": None, "size": 0, "current": not g.db.execute(
                        "SELECT 1 FROM topic_edits WHERE topic_id=?", (topic_id,)).fetchone(),
                    "undone": False})
    return jsonify(out)


def _version_html(topic_id, hid):
    """(html, title) of a saved version; hid 0 = the original."""
    t = _topic_or_404(topic_id)
    if hid == 0:
        return t["document_html"], None
    rev, after = _hist.revision_state(g.db, hid)
    if not rev or rev["tbl"] != "topic_edits" or json.loads(rev["pk"]) != [topic_id]:
        abort(404)
    if after is None:
        return t["document_html"], None
    return after.get("html") or "", after.get("title")


@bp.route("/topics/<topic_id>/history/<int:hid>", methods=["GET"])
def topic_history_version(topic_id, hid):
    """One version's HTML plus a word-level comparison with the current text."""
    html, title = _version_html(topic_id, hid)
    t = _topic_or_404(topic_id)
    e = g.db.execute("SELECT html FROM topic_edits WHERE topic_id=?", (topic_id,)).fetchone()
    cur_html = e["html"] if e else t["document_html"]
    return jsonify({"id": hid, "html": html, "title": title,
                    "diff_html": _diff_words(_san.plain_text(cur_html or ""), _san.plain_text(html or ""))})


@bp.route("/topics/<topic_id>/history/<int:hid>/restore", methods=["POST"])
def topic_history_restore(topic_id, hid):
    t = _topic_or_404(topic_id)
    html, title = _version_html(topic_id, hid)
    if hid == 0:
        return topic_content_restore(topic_id)
    plain = _san.plain_text(html)
    with _hist.Change(g.db, "Restored an earlier version of '%s'" % (title or t["title"]), kind="edit",
                      scope=("topic", topic_id)) as ch:
        g.db.execute(
            "INSERT INTO topic_edits(topic_id,html,title,plain_text,base_version,updated_at) "
            "VALUES(?,?,?,?,?,?) ON CONFLICT(topic_id) DO UPDATE SET html=excluded.html, "
            "title=excluded.title, plain_text=excluded.plain_text, updated_at=excluded.updated_at",
            (topic_id, html, title, plain, t["document_version"], _now()))
        _reindex_topic(topic_id, title or t["title"], plain)
    return jsonify({"ok": True, "changeset": ch.info()})


def _diff_words(old, new):
    """HTML showing how ``new`` (the chosen version) differs from ``old`` (current)."""
    import difflib
    import html as H
    a, b = old.split(), new.split()
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            seg = a[i1:i2]
            if len(seg) > 40:   # keep long unchanged runs short
                seg = seg[:15] + ["…"] + seg[-15:]
            out.append(H.escape(" ".join(seg)))
        if op in ("delete", "replace"):
            out.append("<del>%s</del>" % H.escape(" ".join(a[i1:i2])))
        if op in ("insert", "replace"):
            out.append("<ins>%s</ins>" % H.escape(" ".join(b[j1:j2])))
    return " ".join(out)


@bp.route("/uploads", methods=["POST"])
def upload_image():
    """Save an image you add (editor, icons) into the blob store: data/blobs/<sha>."""
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "no file"}), 400
    ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
    if ext not in _IMG_EXT:
        mt = (f.mimetype or "").split("/")[-1].lower()
        ext = {"jpeg": "jpg"}.get(mt, mt)
        if ext not in _IMG_EXT:
            return jsonify({"error": "only image files can be added"}), 400
    url = _blobs.save_upload(g.db, _app.config["DATA_DIR"], f.stream, ext, original_name=f.filename)
    return jsonify({"url": url, "name": f.filename})


# ------------------------------------------------------------- section reading state
@bp.route("/sections/<section_id>/state", methods=["GET", "POST"])
def section_state(section_id):
    if request.method == "GET":
        r = g.db.execute("SELECT * FROM section_state WHERE section_id=?", (section_id,)).fetchone()
        return jsonify(dict(r) if r else {"section_id": section_id})
    d = request.get_json(force=True) or {}
    cur = g.db.execute("SELECT * FROM section_state WHERE section_id=?", (section_id,)).fetchone()
    if not cur:
        g.db.execute("INSERT INTO section_state(section_id,updated_at) VALUES(?,?)", (section_id, _now()))
    sets, vals = [], []
    if "last_topic_id" in d:
        sets.append("last_topic_id=?"); vals.append(d["last_topic_id"])
    if "scroll_ratio" in d:
        try:
            sets.append("scroll_ratio=?"); vals.append(max(0.0, min(1.0, float(d["scroll_ratio"]))))
        except (TypeError, ValueError):
            sets.pop()
    if "bookmarked" in d:
        sets.append("bookmarked=?"); vals.append(1 if d["bookmarked"] else 0)
    if sets:
        sets.append("updated_at=?"); vals.append(_now())
        g.db.execute(f"UPDATE section_state SET {', '.join(sets)} WHERE section_id=?", (*vals, section_id))
    g.db.commit()
    return jsonify({"ok": True})


# ------------------------------------------------------------- structure editing
from .. import structure as _st  # noqa: E402


def _kind(kind):
    if kind not in _st.KINDS:
        abort(404)
    return kind


_KIND_WORD = {"library": "library", "chapter": "chapter", "section": "section", "topic": "topic"}


def _name(kind, item_id):
    t, _ = _st.KINDS[kind]
    if kind == "topic":
        r = g.db.execute("SELECT COALESCE(e.title,t.title) title FROM topics t LEFT JOIN topic_edits e "
                         "ON e.topic_id=t.id WHERE t.id=?", (item_id,)).fetchone()
    else:
        r = g.db.execute(f"SELECT title FROM {t} WHERE id=?", (item_id,)).fetchone()
    if not r:
        o = g.db.execute("SELECT title FROM struct_overrides WHERE kind=? AND id=?", (kind, item_id)).fetchone()
        return (o["title"] if o and o["title"] else None) or "untitled"
    return r["title"] or "untitled"


def _parent_name(kind, parent_id):
    pk = {"chapter": "library", "section": "chapter", "topic": "section"}.get(kind)
    return _name(pk, parent_id) if pk and parent_id else ""


@bp.route("/structure/<kind>", methods=["POST"])
def structure_create(kind):
    _kind(kind)
    if kind == "library":
        return jsonify({"error": "libraries can't be created here"}), 400
    d = request.get_json(force=True) or {}
    parent = d.get("parent_id")
    if not parent:
        return jsonify({"error": "parent_id required"}), 400
    title = (d.get("title") or "").strip() or "New " + kind
    prob = _st.parent_problem(g.db, kind, parent)
    if prob:
        return jsonify({"error": prob}), 400
    with _hist.Change(g.db, "Added %s '%s' to '%s'" % (kind, title, _parent_name(kind, parent)),
                      kind="structure", scope=(kind, None)) as ch:
        new_id = _st.create(g.db, kind, parent, d.get("title"), d.get("after_id"), d.get("icon_path"))
        ch.scope_id = new_id
    if ch.id:
        g.db.execute("UPDATE changesets SET scope_id=? WHERE id=?", (new_id, ch.id))
        g.db.commit()
    out = {"ok": True, "id": new_id, "changeset": ch.info()}
    if kind == "section":
        chp = g.db.execute("SELECT library_id FROM chapters WHERE id=?", (parent,)).fetchone()
        if chp:
            out["url"] = "/libraries/%s/chapters/%s/sections/%s" % (chp["library_id"], parent, new_id)
    if kind == "topic":
        out["url"] = "/sections/%s#topic-%s" % (parent, new_id)
    return jsonify(out)


@bp.route("/structure/<kind>/<item_id>", methods=["PATCH"])
def structure_update(kind, item_id):
    _kind(kind)
    d = request.get_json(force=True) or {}
    old = _name(kind, item_id)
    parts = []
    if "title" in d:
        parts.append("Renamed %s '%s' to '%s'" % (kind, old, (d["title"] or "").strip()))
    if "icon_path" in d:
        parts.append("Changed the icon of '%s'" % old)
    moving = kind != "library" and ("parent_id" in d or "order" in d or "index" in d)
    if moving:
        t, pcol = _st.KINDS[kind]
        row = g.db.execute(f"SELECT {pcol} p FROM {t} WHERE id=?", (item_id,)).fetchone()
        if not row:
            abort(404)
        dest = d.get("parent_id") or row["p"]
        prob = _st.parent_problem(g.db, kind, dest)
        if prob:
            return jsonify({"error": prob}), 400
        parts.append(("Moved %s '%s' to '%s'" % (kind, old, _parent_name(kind, dest)))
                     if dest != row["p"] else "Reordered '%s'" % old)
    label = "; ".join(parts) or "Changed '%s'" % old
    with _hist.Change(g.db, label, kind="structure", scope=(kind, item_id)) as ch:
        if "title" in d and not _st.rename(g.db, kind, item_id, d["title"]):
            raise _Abort(jsonify({"error": "not found or empty title"}), 400)
        if "icon_path" in d:
            _st.set_icon(g.db, kind, item_id, d["icon_path"] or None)
        if moving:
            _st.move(g.db, kind, item_id, dest, d.get("order"), d.get("index"))
        if kind == "topic" and ("title" in d or moving):
            _hist.reindex_topics(g.db, [item_id])
    return jsonify({"ok": True, "changeset": ch.info()})


class _Abort(Exception):
    """Leave a Change block (rolling it back) and answer with this response."""
    def __init__(self, resp, code):
        super().__init__("abort")
        self.resp, self.code = resp, code


@bp.errorhandler(_Abort)
def _on_abort(e):
    return e.resp, e.code


@bp.route("/structure/<kind>/<item_id>", methods=["DELETE"])
def structure_delete(kind, item_id):
    _kind(kind)
    if kind == "library":
        return jsonify({"error": "libraries can't be deleted"}), 400
    with _hist.Change(g.db, "Deleted %s '%s'" % (kind, _name(kind, item_id)), kind="structure",
                      scope=(kind, item_id)) as ch:
        ok = _st.delete(g.db, kind, item_id)
    return jsonify({"ok": ok, "changeset": ch.info()})


@bp.route("/structure/trash", methods=["GET"])
def structure_trash():
    return jsonify(_st.trash(g.db))


@bp.route("/structure/<kind>/<item_id>/restore", methods=["POST"])
def structure_restore(kind, item_id):
    _kind(kind)
    prob = _st.restore_problem(g.db, kind, item_id)
    if prob:
        return jsonify({"ok": False, "error": prob}), 409
    with _hist.Change(g.db, "Restored %s '%s' from the trash" % (kind, _name(kind, item_id)),
                      kind="structure", scope=(kind, item_id)) as ch:
        ok = _st.restore(g.db, kind, item_id)
        if ok:
            ids = [r[0] for r in g.db.execute("SELECT id FROM topics WHERE id=? OR section_id=? OR section_id IN "
                                              "(SELECT id FROM sections WHERE chapter_id=?)",
                                              (item_id, item_id, item_id))]
            _hist.reindex_topics(g.db, ids)
    return jsonify({"ok": ok, "changeset": ch.info()})


@bp.route("/structure/<kind>/<item_id>/purge", methods=["POST"])
def structure_purge(kind, item_id):
    _kind(kind)
    with _hist.Change(g.db, "Deleted %s '%s' forever (still in Activity)" % (kind, _name(kind, item_id)),
                      kind="structure", scope=(kind, item_id)) as ch:
        ok = _st.purge(g.db, kind, item_id)
    return jsonify({"ok": ok, "changeset": ch.info()})


@bp.route("/structure/tree/<library_id>", methods=["GET"])
def structure_tree(library_id):
    """Whole library as a tree (chapters > sections > topics) for the organizer."""
    chs = g.db.execute("SELECT id,title,icon_path FROM chapters WHERE library_id=? "
                       "ORDER BY sort_order, rowid", (library_id,)).fetchall()
    secs = g.db.execute("SELECT s.id,s.title,s.icon_path,s.chapter_id FROM sections s JOIN chapters c "
                        "ON c.id=s.chapter_id WHERE c.library_id=? ORDER BY s.sort_order, s.rowid",
                        (library_id,)).fetchall()
    tops = g.db.execute("SELECT t.id, COALESCE(e.title,t.title) title, t.section_id FROM topics t "
                        "JOIN sections s ON s.id=t.section_id JOIN chapters c ON c.id=s.chapter_id "
                        "LEFT JOIN topic_edits e ON e.topic_id=t.id "
                        "WHERE c.library_id=? ORDER BY t.sort_order, t.rowid", (library_id,)).fetchall()
    created = {(r["kind"], r["id"]) for r in g.db.execute(
        "SELECT kind,id FROM struct_overrides WHERE created=1 AND deleted=0")}
    by_sec, by_ch = {}, {}
    for t in tops:
        by_sec.setdefault(t["section_id"], []).append(
            {"id": t["id"], "title": t["title"], "mine": ("topic", t["id"]) in created})
    for s_ in secs:
        by_ch.setdefault(s_["chapter_id"], []).append(
            {"id": s_["id"], "title": s_["title"], "icon": S.icon_web_path(s_["icon_path"]),
             "mine": ("section", s_["id"]) in created, "topics": by_sec.get(s_["id"], [])})
    return jsonify([{"id": c["id"], "title": c["title"], "icon": S.icon_web_path(c["icon_path"]),
                     "mine": ("chapter", c["id"]) in created, "sections": by_ch.get(c["id"], [])}
                    for c in chs])


@bp.route("/structure/icons", methods=["GET"])
def structure_icons():
    """Every icon the user can pick: the app's medical icon set, icons already
    used by chapters/sections, and images uploaded as icons."""
    out, seen = [], set()

    def add(url, group):
        if url and url not in seen:
            seen.add(url)
            out.append({"url": url, "group": group, "name": url.rsplit("/", 1)[-1].rsplit(".", 1)[0].replace("-", " ").replace("_", " ")})
    base = _app.config["ASSETS_DIR"]
    for sub in ("icons/medical", "icons"):
        d = _os.path.join(base, sub)
        if _os.path.isdir(d):
            for fn in sorted(_os.listdir(d)):
                if fn.lower().endswith((".webp", ".png", ".svg", ".jpg", ".jpeg", ".gif")):
                    add(f"/assets/{sub}/{fn}", "Library icons")
    for r in g.db.execute("SELECT icon_path FROM chapters UNION SELECT icon_path FROM sections"):
        add(S.icon_web_path(r[0]), "In use")
    for r in g.db.execute("SELECT DISTINCT icon_path FROM struct_overrides WHERE icon_path LIKE '/blobs/%' "
                          "OR icon_path LIKE '/uploads/%'"):
        add(r[0], "Your uploads")
    return jsonify(out)


# ------------------------------------------------------------- cards you make while reading
FROM_READING_DECK = "from-reading"


def _ensure_reading_deck():
    if not g.db.execute("SELECT 1 FROM decks WHERE id=?", (FROM_READING_DECK,)).fetchone():
        g.db.execute("INSERT INTO decks(id,name,color_key,created_at) VALUES(?,?,?,?)",
                     (FROM_READING_DECK, "From reading", "blue", _now()))


@bp.route("/my-cards", methods=["GET", "POST"])
def my_cards():
    if request.method == "GET":
        return jsonify([S.render_my_card(r) for r in S.my_cards_for_scope(
            request.args.get("scope", "mine"), request.args.get("id", ""), _now())])
    d = request.get_json(force=True) or {}
    front, back = (d.get("front") or "").strip(), (d.get("back") or "").strip()
    if not front or not back:
        return jsonify({"error": "A card needs a question and an answer."}), 400
    cid = "my-" + _uid()
    title = g.db.execute("SELECT title FROM topics WHERE id=?", (d.get("topic_id"),)).fetchone()
    label = "Made a flashcard%s" % (" from '%s'" % title["title"] if title else "")
    with _hist.Change(g.db, label, kind="structure", scope=("topic", d.get("topic_id"))) as ch:
        g.db.execute("INSERT INTO my_cards(id,topic_id,front,back,quote,source,created_at,updated_at) "
                     "VALUES(?,?,?,?,?,?,?,?)", (cid, d.get("topic_id"), front[:2000], back[:2000],
                                                 (d.get("quote") or "")[:2000], d.get("source") or "selection",
                                                 _now(), _now()))
        deck = d.get("deck_id") or FROM_READING_DECK
        if deck == FROM_READING_DECK:
            _ensure_reading_deck()
        g.db.execute("INSERT OR IGNORE INTO deck_cards(deck_id,card_id,added_at) VALUES(?,?,?)", (deck, cid, _now()))
    return jsonify({"ok": True, "id": cid, "deck_id": deck, "changeset": ch.info()})


@bp.route("/my-cards/<cid>", methods=["PATCH", "DELETE"])
def my_card(cid):
    if not g.db.execute("SELECT 1 FROM my_cards WHERE id=?", (cid,)).fetchone():
        abort(404)
    if request.method == "DELETE":
        with _hist.Change(g.db, "Deleted a flashcard you made", kind="structure") as ch:
            g.db.execute("DELETE FROM deck_cards WHERE card_id=?", (cid,))
            g.db.execute("DELETE FROM my_cards WHERE id=?", (cid,))
        return jsonify({"ok": True, "changeset": ch.info()})
    d = request.get_json(force=True) or {}
    with _hist.Change(g.db, "Edited a flashcard you made", kind="structure") as ch:
        for f in ("front", "back"):
            if (d.get(f) or "").strip():
                g.db.execute(f"UPDATE my_cards SET {f}=?, updated_at=? WHERE id=?", (d[f].strip()[:2000], _now(), cid))
    return jsonify({"ok": True, "changeset": ch.info()})


# ------------------------------------------------------------- search everything (new layout)
def _snip(text, q, width=70):
    import html as _h
    t = " ".join((text or "").split())
    i = t.lower().find(q.lower())
    if i < 0:
        return _h.escape(t[:width * 2]) + ("…" if len(t) > width * 2 else "")
    a, b = max(0, i - width), min(len(t), i + len(q) + width)
    return (("…" if a else "") + _h.escape(t[a:i]) + "<mark>" + _h.escape(t[i:i + len(q)]) + "</mark>"
            + _h.escape(t[i + len(q):b]) + ("…" if b < len(t) else ""))


def _reader_href(row, block=None):
    base = "/libraries/%s/chapters/%s/sections/%s" % (row["library_id"], row["chapter_id"], row["section_id"])
    return base + (("#block-" + block) if block else ("#topic-" + row["topic_id"]))


@bp.route("/search/all")
def search_all():
    """Topics, your notes & highlights, and flashcards in one search.
    ``kind`` = all | topics | notes | cards, ``chapter`` limits to one chapter."""
    import html as _h
    import re as _re
    q = (request.args.get("q") or "").strip()
    kind = request.args.get("kind", "all")
    chapter = request.args.get("chapter") or None
    out = {"q": q, "topics": [], "notes": [], "cards": []}
    if len(q) < 2:
        return jsonify(out)
    like = f"%{q}%"
    loc = ("SELECT t.id topic_id, COALESCE(e.title,t.title) topic_title, s.id section_id, s.title section_title, "
           "s.chapter_id, ch.title chapter_title, ch.library_id FROM topics t JOIN sections s ON s.id=t.section_id "
           "JOIN chapters ch ON ch.id=s.chapter_id LEFT JOIN topic_edits e ON e.topic_id=t.id ")
    chf = " AND s.chapter_id=?" if chapter else ""
    cha = [chapter] if chapter else []

    if kind in ("all", "topics"):
        toks = _re.findall(r"\w+", q, flags=_re.UNICODE)
        rows = []
        if toks:
            try:
                fts = " ".join('"%s"*' % t for t in toks)
                rows = g.db.execute(
                    "SELECT f.ref topic_id, snippet(search_fts,3,'\x02','\x03','…',12) snip FROM search_fts f "
                    "WHERE search_fts MATCH ? AND f.kind='topic'" + (" AND f.chapter_id=?" if chapter else "") +
                    " ORDER BY rank LIMIT 40", [fts] + cha).fetchall()
            except Exception:  # noqa: BLE001
                rows = []
        if not rows:
            rows = [{"topic_id": r["id"], "snip": None} for r in g.db.execute(
                "SELECT t.id FROM topics t JOIN sections s ON s.id=t.section_id LEFT JOIN topic_edits e ON e.topic_id=t.id "
                "WHERE (COALESCE(e.title,t.title) LIKE ? OR COALESCE(e.plain_text,t.plain_text) LIKE ?)" + chf + " LIMIT 40",
                [like, like] + cha)]
        for r in rows:
            l = g.db.execute(loc + "WHERE t.id=?", (r["topic_id"],)).fetchone()
            if not l:
                continue
            snip = (_h.escape(r["snip"]).replace("\x02", "<mark>").replace("\x03", "</mark>") if r["snip"] else "")
            out["topics"].append({"title": l["topic_title"], "where": f"{l['chapter_title']} · {l['section_title']}",
                                  "snippet": snip, "href": _reader_href(l)})

    if kind in ("all", "notes"):
        for r in g.db.execute(loc.replace("SELECT ", "SELECT n.plain_text body, n.updated_at at, ", 1).replace(
                "FROM topics t", "FROM topic_notes n JOIN topics t ON t.id=n.topic_id", 1) +
                "WHERE n.plain_text LIKE ?" + chf + " ORDER BY n.updated_at DESC LIMIT 30", [like] + cha):
            out["notes"].append({"type": "Topic note", "title": r["topic_title"], "where": f"{r['chapter_title']} · {r['section_title']}",
                                 "snippet": _snip(r["body"], q), "href": _reader_href(r)})
        for r in g.db.execute(loc.replace("SELECT ", "SELECT n.note_text, n.selected_text, n.start_block_id, ", 1).replace(
                "FROM topics t", "FROM inline_notes n JOIN topics t ON t.id=n.topic_id", 1) +
                "WHERE (n.note_text LIKE ? OR n.selected_text LIKE ?)" + chf + " LIMIT 30", [like, like] + cha):
            body = r["note_text"] if q.lower() in (r["note_text"] or "").lower() else r["selected_text"]
            out["notes"].append({"type": "Note on a passage", "title": r["topic_title"], "where": f"{r['chapter_title']} · {r['section_title']}",
                                 "snippet": _snip(body, q), "href": _reader_href(r, r["start_block_id"])})
        for r in g.db.execute(loc.replace("SELECT ", "SELECT h.selected_text, h.start_block_id, ", 1).replace(
                "FROM topics t", "FROM highlights h JOIN topics t ON t.id=h.topic_id", 1) +
                "WHERE h.selected_text LIKE ?" + chf + " LIMIT 30", [like] + cha):
            out["notes"].append({"type": "Highlight", "title": r["topic_title"], "where": f"{r['chapter_title']} · {r['section_title']}",
                                 "snippet": _snip(r["selected_text"], q), "href": _reader_href(r, r["start_block_id"])})

    if kind in ("all", "cards"):
        for r in g.db.execute(loc.replace("SELECT ", "SELECT c.front_text, c.back_text, ", 1).replace(
                "FROM topics t", "FROM cards c JOIN topics t ON t.id=c.topic_id", 1) +
                "WHERE (c.front_text LIKE ? OR c.back_text LIKE ?)" + chf + " LIMIT 30", [like, like] + cha):
            body = r["front_text"] if q.lower() in (r["front_text"] or "").lower() else r["back_text"]
            out["cards"].append({"type": "Library card", "title": r["topic_title"], "where": r["chapter_title"],
                                 "snippet": _snip(body, q),
                                 "href": "/flashcards/review?scope=topic&id=%s&title=%s" % (r["topic_id"], r["topic_title"] or "")})
        for r in g.db.execute(loc.replace("SELECT ", "SELECT m.front, m.back, ", 1).replace(
                "FROM topics t", "FROM my_cards m JOIN topics t ON t.id=m.topic_id", 1) +
                "WHERE (m.front LIKE ? OR m.back LIKE ?)" + chf + " LIMIT 30", [like, like] + cha):
            body = r["front"] if q.lower() in (r["front"] or "").lower() else r["back"]
            out["cards"].append({"type": "Your card", "title": r["topic_title"], "where": r["chapter_title"],
                                 "snippet": _snip(body, q),
                                 "href": "/flashcards/review?scope=topic&id=%s&title=%s" % (r["topic_id"], r["topic_title"] or "")})
    return jsonify(out)


# ------------------------------------------------------------- one day of study (new layout heatmap)
@bp.route("/day/<day>")
def day_detail(day):
    import re as _re
    if not _re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        return jsonify({"error": "bad day"}), 400
    log = g.db.execute("SELECT * FROM study_log WHERE day=?", (day,)).fetchone()
    done = g.db.execute(
        "SELECT p.topic_id, COALESCE(e.title,t.title) title, s.id section_id, s.title section_title, "
        "s.chapter_id, c.library_id FROM progress p JOIN topics t ON t.id=p.topic_id "
        "JOIN sections s ON s.id=t.section_id JOIN chapters c ON c.id=s.chapter_id "
        "LEFT JOIN topic_edits e ON e.topic_id=p.topic_id "
        "WHERE p.completed=1 AND date(p.completed_at,'localtime')=? ORDER BY p.completed_at LIMIT 50", (day,)).fetchall()
    # times are stored in UTC; the heatmap's days are your local days
    reviewed = g.db.execute(
        "SELECT COUNT(*) n FROM card_reviews WHERE date(last_reviewed_at,'localtime')=?", (day,)).fetchone()["n"]
    changes = g.db.execute(
        "SELECT label FROM changesets WHERE date(created_at,'localtime')=? AND kind NOT IN ('import') "
        "ORDER BY created_at DESC LIMIT 8", (day,)).fetchall()
    n_changes = g.db.execute("SELECT COUNT(*) n FROM changesets WHERE date(created_at,'localtime')=? "
                             "AND kind NOT IN ('import')", (day,)).fetchone()["n"]
    return jsonify({
        "day": day,
        "minutes": round(((log["credit_seconds"] if log else 0) or 0) / 60),
        "completed": [{"title": r["title"], "where": r["section_title"],
                       "href": "/libraries/%s/chapters/%s/sections/%s#topic-%s" % (r["library_id"], r["chapter_id"], r["section_id"], r["topic_id"])}
                      for r in done],
        "cards_last_reviewed": reviewed,
        "changes": [r["label"] for r in changes], "n_changes": n_changes,
    })
