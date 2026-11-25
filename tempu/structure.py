"""User changes to the library structure: chapters, sections and topics.

Everything the user does to the structure — create, rename, re-icon, move to
another parent, reorder, delete (to trash) and restore — is applied to the
content tables immediately AND recorded in ``struct_overrides``. Because the
content tables are rebuilt from the source JSON by ``tempu.loader``, the
loader calls :func:`replay` afterwards so the user's structure always wins.

One row per (kind, id) holds the *final state* the user chose, not a log:
    created   1 = the item was made by the user (it has no source JSON)
    parent_id chapter -> library, section -> chapter, topic -> section
    sort_order position among its siblings
    title / icon_path   overrides (NULL = keep the source value)
    deleted   1 = in the trash; payload keeps the deleted rows for restore
"""
import datetime
import json
import uuid

KINDS = {
    "library": ("libraries", None),
    "chapter": ("chapters", "library_id"),
    "section": ("sections", "chapter_id"),
    "topic": ("topics", "section_id"),
}
CHILD = {"library": "chapter", "chapter": "section", "section": "topic", "topic": None}


def _now():
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _table(kind):
    if kind not in KINDS:
        raise ValueError("bad kind")
    return KINDS[kind]


def _row(conn, kind, item_id):
    t, _ = _table(kind)
    return conn.execute(f"SELECT * FROM {t} WHERE id=?", (item_id,)).fetchone()


def _ovr(conn, kind, item_id):
    return conn.execute("SELECT * FROM struct_overrides WHERE kind=? AND id=?",
                        (kind, item_id)).fetchone()


def _upsert(conn, kind, item_id, **f):
    cur = _ovr(conn, kind, item_id)
    f["updated_at"] = _now()
    if cur:
        sets = ", ".join(f"{k}=?" for k in f)
        conn.execute(f"UPDATE struct_overrides SET {sets} WHERE kind=? AND id=?",
                     (*f.values(), kind, item_id))
    else:
        cols = ["kind", "id", *f.keys()]
        conn.execute(f"INSERT INTO struct_overrides({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                     (kind, item_id, *f.values()))


# ------------------------------------------------------------------ operations
def create(conn, kind, parent_id, title, after_id=None, icon_path=None):
    """Make a new chapter/section/topic under parent_id (after after_id, else at the end)."""
    t, pcol = _table(kind)
    new_id = str(uuid.uuid4())
    title = (title or "").strip() or {"chapter": "New chapter", "section": "New section",
                                      "topic": "New topic"}[kind]
    sibs = [r["id"] for r in conn.execute(
        f"SELECT id FROM {t} WHERE {pcol}=? ORDER BY sort_order, rowid", (parent_id,))]
    pos = sibs.index(after_id) + 1 if after_id in sibs else len(sibs)
    sibs.insert(pos, new_id)
    if kind == "chapter":
        conn.execute("INSERT INTO chapters(id,library_id,title,icon_path,sort_order) VALUES(?,?,?,?,?)",
                     (new_id, parent_id, title, icon_path, pos))
    elif kind == "section":
        conn.execute("INSERT INTO sections(id,chapter_id,title,icon_path,sort_order,total_words,total_topics) "
                     "VALUES(?,?,?,?,?,0,0)", (new_id, parent_id, title, icon_path, pos))
    else:
        conn.execute("INSERT INTO topics(id,section_id,title,sort_order,document_version,document_html,"
                     "plain_text,has_cards,updated_at) VALUES(?,?,?,?,1,?,?,0,?)",
                     (new_id, parent_id, title, pos,
                      '<div class="bn-block-outer" data-node-type="blockOuter" data-id="%s">'
                      '<div class="bn-block" data-node-type="blockContainer" data-id="%s">'
                      '<div class="bn-block-content" data-content-type="paragraph">'
                      '<p class="bn-inline-content"><br class="ProseMirror-trailingBreak"></p>'
                      '</div></div></div>' % (new_id, new_id), "", _now()))
    _upsert(conn, kind, new_id, created=1, parent_id=parent_id, title=title,
            icon_path=icon_path, sort_order=pos, deleted=0)
    _write_order(conn, kind, parent_id, sibs)
    return new_id


def rename(conn, kind, item_id, title):
    t, _ = _table(kind)
    title = (title or "").strip()
    if not title or not _row(conn, kind, item_id):
        return False
    conn.execute(f"UPDATE {t} SET title=? WHERE id=?", (title, item_id))
    _upsert(conn, kind, item_id, title=title)
    return True


def set_icon(conn, kind, item_id, icon_path):
    t, _ = _table(kind)
    if kind == "topic":
        conn.execute("UPDATE topics SET icon_url=? WHERE id=?", (icon_path, item_id))
    else:
        conn.execute(f"UPDATE {t} SET icon_path=? WHERE id=?", (icon_path or None, item_id))
    _upsert(conn, kind, item_id, icon_path=icon_path or "")   # "" = icon removed


def _write_order(conn, kind, parent_id, ordered_ids):
    t, pcol = _table(kind)
    for i, iid in enumerate(ordered_ids):
        conn.execute(f"UPDATE {t} SET sort_order=?, {pcol}=? WHERE id=?", (i, parent_id, iid))
        _upsert(conn, kind, iid, sort_order=i, parent_id=parent_id)


def move(conn, kind, item_id, parent_id, ordered_ids=None, index=None):
    """Put item under parent_id. Either give the parent's full new child order,
    or an index to insert at (default: end)."""
    t, pcol = _table(kind)
    if not _row(conn, kind, item_id):
        return False
    old = _row(conn, kind, item_id)[pcol]
    if ordered_ids is None:
        sibs = [r["id"] for r in conn.execute(
            f"SELECT id FROM {t} WHERE {pcol}=? AND id<>? ORDER BY sort_order, rowid",
            (parent_id, item_id))]
        index = len(sibs) if index is None else max(0, min(int(index), len(sibs)))
        sibs.insert(index, item_id)
        ordered_ids = sibs
    else:
        ordered_ids = [i for i in ordered_ids if _row(conn, kind, i)]
        if item_id not in ordered_ids:
            ordered_ids.append(item_id)
    _write_order(conn, kind, parent_id, ordered_ids)
    if old != parent_id:   # close the gap in the old parent
        rest = [r["id"] for r in conn.execute(
            f"SELECT id FROM {t} WHERE {pcol}=? ORDER BY sort_order, rowid", (old,))]
        _write_order(conn, kind, old, rest)
    return True


def _collect(conn, kind, item_id, acc):
    t, _ = _table(kind)
    r = _row(conn, kind, item_id)
    if not r:
        return
    acc.setdefault(t, []).append(dict(r))
    ck = CHILD[kind]
    if ck:
        ct, cpcol = _table(ck)
        for c in conn.execute(f"SELECT id FROM {ct} WHERE {cpcol}=?", (item_id,)).fetchall():
            _collect(conn, ck, c["id"], acc)


def _delete_rows(conn, payload):
    for t in ("topics", "sections", "chapters"):
        for r in payload.get(t, []):
            conn.execute(f"DELETE FROM {t} WHERE id=?", (r["id"],))
            if t == "topics":
                try:
                    conn.execute("DELETE FROM search_fts WHERE ref=? AND kind='topic'", (r["id"],))
                except Exception:  # noqa: BLE001
                    pass


def delete(conn, kind, item_id):
    """Move an item (and everything inside it) to the trash."""
    acc = {}
    _collect(conn, kind, item_id, acc)
    if not acc:
        return False
    _delete_rows(conn, acc)
    _upsert(conn, kind, item_id, deleted=1, deleted_at=_now(), payload=json.dumps(acc))
    return True


def _insert_rows(conn, payload):
    for t in ("chapters", "sections", "topics"):
        for r in payload.get(t, []):
            cols = list(r.keys())
            conn.execute(f"INSERT OR IGNORE INTO {t}({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                         tuple(r[c] for c in cols))


def restore(conn, kind, item_id):
    o = _ovr(conn, kind, item_id)
    if not o or not o["deleted"]:
        return False
    _insert_rows(conn, json.loads(o["payload"] or "{}"))
    _upsert(conn, kind, item_id, deleted=0, deleted_at=None, payload=None)
    return True


def purge(conn, kind, item_id):
    """Delete forever (only from the trash)."""
    o = _ovr(conn, kind, item_id)
    if not o or not o["deleted"]:
        return False
    if o["created"]:
        conn.execute("DELETE FROM struct_overrides WHERE kind=? AND id=?", (kind, item_id))
        # user-made children lose their parent: drop their overrides too
        for t, k in (("topics", "topic"), ("sections", "section"), ("chapters", "chapter")):
            for r in json.loads(o["payload"] or "{}").get(t, []):
                conn.execute("DELETE FROM struct_overrides WHERE kind=? AND id=? AND created=1", (k, r["id"]))
    else:
        conn.execute("UPDATE struct_overrides SET payload=NULL, deleted=2 WHERE kind=? AND id=?",
                     (kind, item_id))
    return True


def trash(conn):
    rows = conn.execute("SELECT kind,id,title,deleted_at,payload FROM struct_overrides "
                        "WHERE deleted=1 ORDER BY deleted_at DESC").fetchall()
    out = []
    for r in rows:
        p = json.loads(r["payload"] or "{}")
        t, _ = _table(r["kind"])
        first = (p.get(t) or [{}])[0]
        out.append({"kind": r["kind"], "id": r["id"], "deleted_at": r["deleted_at"],
                    "title": r["title"] or first.get("title") or "(untitled)",
                    "contains": {k: len(v) for k, v in p.items()}})
    return out


# ------------------------------------------------------------------ replay
def replay(conn):
    """Re-apply every recorded structure change after the content tables were rebuilt."""
    try:
        rows = conn.execute("SELECT * FROM struct_overrides ORDER BY "
                            "CASE kind WHEN 'library' THEN -1 WHEN 'chapter' THEN 0 WHEN 'section' THEN 1 ELSE 2 END").fetchall()
    except Exception:  # noqa: BLE001 - table not there yet
        return 0
    n = 0
    # 1) user-created items (unless purged)
    for o in rows:
        if not o["created"] or o["deleted"] == 2 or o["kind"] == "library":
            continue
        k = o["kind"]
        t, pcol = _table(k)
        if _row(conn, k, o["id"]):
            continue
        if o["deleted"] == 1:
            continue    # stays in the trash (its payload restores it)
        if k == "chapter":
            conn.execute("INSERT OR IGNORE INTO chapters(id,library_id,title,icon_path,sort_order) VALUES(?,?,?,?,?)",
                         (o["id"], o["parent_id"], o["title"], o["icon_path"], o["sort_order"] or 0))
        elif k == "section":
            conn.execute("INSERT OR IGNORE INTO sections(id,chapter_id,title,icon_path,sort_order,total_words,total_topics) "
                         "VALUES(?,?,?,?,?,0,0)", (o["id"], o["parent_id"], o["title"], o["icon_path"], o["sort_order"] or 0))
        else:
            conn.execute("INSERT OR IGNORE INTO topics(id,section_id,title,sort_order,document_version,document_html,"
                         "plain_text,has_cards,updated_at) VALUES(?,?,?,?,1,'','',0,?)",
                         (o["id"], o["parent_id"], o["title"], o["sort_order"] or 0, o["updated_at"]))
        n += 1
    # 2) moves / order / renames / icons
    for o in rows:
        if o["deleted"]:
            continue
        k = o["kind"]
        t, pcol = _table(k)
        if not _row(conn, k, o["id"]):
            continue
        sets, vals = [], []
        if o["parent_id"] and pcol:
            sets.append(f"{pcol}=?"); vals.append(o["parent_id"])
        if o["sort_order"] is not None:
            sets.append("sort_order=?"); vals.append(o["sort_order"])
        if o["title"]:
            sets.append("title=?"); vals.append(o["title"])
        if o["icon_path"] is not None and not (o["created"] and o["icon_path"] == ""):
            sets.append("icon_url=?" if k == "topic" else "icon_path=?"); vals.append(o["icon_path"] or None)
        if sets:
            conn.execute(f"UPDATE {t} SET {', '.join(sets)} WHERE id=?", (*vals, o["id"]))
            n += 1
    # 3) deletions (content items come back on every rebuild; remove them again)
    for o in rows:
        if not o["deleted"]:
            continue
        acc = {}
        _collect(conn, o["kind"], o["id"], acc)
        if acc:
            _delete_rows(conn, acc)
            if o["deleted"] == 1 and not o["created"]:
                conn.execute("UPDATE struct_overrides SET payload=? WHERE kind=? AND id=?",
                             (json.dumps(acc), o["kind"], o["id"]))
            n += 1
    conn.commit()
    return n
