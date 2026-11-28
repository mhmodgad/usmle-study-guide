"""Change journal: every change you make is recorded, so it can be undone,
redone, inspected and restored.

How it works
------------
Code that changes your content wraps the change in ``Change``::

    with history.Change(conn, "Renamed section 'A' to 'B'", kind="structure",
                        scope=("section", sid)) as ch:
        structure.rename(conn, "section", sid, "B")
    ch.id, ch.label          # the changeset, for the "Undo" toast

While a Change is open, per-connection TEMP triggers record the before/after
state of every row written in the journaled tables (``TRACKED`` below), in
both base.db (the served structure) and user.db (your overrides and edits).
When the block ends, the recorded rows are folded into ONE revision per row
(first "before", last "after") and stored with a changeset, in the same
transaction as the change itself. Nothing has to describe its own undo.

Undo writes each row's "before" back (and redo its "after") inside a new
changeset, so history only grows and an undo can itself be undone. Fields
changed again after the change being undone are kept, and reported.

Study state (progress, highlights, reviews...) is not journaled: it is backed
up, but has no undo.
"""
import datetime
import hashlib
import json
import os
import time
import zlib

# table -> (schema, primary key columns, columns NOT recorded on UPDATE)
TRACKED = {
    "libraries":        ("base", ("id",), ()),
    "chapters":         ("base", ("id",), ()),
    "sections":         ("base", ("id",), ()),
    "topics":           ("base", ("id",), ("document_html", "plain_text")),
    "struct_overrides": ("main", ("kind", "id"), ()),
    "topic_edits":      ("main", ("topic_id",), ()),
    "my_cards":         ("main", ("id",), ()),
    "deck_cards":       ("main", ("deck_id", "card_id"), ()),
}
IGNORE_IN_COMPARE = {"updated_at"}
INLINE_LIMIT = 1500          # revision payloads larger than this go to doc_texts
COALESCE_SECONDS = 120       # autosaves closer together than this merge into one changeset
COALESCE_MAX_SPAN = 600      # ...but one merged entry never covers more than 10 minutes of editing
NOT_UNDOABLE = {"import"}


def _now():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _ts(iso):
    return datetime.datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()


def new_id(at=None, offset=0):
    """Time-sortable id: 12 hex digits of milliseconds + 8 random hex digits.
    ``at`` (ISO time) dates the id, for entries imported from the past."""
    ms = int(time.time() * 1000)
    if at:
        try:
            ms = int(datetime.datetime.fromisoformat(str(at).replace("Z", "+00:00")).timestamp() * 1000)
        except ValueError:
            pass
    return "%012x%s" % (ms + offset, os.urandom(4).hex())


def _next_id(conn):
    """A new changeset id that sorts after every existing one. Undo/redo
    "latest" go by id order, so two changes in the same millisecond (random
    tail) or a clock that was set back must never put a new change before an
    older one."""
    cid = new_id()
    last = conn.execute("SELECT MAX(id) FROM changesets").fetchone()[0]
    if last and cid <= last:
        try:
            cid = "%012x%s" % (int(last[:12], 16) + 1, os.urandom(4).hex())
        except ValueError:
            pass
    return cid


# ------------------------------------------------------------------ triggers
_TRIGGER_SQL = {}


def _columns(conn, schema, table):
    try:
        return [r[1] for r in conn.execute(f"PRAGMA {schema}.table_info({table})")]
    except Exception:  # noqa: BLE001
        return []


def install(conn):
    """Create the TEMP capture table + triggers on this connection (cheap, idempotent)."""
    conn.execute("CREATE TEMP TABLE IF NOT EXISTS _cap("
                 "seq INTEGER PRIMARY KEY AUTOINCREMENT, tbl TEXT, op TEXT, pk TEXT, old TEXT, new TEXT)")
    conn.execute("CREATE TEMP TABLE IF NOT EXISTS _cap_on(v INTEGER)")
    if not conn.execute("SELECT 1 FROM _cap_on").fetchone():
        conn.execute("INSERT INTO _cap_on VALUES(0)")
    for table, (schema, pk, skip_upd) in TRACKED.items():
        cols = _columns(conn, schema, table)
        if not cols:
            continue                      # base.db not built yet
        key = (schema, table, tuple(cols))
        sql = _TRIGGER_SQL.get(key)
        if sql is None:
            def obj(ref, use):
                return "json_object(" + ",".join(f"'{c}',{ref}.\"{c}\"" for c in use) + ")"
            pkj = lambda ref: "json_array(" + ",".join(f"{ref}.\"{c}\"" for c in pk) + ")"  # noqa: E731
            upd_cols = [c for c in cols if c not in skip_upd]
            when = "WHEN (SELECT v FROM _cap_on)=1"
            sql = [
                f"CREATE TEMP TRIGGER IF NOT EXISTS _cap_{table}_i AFTER INSERT ON {schema}.{table} {when} "
                f"BEGIN INSERT INTO _cap(tbl,op,pk,old,new) VALUES('{table}','I',{pkj('NEW')},NULL,{obj('NEW', cols)}); END",
                f"CREATE TEMP TRIGGER IF NOT EXISTS _cap_{table}_u AFTER UPDATE ON {schema}.{table} {when} "
                f"BEGIN INSERT INTO _cap(tbl,op,pk,old,new) VALUES('{table}','U',{pkj('NEW')},"
                f"{obj('OLD', upd_cols)},{obj('NEW', upd_cols)}); "
                # a key change is a delete + insert
                f"END",
                f"CREATE TEMP TRIGGER IF NOT EXISTS _cap_{table}_d AFTER DELETE ON {schema}.{table} {when} "
                f"BEGIN INSERT INTO _cap(tbl,op,pk,old,new) VALUES('{table}','D',{pkj('OLD')},{obj('OLD', cols)},NULL); END",
            ]
            _TRIGGER_SQL[key] = sql
        for s in sql:
            conn.execute(s)


# ------------------------------------------------------------------ payload storage
def _pack(conn, row):
    if row is None:
        return None
    text = json.dumps(row, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    if len(text) <= INLINE_LIMIT:
        return text
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()
    conn.execute("INSERT OR IGNORE INTO doc_texts(hash, body) VALUES(?,?)",
                 (h, zlib.compress(text.encode("utf-8"), 6)))
    return "@" + h


def _drop_if_unused(conn, ref):
    """Delete a stored text that no revision points to any more."""
    if not ref or not ref.startswith("@"):
        return
    if conn.execute("SELECT 1 FROM revisions WHERE before=? OR after=? LIMIT 1", (ref, ref)).fetchone():
        return
    conn.execute("DELETE FROM doc_texts WHERE hash=?", (ref[1:],))


def compact(conn):
    """Remove stored texts nothing refers to (left by older versions). Returns how many."""
    n = conn.execute(
        "DELETE FROM doc_texts WHERE '@'||hash NOT IN (SELECT before FROM revisions WHERE before LIKE '@%' "
        "UNION SELECT after FROM revisions WHERE after LIKE '@%')").rowcount
    conn.commit()
    return n


def unpack(conn, ref):
    if ref is None:
        return None
    if ref.startswith("@"):
        r = conn.execute("SELECT body FROM doc_texts WHERE hash=?", (ref[1:],)).fetchone()
        if not r:
            return None
        return json.loads(zlib.decompress(r[0]).decode("utf-8"))
    return json.loads(ref)


# ------------------------------------------------------------------ recording
def _fold(caps):
    """Raw trigger rows -> one (tbl, pk, op, before, after) per row, in first-touch order."""
    state = {}
    order = []
    for c in caps:
        key = (c["tbl"], c["pk"])
        old = json.loads(c["old"]) if c["old"] else None
        new = json.loads(c["new"]) if c["new"] else None
        if key not in state:
            order.append(key)
            # before: what the row was when we first touched it
            state[key] = {"before": None if c["op"] == "I" else old, "after": None, "exists": True}
            if c["op"] == "U":
                state[key]["after"] = dict(old or {})
        st = state[key]
        if c["op"] == "I":
            st["after"] = dict(new)
            st["exists"] = True
        elif c["op"] == "D":
            if st["before"] is not None and old:
                # first touched by an UPDATE (which leaves big columns out): complete
                # the "before" row from the deleted row, keeping the earlier values
                full = dict(old)
                full.update(st["before"])
                st["before"] = full
            st["after"] = None
            st["exists"] = False
        else:  # U: partial (columns not recorded on update are left out)
            cur = st["after"] if st["after"] is not None else {}
            cur.update(new or {})
            st["after"] = cur
    out = []
    for key in order:
        st = state[key]
        before, after = st["before"], st["after"]
        if before is None and after is None:
            continue                                   # created and deleted again
        if before is None:
            op = "I"
        elif after is None:
            op = "D"
        else:
            op = "U"
            if {k: v for k, v in before.items() if k in after} == {k: v for k, v in after.items() if k in before}:
                continue                               # touched but unchanged
        out.append((key[0], key[1], op, before, after))
    return out


def _merge(prev_op, prev_before, prev_after, op, before, after):
    """Combine an existing revision with a newer one for the same row."""
    first = prev_before if prev_op != "I" else None
    last = after
    if first is None and last is None:
        return None
    if first is None:
        return "I", None, last
    if last is None:
        return "D", first, None
    return "U", first, last


class Change:
    """Record everything written inside the block as one changeset (one undo step)."""

    def __init__(self, conn, label, kind="edit", scope=None, session=None,
                 coalesce=False, reverts=None):
        self.conn = conn
        self.label = label
        self.kind = kind
        self.scope_kind, self.scope_id = scope if scope else (None, None)
        self.session = session
        self.coalesce = coalesce
        self.reverts = list(reverts or [])
        self.id = None
        self.rows = 0

    def __enter__(self):
        install(self.conn)
        # Already recording (a Change inside a Change)? Then this block simply
        # becomes part of the outer one: one undo step, nothing lost.
        self.nested = bool(self.conn.execute("SELECT v FROM _cap_on").fetchone()[0])
        if self.nested:
            return self
        self.conn.execute("DELETE FROM _cap")
        self.conn.execute("UPDATE _cap_on SET v=1")
        return self

    def __exit__(self, exc_type, exc, tb):
        conn = self.conn
        if self.nested:
            return False                   # the outer Change stores (or rolls back) everything
        conn.execute("UPDATE _cap_on SET v=0")
        if exc_type is not None:
            conn.rollback()
            conn.execute("DELETE FROM _cap")
            return False
        try:
            caps = conn.execute("SELECT * FROM _cap ORDER BY seq").fetchall()
            conn.execute("DELETE FROM _cap")
            folded = _fold(caps)
            if folded or self.reverts:
                self._store(folded)
            conn.commit()
        except Exception:
            conn.rollback()            # never leave a half-recorded change behind
            raise
        return False

    # -- storing
    def _coalesce_target(self):
        if not (self.coalesce and self.scope_id):
            return None
        last = self.conn.execute("SELECT * FROM changesets ORDER BY id DESC LIMIT 1").fetchone()
        if not last or last["kind"] != self.kind or last["scope_id"] != self.scope_id or last["undone"]:
            return None
        if self.session and last["session"] and last["session"] != self.session:
            return None
        # a checkpoint was saved after this entry: what comes next is "after the checkpoint"
        if self.conn.execute("SELECT 1 FROM checkpoints WHERE changeset_id=?", (last["id"],)).fetchone():
            return None
        try:
            now = time.time()
            age = now - _ts(last["updated_at"])
            span = now - _ts(last["created_at"])
        except ValueError:
            return None
        return last["id"] if age < COALESCE_SECONDS and span < COALESCE_MAX_SPAN else None

    def _store(self, folded):
        conn = self.conn
        now = _now()
        target = self._coalesce_target()
        if target:
            self.id = target
            existing = {(r["tbl"], r["pk"]): r for r in conn.execute(
                "SELECT * FROM revisions WHERE changeset_id=?", (target,))}
            seq = conn.execute("SELECT COALESCE(MAX(seq),0) FROM revisions WHERE changeset_id=?",
                               (target,)).fetchone()[0]
            for tbl, pk, op, before, after in folded:
                prev = existing.get((tbl, pk))
                if prev:
                    merged = _merge(prev["op"], unpack(conn, prev["before"]), unpack(conn, prev["after"]),
                                    op, before, after)
                    if merged is None:
                        conn.execute("DELETE FROM revisions WHERE id=?", (prev["id"],))
                    else:
                        conn.execute("UPDATE revisions SET op=?, before=?, after=? WHERE id=?",
                                     (merged[0], _pack(conn, merged[1]), _pack(conn, merged[2]), prev["id"]))
                    _drop_if_unused(conn, prev["after"])     # the replaced copy of the text
                else:
                    seq += 1
                    conn.execute("INSERT INTO revisions(changeset_id,seq,tbl,pk,op,before,after) "
                                 "VALUES(?,?,?,?,?,?,?)",
                                 (target, seq, tbl, pk, op, _pack(conn, before), _pack(conn, after)))
            n = conn.execute("SELECT COUNT(*) FROM revisions WHERE changeset_id=?", (target,)).fetchone()[0]
            conn.execute("UPDATE changesets SET updated_at=?, label=?, n_rows=? WHERE id=?",
                         (now, self.label, n, target))
            self.rows = n
            return
        self.id = _next_id(conn)
        conn.execute("INSERT INTO changesets(id,created_at,updated_at,label,kind,scope_kind,scope_id,"
                     "session,reverts,undone,n_rows) VALUES(?,?,?,?,?,?,?,?,?,0,?)",
                     (self.id, now, now, self.label, self.kind, self.scope_kind, self.scope_id,
                      self.session, json.dumps(self.reverts) if self.reverts else None, len(folded)))
        for i, (tbl, pk, op, before, after) in enumerate(folded, 1):
            conn.execute("INSERT INTO revisions(changeset_id,seq,tbl,pk,op,before,after) VALUES(?,?,?,?,?,?,?)",
                         (self.id, i, tbl, pk, op, _pack(conn, before), _pack(conn, after)))
        for rid in self.reverts:
            if rid.startswith("+"):                    # re-applied: in effect again
                conn.execute("UPDATE changesets SET undone=0 WHERE id=?", (rid[1:],))
            else:
                conn.execute("UPDATE changesets SET undone=1 WHERE id=?", (rid,))
        self.rows = len(folded)

    def info(self):
        return {"id": self.id, "label": self.label, "kind": self.kind} if self.id else None


# ------------------------------------------------------------------ applying
def _where(table):
    _, pk, _ = TRACKED[table]
    return " AND ".join(f'"{c}"=?' for c in pk)


def _current(conn, table, pk_vals):
    schema = TRACKED[table][0]
    r = conn.execute(f"SELECT * FROM {schema}.{table} WHERE {_where(table)}", pk_vals).fetchone()
    return dict(r) if r else None


def _same(a, b):
    return a == b or (a in (None, "") and b in (None, ""))


def _invert(conn, changeset_id, force=False, dry=False, forward=False):
    """Write every row of a changeset back to its 'before' state (newest first).
    With ``forward`` it does the opposite: writes the 'after' state again (oldest
    first), i.e. re-applies the changeset.

    Returns (conflicts, touched_topic_ids). A field that was changed again after
    this changeset keeps its newer value and is reported as a conflict; a row
    that was created here and changed later is only deleted with ``force``.
    """
    conflicts = []
    touched = set()
    sim = {}                                       # dry-run row states

    def cur_of(table, pkv):
        k = (table, tuple(pkv))
        if dry and k in sim:
            return sim[k]
        return _current(conn, table, pkv)

    def put(table, pkv, row):
        sim[(table, tuple(pkv))] = row

    revs = conn.execute("SELECT * FROM revisions WHERE changeset_id=? ORDER BY seq " + ("ASC" if forward else "DESC"),
                        (changeset_id,)).fetchall()
    for r in revs:
        table = r["tbl"]
        if table not in TRACKED:
            continue
        schema = TRACKED[table][0]
        pkv = json.loads(r["pk"])
        before, after = unpack(conn, r["before"]), unpack(conn, r["after"])
        op = r["op"]
        if forward:
            before, after = after, before
            op = {"I": "D", "D": "I"}.get(op, op)
        cur = cur_of(table, pkv)
        if table == "topics":
            touched.add(pkv[0])
        elif table == "topic_edits":
            touched.add(pkv[0])
        if op == "I":                              # created here -> delete it again
            if cur is None:
                continue
            changed = [k for k, v in (after or {}).items()
                       if k in cur and k not in IGNORE_IN_COMPARE and not _same(cur[k], v)]
            if changed:
                conflicts.append({"table": table, "pk": pkv, "fields": changed, "what": "changed since"})
                if not force:
                    continue
            if not dry:
                conn.execute(f"DELETE FROM {schema}.{table} WHERE {_where(table)}", pkv)
            put(table, pkv, None)
        elif op == "D":                            # deleted here -> put it back
            if cur is not None:
                conflicts.append({"table": table, "pk": pkv, "fields": [], "what": "exists again"})
                continue
            if not dry:
                cols = [c for c in before.keys() if c in _cols(conn, schema, table)]
                conn.execute(f"INSERT INTO {schema}.{table}({','.join(chr(34) + c + chr(34) for c in cols)}) "
                             f"VALUES({','.join('?' * len(cols))})", [before[c] for c in cols])
            put(table, pkv, dict(before))
        else:                                      # changed here -> change fields back
            if cur is None:
                conflicts.append({"table": table, "pk": pkv, "fields": list(before), "what": "gone"})
                continue
            sets, vals, kept = [], [], []
            new_state = dict(cur)
            for k, v in before.items():
                if k not in cur:
                    continue
                if k in IGNORE_IN_COMPARE or _same(cur[k], (after or {}).get(k)):
                    if not _same(cur[k], v):
                        sets.append(f'"{k}"=?'); vals.append(v)
                        new_state[k] = v
                else:
                    kept.append(k)
            if kept:
                conflicts.append({"table": table, "pk": pkv, "fields": kept, "what": "changed since"})
            if sets and not dry:
                conn.execute(f"UPDATE {schema}.{table} SET {', '.join(sets)} WHERE {_where(table)}",
                             (*vals, *pkv))
            put(table, pkv, new_state)
    return conflicts, touched


_COLS = {}


def _cols(conn, schema, table):
    k = (schema, table)
    if k not in _COLS:
        _COLS[k] = set(_columns(conn, schema, table))
    return _COLS[k]


def reindex_topics(conn, topic_ids):
    """Bring the search index in line with the current title/text of these topics."""
    for tid in topic_ids:
        try:
            conn.execute("DELETE FROM search_fts WHERE ref=? AND kind='topic'", (tid,))
            r = conn.execute(
                "SELECT COALESCE(e.title,t.title) title, COALESCE(e.plain_text,t.plain_text) body, "
                "t.section_id, s.chapter_id, c.library_id FROM topics t "
                "JOIN sections s ON s.id=t.section_id JOIN chapters c ON c.id=s.chapter_id "
                "LEFT JOIN topic_edits e ON e.topic_id=t.id WHERE t.id=?", (tid,)).fetchone()
            if r:
                conn.execute("INSERT INTO search_fts(ref,kind,title,body,library_id,chapter_id,section_id) "
                             "VALUES(?,?,?,?,?,?,?)",
                             (tid, "topic", r["title"] or "", r["body"] or "",
                              r["library_id"], r["chapter_id"], r["section_id"]))
        except Exception:  # noqa: BLE001 - no FTS: search falls back to LIKE
            return


def get(conn, changeset_id):
    r = conn.execute("SELECT * FROM changesets WHERE id=?", (changeset_id,)).fetchone()
    return dict(r) if r else None


def preview_undo(conn, changeset_id):
    """Conflicts an undo would report, without changing anything."""
    conflicts, _ = _invert(conn, changeset_id, dry=True)
    return conflicts


def undo(conn, changeset_id, force=False, label=None):
    """Revert one changeset. Returns (Change|None, conflicts). Nothing is written
    when there are conflicts and ``force`` is false."""
    cs = get(conn, changeset_id)
    if not cs:
        raise KeyError(changeset_id)
    if cs["kind"] in NOT_UNDOABLE:
        raise ValueError("This change was imported from before history was kept and can't be undone.")
    if cs["undone"]:
        return None, []
    conflicts = preview_undo(conn, changeset_id)
    if conflicts and not force:
        return None, conflicts
    kind = "redo" if cs["kind"] == "undo" else "undo"
    text = label or (("Redid: " + _strip(cs["label"])) if kind == "redo" else ("Undid: " + cs["label"]))
    with Change(conn, text, kind=kind, scope=(cs["scope_kind"], cs["scope_id"]),
                reverts=[changeset_id]) as ch:
        _, touched = _invert(conn, changeset_id, force=force)
        for rid in json.loads(cs["reverts"] or "[]"):        # undoing an undo: the original is live again
            if rid.startswith("+"):                          # undoing a re-apply: taken back again
                conn.execute("UPDATE changesets SET undone=1 WHERE id=?", (rid[1:],))
            else:
                conn.execute("UPDATE changesets SET undone=0 WHERE id=?", (rid,))
        reindex_topics(conn, touched)
    return ch, conflicts


def _strip(label):
    return label[len("Undid: "):] if label.startswith("Undid: ") else label


def latest_undoable(conn):
    """The newest change whose effect is still in place (what Ctrl+Z undoes)."""
    r = conn.execute("SELECT id FROM changesets WHERE undone=0 AND kind NOT IN ('undo','import') "
                     "ORDER BY id DESC LIMIT 1").fetchone()
    return r[0] if r else None


def latest_redoable(conn):
    """The undo to revert for Ctrl+Shift+Z: the newest undo that is still in effect,
    provided nothing else has been changed since it."""
    last = conn.execute("SELECT * FROM changesets ORDER BY id DESC LIMIT 1").fetchone()
    r = conn.execute("SELECT id FROM changesets WHERE kind='undo' AND undone=0 "
                     "ORDER BY id DESC LIMIT 1").fetchone()
    if not r:
        return None
    if last and last["kind"] not in ("undo", "redo"):
        return None
    return r[0]


def restore_to(conn, after_changeset_id, label):
    """Bring everything back to how it was right after ``after_changeset_id``
    (None = before any change), as ONE changeset.

    Every changeset recorded after that point is reverted, newest first,
    including undos and redos: an undo is reverted (its change comes back)
    and then the change itself is reverted, so a change you had already undone
    stays gone. Only the changes that were in effect are marked as undone, so
    undoing the restore puts the flags back exactly as they were."""
    q = "SELECT id, undone FROM changesets WHERE kind NOT IN ('import')"
    args = ()
    if after_changeset_id:
        q += " AND id > ?"
        args = (after_changeset_id,)
    rows = conn.execute(q + " ORDER BY id DESC", args).fetchall()
    live = [r["id"] for r in rows if not r["undone"]]
    if not live:
        return None
    touched_all = set()
    with Change(conn, label, kind="restore", reverts=live) as ch:
        for r in rows:
            _, touched = _invert(conn, r["id"], force=True)
            touched_all |= touched
        reindex_topics(conn, touched_all)
    return ch


def reapply(conn, changeset_id, label=None, force=False):
    """Re-apply ONE change that a restore took back (redo of a single item),
    leaving the rest of the restore as it is. Returns (Change|None, conflicts)."""
    cs = get(conn, changeset_id)
    if not cs:
        raise KeyError(changeset_id)
    if not cs["undone"]:
        return None, []
    conflicts, _ = _invert(conn, changeset_id, dry=True, forward=True)
    if conflicts and not force:
        return None, conflicts
    with Change(conn, label or ("Redid: " + _strip(cs["label"])), kind="redo",
                scope=(cs["scope_kind"], cs["scope_id"]), reverts=["+" + changeset_id]) as ch:
        _, touched = _invert(conn, changeset_id, force=force, forward=True)
        reindex_topics(conn, touched)
    return ch, conflicts


# ------------------------------------------------------------------ reading history
def topic_versions(conn, topic_id):
    """Every saved version of a topic's text, newest first (plus the original)."""
    pk = json.dumps([topic_id])
    rows = conn.execute(
        "SELECT r.id rid, r.op, r.after, c.id cid, c.label, c.updated_at, c.kind, c.undone "
        "FROM revisions r JOIN changesets c ON c.id=r.changeset_id "
        "WHERE r.tbl='topic_edits' AND r.pk=? ORDER BY c.id DESC", (pk,)).fetchall()
    cur = conn.execute("SELECT html, title FROM topic_edits WHERE topic_id=?", (topic_id,)).fetchone()
    out, seen_current = [], False
    for r in rows:
        after = unpack(conn, r["after"])
        is_current = (not seen_current) and (
            (after is None and cur is None) or
            (after is not None and cur is not None and after.get("html") == cur["html"]
             and after.get("title") == cur["title"]))
        if is_current:
            seen_current = True
        out.append({"id": r["rid"], "changeset": r["cid"], "label": r["label"], "saved_at": r["updated_at"],
                    "original": after is None, "title": (after or {}).get("title"),
                    "size": len((after or {}).get("html") or ""), "current": is_current,
                    "undone": bool(r["undone"])})
    return out


def revision_state(conn, revision_id):
    r = conn.execute("SELECT * FROM revisions WHERE id=?", (revision_id,)).fetchone()
    if not r:
        return None, None
    return dict(r), unpack(conn, r["after"])


def changesets(conn, limit=50, before=None, scope_id=None, kind=None):
    q, args = "SELECT * FROM changesets WHERE 1=1", []
    if before:
        q += " AND id < ?"; args.append(before)
    if scope_id:
        q += " AND scope_id=?"; args.append(scope_id)
    if kind:
        q += " AND kind=?"; args.append(kind)
    q += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    return [dict(r) for r in conn.execute(q, args)]
