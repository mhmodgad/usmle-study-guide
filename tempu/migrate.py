"""One-time upgrade from the single ``data/tempu.db`` to ``base.db`` + ``user.db``.

Runs automatically the first time the new version starts (and from
``python -m tempu.loader``). It never edits the old file: it works on copies
named ``*.migrating`` and only renames them into place at the end, so a crash
part-way leaves the old database untouched and the next start simply retries.

  1. copy tempu.db -> base.db.migrating (the served content)
  2. create user.db.migrating and copy every user table into it
  3. move data/uploads/* into the blob store and rewrite /uploads/ URLs
  4. turn the old per-topic snapshots into journal entries
  5. drop the user tables from the base copy
  6. rename: base.db.migrating -> base.db, user.db.migrating -> user.db,
     tempu.db -> tempu.db.pre-migration (kept until you delete it)
"""
import json
import os
import shutil
import sqlite3

from . import db as dbmod
from . import blobs as blobmod
from . import history

LEGACY_NAME = "tempu.db"


def needed(data_dir):
    return (not os.path.isfile(os.path.join(data_dir, "user.db"))
            and os.path.isfile(os.path.join(data_dir, LEGACY_NAME)))


def ensure(data_dir=None, quiet=False):
    """Make sure data_dir has the new layout. Returns True if a migration ran."""
    data_dir = data_dir or dbmod.DATA_DIR
    os.makedirs(data_dir, exist_ok=True)
    user = os.path.join(data_dir, "user.db")
    if os.path.isfile(user):
        _startup_checks(data_dir)
        return False
    if not os.path.isfile(os.path.join(data_dir, LEGACY_NAME)):
        # fresh install: an empty user.db; base.db comes from the loader
        conn = dbmod.connect(user, journal=False)
        dbmod.init_user_schema(conn)
        conn.close()
        return False
    _migrate(data_dir, quiet)
    _startup_checks(data_dir)
    return True


def _log(quiet, *a):
    if not quiet:
        print(*a)


def _cols(conn, schema, table):
    return [r[1] for r in conn.execute(f"PRAGMA {schema}.table_info({table})")]


def _migrate(data_dir, quiet):
    legacy = os.path.join(data_dir, LEGACY_NAME)
    base_tmp = os.path.join(data_dir, "base.db.migrating")
    user_tmp = os.path.join(data_dir, "user.db.migrating")
    _log(quiet, "Upgrading your data to the new storage layout (one time)…")
    for p in (base_tmp, user_tmp, base_tmp + "-wal", base_tmp + "-shm", user_tmp + "-wal", user_tmp + "-shm"):
        if os.path.exists(p):
            os.remove(p)

    # 1) fold the WAL into the old file, then copy it
    c = sqlite3.connect(legacy)
    c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    c.close()
    shutil.copy2(legacy, base_tmp)

    # 2) user tables into a new user.db
    conn = sqlite3.connect(user_tmp)
    conn.row_factory = sqlite3.Row
    conn.executescript(dbmod.USER_SQL)
    conn.execute("ATTACH DATABASE ? AS base", (base_tmp,))
    old_tables = {r[0] for r in conn.execute("SELECT name FROM base.sqlite_master WHERE type='table'")}
    moved = {}
    for t in dbmod.USER_TABLES:
        if t not in old_tables:
            continue
        new_cols = set(_cols(conn, "main", t))
        cols = [c for c in _cols(conn, "base", t) if c in new_cols]
        if not cols:
            continue
        cl = ",".join(f'"{c}"' for c in cols)
        conn.execute(f"INSERT OR IGNORE INTO main.{t}({cl}) SELECT {cl} FROM base.{t}")
        moved[t] = conn.execute(f"SELECT COUNT(*) FROM main.{t}").fetchone()[0]
    conn.commit()
    _log(quiet, "  copied your data:", json.dumps({k: v for k, v in moved.items() if v}))

    # 3) uploads -> blobs
    n_up = _move_uploads(conn, data_dir)
    if n_up:
        _log(quiet, f"  moved {n_up} uploaded file(s) into data/blobs")

    # 4) old topic snapshots -> journal
    n_cs = _import_topic_history(conn)
    n_st = _import_structure(conn)
    _log(quiet, f"  history: {n_cs} topic version(s), {n_st} structure change(s) imported")
    conn.commit()

    # 5) drop user tables from the base copy
    for t in dbmod.USER_TABLES:
        if t in old_tables:
            conn.execute(f"DROP TABLE IF EXISTS base.{t}")
    conn.commit()
    conn.execute("DETACH DATABASE base")
    conn.close()
    c = sqlite3.connect(base_tmp)
    c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    c.execute("VACUUM")
    c.close()
    c = sqlite3.connect(user_tmp)
    c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    c.close()

    # 6) swap into place (user.db last: its presence means "migrated")
    for suffix in ("-wal", "-shm"):
        for p in (base_tmp + suffix, user_tmp + suffix):
            if os.path.exists(p):
                os.remove(p)
    os.replace(base_tmp, os.path.join(data_dir, "base.db"))
    os.replace(user_tmp, os.path.join(data_dir, "user.db"))
    keep = os.path.join(data_dir, LEGACY_NAME + ".pre-migration")
    if not os.path.exists(keep):
        os.replace(legacy, keep)
    for suffix in ("-wal", "-shm"):
        p = legacy + suffix
        if os.path.exists(p):
            os.remove(p)
    _log(quiet, f"  done. Your old database is kept as {os.path.basename(keep)} (safe to delete later).")


def _move_uploads(conn, data_dir):
    up = os.path.join(data_dir, "uploads")
    if not os.path.isdir(up):
        return 0
    mapping = {}
    for fn in sorted(os.listdir(up)):
        full = os.path.join(up, fn)
        if not os.path.isfile(full):
            continue
        ext = fn.rsplit(".", 1)[-1].lower() if "." in fn else "bin"
        with open(full, "rb") as f:
            url = blobmod.save_bytes(conn, data_dir, f.read(), ext, original_name=fn)
        mapping["/uploads/" + fn] = url
    targets = [("main", "topic_edits", "html"), ("main", "topic_edit_history", "html"),
               ("main", "topic_notes", "body_html"), ("main", "struct_overrides", "icon_path"),
               ("main", "struct_overrides", "payload"), ("main", "settings", "value"),
               ("base", "chapters", "icon_path"), ("base", "sections", "icon_path"),
               ("base", "topics", "icon_url"), ("base", "libraries", "icon_path")]
    for old, new in mapping.items():
        for schema, t, col in targets:
            try:
                conn.execute(f"UPDATE {schema}.{t} SET {col}=REPLACE({col},?,?) WHERE {col} LIKE ?",
                             (old, new, f"%{old}%"))
            except sqlite3.OperationalError:
                pass
    conn.commit()
    # keep the old folder (renamed) so nothing is lost; /uploads/ URLs still resolve from it
    done = up + ".migrated"
    if not os.path.exists(done):
        os.replace(up, done)
    return len(mapping)


def _row_state(topic_id, html, title, plain, base_version, at):
    return {"topic_id": topic_id, "html": html, "title": title, "plain_text": plain,
            "base_version": base_version, "updated_at": at}


def _import_topic_history(conn):
    """Old model: topic_edit_history = snapshots taken at the start of each editing
    session (and before 'restore original'); topic_edits = the current version.
    New model: a chain of journal entries, oldest first, each before -> after."""
    from . import sanitize
    topics = [r[0] for r in conn.execute(
        "SELECT topic_id FROM topic_edit_history UNION SELECT topic_id FROM topic_edits")]
    n = 0
    for tid in topics:
        base = conn.execute("SELECT title, document_html, document_version FROM base.topics WHERE id=?",
                            (tid,)).fetchone()
        orig_html = base["document_html"] if base else None
        ver = base["document_version"] if base else None
        title0 = base["title"] if base else "topic"
        states = [(None, None)]                       # (state, time); None = the original
        for h in conn.execute("SELECT * FROM topic_edit_history WHERE topic_id=? ORDER BY id", (tid,)):
            if h["html"] == orig_html and not h["title"]:
                st = None
            else:
                st = _row_state(tid, h["html"], h["title"], sanitize.plain_text(h["html"] or ""), ver, h["saved_at"])
            states.append((st, h["saved_at"]))
        cur = conn.execute("SELECT * FROM topic_edits WHERE topic_id=?", (tid,)).fetchone()
        states.append((dict(cur) if cur else None, cur["updated_at"] if cur else None))
        # drop consecutive duplicates
        chain = []
        for st, at in states:
            key = None if st is None else (st["html"], st["title"])
            if chain and chain[-1][2] == key:
                continue
            chain.append((st, at, key))
        for i in range(1, len(chain)):
            before, after, at = chain[i - 1][0], chain[i][0], chain[i][1] or chain[i - 1][1]
            at = at or history._now()
            cid = history.new_id(at, i)
            title = (after or before or {}).get("title") or title0
            label = (f"Restored original of '{title0}'" if after is None else f"Edited '{title}'") + " (imported)"
            op = "I" if before is None else ("D" if after is None else "U")
            conn.execute("INSERT INTO changesets(id,created_at,updated_at,label,kind,scope_kind,scope_id,n_rows) "
                         "VALUES(?,?,?,?,?,?,?,1)", (cid, at, at, label, "edit", "topic", tid))
            conn.execute("INSERT INTO revisions(changeset_id,seq,tbl,pk,op,before,after) VALUES(?,?,?,?,?,?,?)",
                         (cid, 1, "topic_edits", json.dumps([tid]), op,
                          history._pack(conn, before), history._pack(conn, after)))
            n += 1
    conn.execute("DELETE FROM topic_edit_history")
    return n


def _import_structure(conn):
    rows = conn.execute("SELECT * FROM struct_overrides").fetchall()
    if not rows:
        return 0
    at = max((r["updated_at"] or "" for r in rows), default="") or history._now()
    cid = history.new_id(at)
    conn.execute("INSERT INTO changesets(id,created_at,updated_at,label,kind,n_rows) VALUES(?,?,?,?,?,?)",
                 (cid, at, at, "Structure changes made before history was kept (imported)", "import", len(rows)))
    for i, r in enumerate(rows, 1):
        conn.execute("INSERT INTO revisions(changeset_id,seq,tbl,pk,op,before,after) VALUES(?,?,?,?,?,?,?)",
                     (cid, i, "struct_overrides", json.dumps([r["kind"], r["id"]]), "I", None,
                      history._pack(conn, dict(r))))
    return len(rows)


def _startup_checks(data_dir):
    """Cheap checks on every start: schema up to date, crash leftovers cleaned."""
    try:
        conn = dbmod.connect(os.path.join(data_dir, "user.db"), journal=False)
        dbmod.ensure_user_tables(conn)
        history.compact(conn)              # stored texts no version refers to any more
        blobmod.cleanup_temp(data_dir)
        blobmod.index_untracked(conn, data_dir)
        conn.close()
    except Exception as e:  # noqa: BLE001 - never block the app from starting
        print("  ! startup check failed:", e)
