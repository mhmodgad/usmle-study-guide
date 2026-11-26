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
