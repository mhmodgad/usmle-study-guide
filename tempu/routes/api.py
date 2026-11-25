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
    rows = _cards_for_scope(scope, scope_id, limit=limit, order=order)
    out = [S.render_card(r) for r in rows]
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
    data = request.get_json(force=True)
    card_id = data.get("card_id")
    rating = int(data.get("rating", 3))
    if not card_id:
        abort(400)
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
    return jsonify({"ok": True, "review": upd})


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
        "reopened=excluded.reopened,completed_at=excluded.completed_at,"
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
            "completed_at=excluded.completed_at,last_opened_at=excluded.last_opened_at",
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
    data = request.get_json(force=True)
    body = data.get("body_html", "")
    plain = data.get("plain_text", "")
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
        "SELECT id, title, item_count FROM collections WHERE kind='personal' "
        "ORDER BY created_at DESC").fetchall()
    return jsonify({"collections": [dict(r) for r in rows]})


@bp.route("/collections", methods=["POST"])
def create_collection():
    d = request.get_json(force=True)
    cid = _uid()
    g.db.execute(
        "INSERT INTO collections(id,kind,title,description,exam_scope,item_count,share_state,"
        "created_at) VALUES(?,?,?,?,?,?,?,?)",
        (cid, "personal", d.get("title", "New collection"), d.get("description"),
         "step2ck", 0, "private", _now()))
    g.db.commit()
    return jsonify({"ok": True, "id": cid})


@bp.route("/collections/<cid>/items", methods=["POST"])
def add_collection_item(cid):
    d = request.get_json(force=True)
    g.db.execute(
        "INSERT INTO collection_items(collection_id,item_type,topic_id,section_id,chapter_id,"
        "entry_id,sort_order) VALUES(?,?,?,?,?,?,?)",
        (cid, d.get("item_type", "topic"), d.get("topic_id"), d.get("section_id"),
         d.get("chapter_id"), _uid(),
         g.db.execute("SELECT COUNT(*) n FROM collection_items WHERE collection_id=?",
                      (cid,)).fetchone()["n"]))
    g.db.execute("UPDATE collections SET item_count=item_count+1 WHERE id=?", (cid,))
    g.db.commit()
    return jsonify({"ok": True})


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
    d = request.get_json(force=True)
    day = d.get("day") or datetime.date.today().isoformat()
    eng = int(d.get("englishMinutes", 0)) * 60
    ara = int(d.get("arabicMinutes", 0)) * 60
    q = int(d.get("questionsAnswered", 0))
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
        (day, eng, ara, q, eng, int(credit)))
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
    items = []
    try:
        rows = g.db.execute(
            "SELECT ref, title, chapter_id, section_id, library_id, "
            "snippet(search_fts,3,'<mark>','</mark>','…',8) snip "
            "FROM search_fts WHERE search_fts MATCH ? ORDER BY rank LIMIT 20",
            (q + "*",)).fetchall()
        for r in rows:
            items.append(_search_item(r["ref"], r["title"], r["section_id"],
                                      r["chapter_id"], r["library_id"], r["snip"]))
    except Exception:
        like = f"%{q}%"
        rows = g.db.execute(
            "SELECT t.id ref, t.title, s.id section_id, s.chapter_id, c.library_id "
            "FROM topics t JOIN sections s ON t.section_id=s.id "
            "JOIN chapters c ON s.chapter_id=c.id "
            "WHERE t.title LIKE ? OR t.plain_text LIKE ? LIMIT 20", (like, like)).fetchall()
        for r in rows:
            items.append(_search_item(r["ref"], r["title"], r["section_id"],
                                      r["chapter_id"], r["library_id"], ""))
    return jsonify({"items": items})


def _search_item(topic_id, title, section_id, chapter_id, library_id, snip):
    chap = g.db.execute("SELECT title FROM chapters WHERE id=?", (chapter_id,)).fetchone()
    return {
        "id": topic_id, "title": title, "snippet": snip,
        "breadcrumb": ["USMLE STEP 2CK", chap["title"] if chap else ""],
        "href": f"/libraries/{library_id}/chapters/{chapter_id}/sections/{section_id}#topic-{topic_id}",
    }
