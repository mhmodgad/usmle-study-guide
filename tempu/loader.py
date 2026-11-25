"""Build the SQLite content database from the captured ../content JSON.

Reads the library structure, every section's topic documents, all STEP 2CK
flashcards, the official + personal collections, and the captured user state,
renders content to HTML with the verified BlockNote / Lexical renderers, and
writes everything into data/tempu.db.

Usage:
    python -m tempu.loader [--content PATH] [--db PATH] [--step1] [--reset]

Idempotent: with --reset (default) it drops and rebuilds the content tables but
*preserves* user state unless --wipe-user is given.
"""
import argparse
import datetime as _dt
import json
import os
import re
import sys

from . import db as dbmod
from . import structure as structmod
from .render import bn_render, card_render

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)


def _resolve_content():
    v = os.environ.get("TEMPU_CONTENT")
    if v:
        return v
    in_project = os.path.join(PROJECT, "local", "content")
    if os.path.isdir(in_project):
        return in_project
    return os.path.join(os.path.dirname(PROJECT), "content")


DEFAULT_CONTENT = _resolve_content()

LIBRARY_TITLES = {
    "8f7b96f9-7778-4908-af76-a8ad722cd68a": ("USMLE STEP 2CK", "step2ck", 0, 0),
    "2d133996-90f7-48ee-97c8-8c0c9fcfa973": ("USMLE STEP 1", "step1", 1, 1),
}
STEP2CK = "8f7b96f9-7778-4908-af76-a8ad722cd68a"
STEP1 = "2d133996-90f7-48ee-97c8-8c0c9fcfa973"

SECTION_HREF_RE = re.compile(r"/sections/([0-9a-f-]{36})")


# ----------------------------------------------------------------- media mapping
def _web_media_from_url(url):
    """media.tempusmle.com/topics/<tid>/<file>  ->  /assets/media/<tid>/<file>."""
    if not url or not isinstance(url, str):
        return url
    if "media.tempusmle.com" not in url or "/topics/" not in url:
        return url  # youtube / other stays remote
    tail = url.split("/topics/", 1)[-1].split("?")[0]
    return "/assets/media/" + tail


def _web_media_from_objectkey(object_key):
    """objectKey 'topics/<tid>/<file>'  ->  /assets/media/<tid>/<file>."""
    if not object_key:
        return None
    key = object_key
    if key.startswith("topics/"):
        key = key[len("topics/"):]
    return "/assets/media/" + key


# Point the reusable renderers at web-absolute asset paths.
bn_render.media_src = _web_media_from_url


def _now():
    return _dt.datetime.utcnow().isoformat() + "Z"


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ----------------------------------------------------------------- content load
def load_structure(conn, content):
    struct_path = os.path.join(content, "library-step2ck-structure.json")
    struct = load_json(struct_path)
    lib_id = struct["libraryId"]
    study = struct.get("studyStatus") or {}

    for lid, (title, scope, sort_order, locked) in LIBRARY_TITLES.items():
        conn.execute(
            "INSERT OR REPLACE INTO libraries(id,title,slug,exam_scope,sort_order,locked) "
            "VALUES(?,?,?,?,?,?)",
            (lid, title, scope, scope, sort_order, locked),
        )

    for ci, chap in enumerate(struct.get("chapters") or []):
        conn.execute(
            "INSERT OR REPLACE INTO chapters"
            "(id,library_id,title,slug,icon_path,icon_alt,is_public_sample,sort_order) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (chap["id"], lib_id, chap.get("title"), chap.get("slug"),
             chap.get("iconPath"), chap.get("iconAlt"),
             1 if chap.get("isPublicSample") else 0,
             chap.get("sortOrder", ci)),
        )
        for si, sec in enumerate(chap.get("sections") or []):
            st = study.get(sec["id"]) or {}
            conn.execute(
                "INSERT OR REPLACE INTO sections"
                "(id,chapter_id,title,slug,icon_path,icon_alt,is_public_sample,sort_order,"
                " total_words,total_topics) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (sec["id"], chap["id"], sec.get("title"), sec.get("slug"),
                 sec.get("iconPath"), sec.get("iconAlt"),
                 1 if sec.get("isPublicSample") else 0, si,
                 st.get("totalWords", 0), st.get("totalTopics", 0)),
            )
    conn.commit()
    return lib_id, study


def load_sections(conn, content):
    sections_dir = os.path.join(content, "sections")
    if not os.path.isdir(sections_dir):
        print("  ! no sections dir:", sections_dir)
        return 0, 0
    nsec = ntop = 0
    known = {r[0] for r in conn.execute("SELECT id FROM sections")}
    for sid in sorted(os.listdir(sections_dir)):
        sj = os.path.join(sections_dir, sid, "section.json")
        if not os.path.isfile(sj):
            continue
        try:
            data = load_json(sj)
        except Exception as e:  # noqa: BLE001
            print("  ! bad section json", sid, e)
            continue
        primary = (data.get("payload") or {}).get("primary") or {}
        section = primary.get("section") or {}
        secid = data.get("sectionId") or section.get("id") or sid
        # ensure the section row exists even if it was absent from the structure
        if secid not in known:
            conn.execute(
                "INSERT OR IGNORE INTO sections(id,chapter_id,title,slug) VALUES(?,?,?,?)",
                (secid, data.get("chapterId"), data.get("sectionTitle"), data.get("slug")),
            )
            known.add(secid)
        nxt = primary.get("nextSection") or {}
        nxt_id = None
        if nxt.get("href"):
            m = SECTION_HREF_RE.search(nxt["href"])
            nxt_id = m.group(1) if m else None
        if nxt_id:
            conn.execute("UPDATE sections SET next_section_id=? WHERE id=?", (nxt_id, secid))
        fc_ids = set(primary.get("flashcardTopicIds") or [])
        topics = primary.get("topics") or []
        for ti, t in enumerate(topics):
            tid = t.get("id")
            if not tid:
                continue
            doc = t.get("document")
            html = bn_render.render_document(doc)
            plain = _plain_from_blocknote(doc)
            conn.execute(
                "INSERT OR REPLACE INTO topics"
                "(id,section_id,title,sort_order,document_version,icon_url,document_html,"
                " plain_text,has_cards,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (tid, secid, t.get("title"), ti, t.get("documentVersion", 1),
                 t.get("iconUrl"), html, plain,
                 1 if tid in fc_ids else 0, t.get("updatedAt")),
            )
            ntop += 1
        nsec += 1
    conn.commit()
    return nsec, ntop


def rerender_documents(conn, content=None, quiet=False):
    """Re-render every stored topic's reader HTML from the section JSON files.

    Touches only topics.document_html / plain_text (no user state, no other
    content), so it is safe to run on an existing database. Records the
    renderer version in meta so the app knows the stored HTML is current.
    """
    content = content or DEFAULT_CONTENT
    sections_dir = os.path.join(content, "sections")
    n = 0
    if os.path.isdir(sections_dir):
        for sid in sorted(os.listdir(sections_dir)):
            sj = os.path.join(sections_dir, sid, "section.json")
            if not os.path.isfile(sj):
                continue
            try:
                data = load_json(sj)
            except Exception:  # noqa: BLE001
                continue
            primary = (data.get("payload") or {}).get("primary") or {}
            for t in primary.get("topics") or []:
                tid = t.get("id")
                if not tid:
                    continue
                doc = t.get("document")
                conn.execute("UPDATE topics SET document_html=?, plain_text=? WHERE id=?",
                             (bn_render.render_document(doc), _plain_from_blocknote(doc), tid))
                n += 1
    else:
        if not quiet:
            print("  ! no sections dir:", sections_dir)
        return 0
    conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('render_version',?)",
                 (str(bn_render.RENDER_VERSION),))
    conn.commit()
    if not quiet:
        print(f"  re-rendered {n} topic documents (renderer v{bn_render.RENDER_VERSION})")
    return n


def ensure_render_current(db_path=None, content=None):
    """Re-render stored topic HTML once after a renderer upgrade."""
    try:
        conn = dbmod.connect(db_path)
        try:
            row = conn.execute("SELECT value FROM meta WHERE key='render_version'").fetchone()
        except Exception:  # noqa: BLE001 - no meta table yet (DB not built)
            conn.close()
            return False
        if row and str(row[0]) == str(bn_render.RENDER_VERSION):
            conn.close()
            return False
        if not conn.execute("SELECT 1 FROM topics LIMIT 1").fetchone():
            conn.close()
            return False
        print("Updating stored topic documents for the new reader (one time)…")
        rerender_documents(conn, content)
        conn.close()
        return True
    except Exception as e:  # noqa: BLE001 - never block the app from starting
        print("  ! could not re-render topic documents:", e)
        return False


_WS = re.compile(r"\s+")


def _plain_from_blocknote(doc):
    out = []

    def walk(node):
        if isinstance(node, list):
            for x in node:
                walk(x)
            return
        if not isinstance(node, dict):
            return
        c = node.get("content")
        if isinstance(c, list):
            for run in c:
                if isinstance(run, dict) and run.get("text"):
                    out.append(run["text"])
                elif isinstance(run, dict) and run.get("type") == "link":
                    for r2 in run.get("content") or []:
                        if isinstance(r2, dict) and r2.get("text"):
                            out.append(r2["text"])
        elif isinstance(c, dict):  # table
            for row in c.get("rows") or []:
                for cell in row.get("cells") or []:
                    walk(cell if isinstance(cell, dict) else {"content": cell})
        for ch in node.get("children") or []:
            walk(ch)

    walk(doc)
    txt = " ".join(out).replace("​", "")
    return _WS.sub(" ", txt).strip()


def load_cards(conn, content, include_step1=False):
    total = 0
    sets = [("step2ck", STEP2CK)]
    if include_step1:
        sets.append(("step1", STEP1))
    for sub, lib_id in sets:
        d = os.path.join(content, "cards", sub)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".json"):
                continue
            data = load_json(os.path.join(d, fn))
            chapter_id = data.get("chapterId")
            for topic in data.get("topics") or []:
                topic_id = topic.get("t")
                for order, row in enumerate(topic.get("rows") or []):
                    front = row.get("front_document")
                    back = row.get("back_document")
                    conn.execute(
                        "INSERT OR REPLACE INTO cards"
                        "(id,topic_id,note_id,chapter_id,library_id,ordinal,kind,is_beta,"
                        " sort_order,front_json,back_json,front_text,back_text) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (row.get("card_id"), topic_id or row.get("topic_id"),
                         row.get("note_id"), chapter_id, lib_id,
                         row.get("ordinal"), row.get("kind"),
                         1 if row.get("is_beta") else 0, order,
                         json.dumps(front) if front else None,
                         json.dumps(back) if back else None,
                         card_render.visible_text(front) if front else "",
                         card_render.visible_text(back) if back else ""),
                    )
                    total += 1
    conn.commit()
    return total


def load_collections(conn, content):
    # official list
    off_path = os.path.join(content, "collections-official.json")
    personal_path = os.path.join(content, "collections-personal.json")
    coll_dir = os.path.join(content, "collections")

    if os.path.isfile(off_path):
        for c in load_json(off_path):
            conn.execute(
                "INSERT OR REPLACE INTO collections"
                "(id,kind,title,description,exam_scope,library_id,library_title,item_count,"
                " share_state,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (c["collectionId"], "official", c.get("title"), c.get("description"),
                 c.get("examScope"), c.get("libraryId"), c.get("libraryTitle"),
                 c.get("entryCount", 0), None, None),
            )
    if os.path.isfile(personal_path):
        p = load_json(personal_path)
        for c in p.get("collections") or []:
            conn.execute(
                "INSERT OR REPLACE INTO collections"
                "(id,kind,title,description,exam_scope,library_id,library_title,item_count,"
                " share_state,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (c["id"], "personal", c.get("title"), c.get("description"),
                 p.get("activeScope"), None, None, c.get("itemCount", 0),
                 c.get("shareState"), c.get("createdAt")),
            )
    # items from parsed per-collection files
    nitems = 0
    if os.path.isdir(coll_dir):
        for fn in sorted(os.listdir(coll_dir)):
            if not fn.endswith(".json"):
                continue
            data = load_json(os.path.join(coll_dir, fn))
            cid = data.get("activeId")
            items = data.get("items") or []
            if not cid:
                continue
            conn.execute("DELETE FROM collection_items WHERE collection_id=?", (cid,))
            for order, it in enumerate(items):
                href = it.get("href") or ""
                m = SECTION_HREF_RE.search(href)
                section_id = m.group(1) if m else it.get("sectionId")
                topic_id = None
                if "#topic-" in href:
                    topic_id = href.split("#topic-", 1)[-1]
                conn.execute(
                    "INSERT INTO collection_items"
                    "(collection_id,item_type,topic_id,section_id,chapter_id,entry_id,sort_order)"
                    " VALUES(?,?,?,?,?,?,?)",
                    (cid, it.get("itemType"), topic_id, section_id,
                     it.get("chapterId"), it.get("entryId"), order),
                )
                nitems += 1
    # personal collection detail files (My HY etc.):
    # content/collection-personal-detail-*.json  -> initialResult.data[]
    for fn in sorted(os.listdir(content)):
        if not (fn.startswith("collection-personal-detail-") and fn.endswith(".json")):
            continue
        data = load_json(os.path.join(content, fn))
        ir = data.get("initialResult") or {}
        active = ir.get("activeCollection") or {}
        cid = active.get("id")
        rows = ir.get("data") or []
        if not cid:
            continue
        conn.execute("DELETE FROM collection_items WHERE collection_id=?", (cid,))
        for order, it in enumerate(rows):
            itype = it.get("type")
            topic_id = it.get("targetId") if itype == "topic" else None
            section_id = it.get("sectionId") or (
                it.get("targetId") if itype == "section" else None)
            conn.execute(
                "INSERT INTO collection_items"
                "(collection_id,item_type,topic_id,section_id,chapter_id,entry_id,sort_order)"
                " VALUES(?,?,?,?,?,?,?)",
                (cid, itype, topic_id, section_id, it.get("chapterId"),
                 it.get("id"), order),
            )
            nitems += 1
    conn.commit()
    return nitems


# ----------------------------------------------------------------- user state seed
def seed_user_state(conn, content, wipe=False):
    if wipe:
        for t in ("progress", "highlights", "inline_notes", "topic_notes"):
            conn.execute(f"DELETE FROM {t}")
    ustate_path = os.path.join(content, "user-topic-state.json")
    if os.path.isfile(ustate_path):
        u = load_json(ustate_path)
        for tid, st in u.items():
            # only seed rows that don't already exist (preserve live edits)
            exists = conn.execute("SELECT 1 FROM progress WHERE topic_id=?", (tid,)).fetchone()
            if not exists:
                conn.execute(
                    "INSERT INTO progress(topic_id,completed,reopened,completed_at) "
                    "VALUES(?,?,?,?)",
                    (tid, 1 if st.get("completed") else 0, st.get("reopened", 0),
                     _now() if st.get("completed") else None),
                )
            for h in st.get("highlights") or []:
                conn.execute(
                    "INSERT OR REPLACE INTO highlights"
                    "(id,topic_id,color,selected_text,prefix_text,suffix_text,start_block_id,"
                    " end_block_id,start_offset,end_offset,document_version,created_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (h.get("id"), tid, h.get("color", "yellow"), h.get("selected_text"),
                     h.get("prefix_text"), h.get("suffix_text"), h.get("start_block_id"),
                     h.get("end_block_id"), h.get("start_offset"), h.get("end_offset"),
                     h.get("document_version"), _now()),
                )
            for n in st.get("inlineNotes") or []:
                conn.execute(
                    "INSERT OR REPLACE INTO inline_notes"
                    "(id,topic_id,note_text,selected_text,prefix_text,suffix_text,start_block_id,"
                    " end_block_id,start_offset,end_offset,document_version,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (n.get("id"), tid, n.get("note_text"), n.get("selected_text"),
                     n.get("prefix_text"), n.get("suffix_text"), n.get("start_block_id"),
                     n.get("end_block_id"), n.get("start_offset"), n.get("end_offset"),
                     n.get("document_version"), _now(), _now()),
                )
    # topic-note previews from the captured notes page
    notes_path = os.path.join(content, "notes-page-payload.json")
    if os.path.isfile(notes_path):
        np = load_json(notes_path)
        for n in ((np.get("initialData") or {}).get("notes") or []):
            if n.get("kind") != "topic":
                continue
            tid = n.get("topicId")
            if not tid:
                continue
            exists = conn.execute("SELECT 1 FROM topic_notes WHERE topic_id=?", (tid,)).fetchone()
            if exists:
                continue
            preview = n.get("previewText") or ""
            body = "".join(f"<p>{_esc(line)}</p>" for line in preview.split("\n") if line.strip())
            conn.execute(
                "INSERT INTO topic_notes(topic_id,body_html,plain_text,updated_at) VALUES(?,?,?,?)",
                (tid, body, preview, n.get("lastEditedAt") or n.get("updatedAt")),
            )
    conn.commit()


def seed_study_log(conn, content):
    """Approximate the consistency log from each section's lastOpenedAt (1 unit / day)."""
    if conn.execute("SELECT 1 FROM study_log LIMIT 1").fetchone():
        return
    struct_path = os.path.join(content, "library-step2ck-structure.json")
    if not os.path.isfile(struct_path):
        return
    study = (load_json(struct_path).get("studyStatus") or {})
    per_day = {}
    for st in study.values():
        ts = st.get("lastOpenedAt")
        if not ts:
            continue
        day = ts[:10]
        per_day[day] = per_day.get(day, 0) + max(1, round((st.get("completedWords", 0) or 0) / 225))
    for day, units in sorted(per_day.items()):
        secs = units * 15 * 60  # 1 unit = 15 min english video
        conn.execute(
            "INSERT OR REPLACE INTO study_log"
            "(day,english_video_seconds,arabic_video_seconds,questions_answered,"
            " app_seconds,credit_seconds) VALUES(?,?,?,?,?,?)",
            (day, secs, 0, 0, secs, secs),
        )
    conn.commit()


DEFAULT_SETTINGS = {
    "dailyStudyGoalUnits": "8",
    "targetExamScope": "step2ck",
    "readerTextSize": "15",
    "readerSpacing": "default",
    "showVideoReferences": "true",
    "theme": "dark",
    "displayName": "Mohamed Atef",
    "initials": "MA",
}


def seed_settings(conn):
    for k, v in DEFAULT_SETTINGS.items():
        conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
    conn.commit()


# Chapters pinned on the live account (Quick access): Musculoskeletal,
# Ophthalmology, Infectious Disease.
PINNED_CHAPTERS = [
    "8a2cbe44-6396-44c0-8c1b-64b2aec7b3c6",  # Musculoskeletal
    "a6719121-b2dc-4e8a-95a9-c60d02d29463",  # Ophthalmology
    "1cc4b83a-b456-41f3-b930-7f974ed2f796",  # Infectious Disease
]

HY_DECK_FILE = os.path.join(os.path.dirname(__file__), "data", "hy_deck.json")
STEP2CK_LIB = "8f7b96f9-7778-4908-af76-a8ad722cd68a"


def seed_pins(conn):
    n = 0
    for cid in PINNED_CHAPTERS:
        if conn.execute("SELECT 1 FROM chapters WHERE id=?", (cid,)).fetchone():
            conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",
                         ("pin:%s" % cid, "1"))
            n += 1
    conn.commit()
    return n


def _lexical_side(text):
    """Wrap plain text (newline-separated) in the Lexical 'tempu-flashcard-side' shape
    that card_render understands, so a user-created card renders like any other."""
    children = []
    for line in (text or "").split("\n"):
        line = line.strip()
        if line:
            children.append({"type": "paragraph",
                             "children": [{"type": "text", "text": line, "format": 0}]})
        else:
            children.append({"type": "paragraph", "children": []})
    if not children:
        children = [{"type": "paragraph", "children": []}]
    return [{"kind": "tempu-flashcard-side",
             "editorState": {"root": {"type": "root", "children": children}}}]


def seed_decks(conn):
    """Replicate the user's personal 'HY' deck and its 7 user-created cards."""
    if not os.path.isfile(HY_DECK_FILE):
        return 0
    data = load_json(HY_DECK_FILE)
    d = data["deck"]
    conn.execute(
        "INSERT OR IGNORE INTO decks(id,name,color_key,parent_deck_id,created_at) "
        "VALUES(?,?,?,?,?)", (d["id"], d["name"], d["color_key"], None, _now()))
    n = 0
    for order, c in enumerate(data.get("cards") or []):
        cid = c["id"]
        front_doc = _lexical_side(c.get("front"))
        back_doc = _lexical_side(c.get("back")) if c.get("back") else None
        conn.execute(
            "INSERT OR REPLACE INTO cards"
            "(id,topic_id,note_id,chapter_id,library_id,ordinal,kind,is_beta,sort_order,"
            " front_json,back_json,front_text,back_text) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (cid, "user-hy-deck", None, None, STEP2CK_LIB, None, "basic", 0, order,
             json.dumps(front_doc), json.dumps(back_doc) if back_doc else None,
             c.get("front", ""), c.get("back", "")))
        conn.execute(
            "INSERT OR IGNORE INTO deck_cards(deck_id,card_id,added_at) VALUES(?,?,?)",
            (d["id"], cid, _now()))
        # SRS state: 'new' -> no review row; 'learning' -> a learning row not yet due
        if c.get("state") == "learning":
            due = (_dt.datetime.utcnow() + _dt.timedelta(days=1)).replace(microsecond=0).isoformat() + "Z"
            conn.execute(
                "INSERT OR REPLACE INTO card_reviews"
                "(card_id,state,reps,lapses,ease,interval_days,due_at,last_rating,last_reviewed_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (cid, "learning", 0, 0, 2.5, 0, due, None, _now()))
        n += 1
    conn.commit()
    return n


def build_search(conn):
    if not dbmod.init_search(conn):
        print("  ! FTS5 unavailable; search will use LIKE fallback")
        return
    conn.execute("DELETE FROM search_fts")
    rows = conn.execute(
        "SELECT t.id,t.title,t.plain_text,s.chapter_id,t.section_id,c.library_id "
        "FROM topics t JOIN sections s ON t.section_id=s.id "
        "JOIN chapters c ON s.chapter_id=c.id"
    ).fetchall()
    conn.executemany(
        "INSERT INTO search_fts(ref,kind,title,body,library_id,chapter_id,section_id) "
        "VALUES(?,?,?,?,?,?,?)",
        [(r["id"], "topic", r["title"] or "", r["plain_text"] or "",
          r["library_id"], r["chapter_id"], r["section_id"]) for r in rows],
    )
    conn.commit()


def _esc(s):
    import html as H
    return H.escape(s or "", quote=False)


def update_has_cards(conn):
    conn.execute(
        "UPDATE topics SET has_cards=1 WHERE id IN (SELECT DISTINCT topic_id FROM cards)"
    )
    conn.commit()


def reset_content(conn):
    for t in ("collection_items", "collections", "cards", "topics",
              "sections", "chapters", "libraries"):
        conn.execute(f"DELETE FROM {t}")
    conn.commit()


def build(content=DEFAULT_CONTENT, db_path=None, include_step1=False,
          wipe_user=False, reset=True):
    conn = dbmod.connect(db_path)
    dbmod.init_schema(conn)
    if reset:
        print("Resetting content tables…")
        reset_content(conn)
    print("Content dir:", content)
    print("Loading structure…")
    load_structure(conn, content)
    print("Loading sections + topic documents…")
    nsec, ntop = load_sections(conn, content)
    print(f"  sections={nsec} topics={ntop}")
    print("Loading flashcards…")
    ncards = load_cards(conn, content, include_step1=include_step1)
    print(f"  cards={ncards}")
    update_has_cards(conn)
    print("Loading collections…")
    nitems = load_collections(conn, content)
    print(f"  collection items={nitems}")
    print("Seeding user state…")
    seed_user_state(conn, content, wipe=wipe_user)
    seed_study_log(conn, content)
    seed_settings(conn)
    npins = seed_pins(conn)
    ndeck = seed_decks(conn)
    print(f"  pins={npins}  deck cards matched={ndeck}")
    dbmod.ensure_user_tables(conn)
    nrep = structmod.replay(conn)
    if nrep:
        print(f"  re-applied {nrep} of your structure changes (chapters/sections/topics)")
    print("Building search index…")
    build_search(conn)
    conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('built_at',?)", (_now(),))
    conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('render_version',?)",
                 (str(bn_render.RENDER_VERSION),))
    conn.commit()
    # summary
    counts = {}
    for t in ("libraries", "chapters", "sections", "topics", "cards",
              "collections", "collection_items", "progress", "highlights",
              "inline_notes", "topic_notes"):
        counts[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    print("DB summary:", json.dumps(counts))
    conn.close()
    return counts


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build the TEMP-U local database")
    ap.add_argument("--content", default=DEFAULT_CONTENT)
    ap.add_argument("--db", default=None)
    ap.add_argument("--step1", action="store_true", help="also load STEP 1 cards")
    ap.add_argument("--wipe-user", action="store_true", help="discard existing user state and reseed")
    ap.add_argument("--no-reset", action="store_true", help="do not clear content tables first")
    ap.add_argument("--rerender", action="store_true",
                    help="only re-render the stored topic documents (keeps everything else)")
    args = ap.parse_args(argv)
    if args.rerender:
        conn = dbmod.connect(args.db)
        dbmod.init_schema(conn)
        rerender_documents(conn, args.content)
        conn.close()
        return
    build(content=args.content, db_path=args.db, include_step1=args.step1,
          wipe_user=args.wipe_user, reset=not args.no_reset)


if __name__ == "__main__":
    main()
