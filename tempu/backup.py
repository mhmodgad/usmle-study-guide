"""Cloud backup of your data with rclone (Google Drive, or any rclone remote).

Offline first: a change is saved when it is on disk. This module copies what
you choose to the cloud later, in the background, and never blocks the app.

You control it fully (Settings -> Backup, stored in user.db ``user_meta``):
  * on / off
  * WHAT is backed up: each category in ``CATEGORIES`` can be ticked or not
  * WHEN: after changes, every N hours, or only when you press "Back up now"
  * how many snapshots to keep, and where (any rclone remote + folder)

What a backup run does (``run``):
  1. new files you added  -> <remote>/blobs/ab/<sha>.<ext>   (each file once)
  2. a consistent copy of user.db with only the chosen categories, gzipped
                          -> <remote>/snapshots/YYYY/MM/user-<time>.db.gz (+ .json)
  3. optional large items you ticked (content DB, original media, captured JSON)
                          -> <remote>/content/...   (rclone copies only what changed)
  4. manifest.json last   -> <remote>/manifest.json  (the pointer to a complete backup)
  5. old snapshots pruned by the retention you set

Command line:  python -m tempu.backup status | run | list | restore [NAME] [--only a,b]
"""
import argparse
import datetime
import gzip
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time

from . import db as dbmod
from . import blobs as blobmod

# key -> (label, description, user.db tables, default on, size hint)
CATEGORIES = {
    "edits": ("Content edits & history",
              "Your changes to topics, new and moved chapters/sections/topics, the trash, undo history and checkpoints.",
              ["changesets", "revisions", "doc_texts", "checkpoints", "topic_edits",
               "topic_edit_history", "struct_overrides"], True, "small"),
    "study": ("Study progress", "Completed topics, reading position, bookmarks, study log.",
              ["progress", "section_state", "study_log"], True, "small"),
    "notes": ("Highlights & notes", "Highlights, inline notes and topic notes.",
              ["highlights", "inline_notes", "topic_notes"], True, "small"),
    "flashcards": ("Flashcards & decks", "Your decks and spaced-repetition review state.",
                   ["card_reviews", "decks", "deck_cards"], True, "small"),
    "settings": ("Settings & profile", "Display name, avatar, theme, reader and app preferences.",
                 ["settings"], True, "small"),
    "files": ("Files you added", "Images and icons you added with the editor (data/blobs).",
              ["blobs"], True, "depends"),
    "base": ("Library content database", "data/base.db — rebuildable from your content folder.",
             [], False, "large"),
    "source": ("Captured content (JSON)", "local/content — what the library is built from.",
               [], False, "large"),
    "media": ("Original images & videos", "local/assets/media — the original topic media.",
              [], False, "very large"),
}
NEVER_IN_SNAPSHOT = ("backup_log", "user_meta")

DEFAULT_CONFIG = {
    "enabled": False,
    "remote": "",                      # e.g. "tempu-drive:tempu-backup"
    "categories": {k: v[3] for k, v in CATEGORIES.items()},
    "schedule": "auto",                # auto | interval | manual
    "interval_hours": 6,
    "keep_recent": 20, "keep_daily": 14, "keep_monthly": 12,
    "rclone": "",                      # path to rclone; empty = find it on PATH
}
QUIET_SECONDS = 60          # wait this long after the last change (bursts -> one backup)
MIN_GAP_SECONDS = 600       # "auto": at most one backup every 10 minutes
BACKOFF_MINUTES = [1, 5, 15, 60]
LOCAL_KEEP = 3              # snapshots also kept in data/backup for local recovery


class BackupError(Exception):
    pass


def _now():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)


def _iso(dt=None):
    return (dt or _now()).isoformat().replace("+00:00", "Z")


def _parse(iso):
    try:
        return datetime.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ config
def get_config(conn):
    r = conn.execute("SELECT value FROM user_meta WHERE key='backup_config'").fetchone()
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if r:
        try:
            saved = json.loads(r[0])
            cats = cfg["categories"]
            cats.update(saved.get("categories") or {})
            cfg.update(saved)
            cfg["categories"] = cats
        except ValueError:
            pass
    return cfg


def save_config(conn, changes):
    cfg = get_config(conn)
    for k, v in changes.items():
        if k == "categories" and isinstance(v, dict):
            cfg["categories"].update({c: bool(on) for c, on in v.items() if c in CATEGORIES})
        elif k in ("enabled",):
            cfg[k] = bool(v)
        elif k in ("interval_hours", "keep_recent", "keep_daily", "keep_monthly"):
            cfg[k] = max(0, int(v))
        elif k == "schedule" and v in ("auto", "interval", "manual"):
            cfg[k] = v
        elif k in ("remote", "rclone"):
            cfg[k] = (v or "").strip()
    cfg["interval_hours"] = max(1, cfg["interval_hours"])
    cfg["keep_recent"] = max(1, cfg["keep_recent"])
    conn.execute("INSERT OR REPLACE INTO user_meta(key,value) VALUES('backup_config',?)", (json.dumps(cfg),))
    conn.commit()
    return cfg


def _meta(conn, key, value=None):
    if value is None:
        r = conn.execute("SELECT value FROM user_meta WHERE key=?", (key,)).fetchone()
        return r[0] if r else None
    conn.execute("INSERT OR REPLACE INTO user_meta(key,value) VALUES(?,?)", (key, value))
    conn.commit()


# ------------------------------------------------------------------ rclone
def rclone_path(cfg):
    p = cfg.get("rclone") or os.environ.get("TEMPU_RCLONE") or shutil.which("rclone")
    return p if p and (os.path.isfile(p) or shutil.which(p)) else None


def _rclone(cfg, *args, timeout=3600, input_text=None):
    exe = rclone_path(cfg)
    if not exe:
        raise BackupError("rclone is not installed (see Settings → Backup for how to install it).")
    try:
        p = subprocess.run([exe, *args], capture_output=True, text=True, timeout=timeout, input=input_text)
    except subprocess.TimeoutExpired:
        raise BackupError("rclone timed out: " + " ".join(args[:2]))
    if p.returncode != 0:
        msg = (p.stderr or p.stdout or "").strip().splitlines()
        raise BackupError("rclone failed: " + (msg[-1] if msg else "exit %d" % p.returncode))
    return p.stdout


def _join(remote, *parts):
    remote = remote.rstrip("/")
    return remote + "/" + "/".join(p.strip("/") for p in parts if p)


def test_remote(cfg):
    """Write, read back and delete a small file. Returns a message or raises BackupError."""
    if not cfg.get("remote"):
        raise BackupError("Choose a remote first, e.g. tempu-drive:tempu-backup")
    name = "_tempu_test_%d.txt" % int(time.time())
    _rclone(cfg, "mkdir", cfg["remote"], timeout=120)
    _rclone(cfg, "rcat", _join(cfg["remote"], name), input_text="ok", timeout=120)
    got = _rclone(cfg, "cat", _join(cfg["remote"], name), timeout=120)
    _rclone(cfg, "deletefile", _join(cfg["remote"], name), timeout=120)
    if got.strip() != "ok":
        raise BackupError("The test file came back different.")
    return "Connected: rclone can write to %s" % cfg["remote"]


# ------------------------------------------------------------------ state
def content_dir():
    """local/content (same rule as tempu.loader)."""
    v = os.environ.get("TEMPU_CONTENT")
    if v:
        return v
    inp = os.path.join(dbmod.PROJECT, "local", "content")
    return inp if os.path.isdir(inp) else os.path.join(os.path.dirname(dbmod.PROJECT), "content")


def assets_dir():
    """local/assets (same rule as tempu.app)."""
    v = os.environ.get("TEMPU_ASSETS")
    if v:
        return v
    inp = os.path.join(dbmod.PROJECT, "local", "assets")
    return inp if os.path.isdir(inp) else os.path.join(os.path.dirname(dbmod.PROJECT), "tempu-replica", "assets")


def _dirs(db_path):
    user, base, data_dir = dbmod.paths(db_path)
    return user, base, data_dir, os.path.join(data_dir, "backup")


def _last_ok(conn):
    r = conn.execute("SELECT * FROM backup_log WHERE ok=1 ORDER BY id DESC LIMIT 1").fetchone()
    return dict(r) if r else None


def _last_run(conn):
    r = conn.execute("SELECT * FROM backup_log ORDER BY id DESC LIMIT 1").fetchone()
    return dict(r) if r else None


def _last_change_time(db_path):
    user = dbmod.paths(db_path)[0]
    t = 0
    for p in (user, user + "-wal"):
        if os.path.exists(p):
            t = max(t, os.path.getmtime(p))
    return t


def pending(conn, db_path):
    """(has_changes, changes_since_last_backup, files_waiting)."""
    last = _last_ok(conn)
    files = conn.execute("SELECT COUNT(*) FROM blobs WHERE uploaded_at IS NULL").fetchone()[0]
    if not last:
        n = conn.execute("SELECT COUNT(*) FROM changesets").fetchone()[0]
        return True, n, files
    n = conn.execute("SELECT COUNT(*) FROM changesets WHERE updated_at > ?", (last["started_at"],)).fetchone()[0]
    started = _parse(last["started_at"])
    dirty = _last_change_time(db_path) > (started.timestamp() + 2 if started else 0)
    return bool(dirty or n or files), n, files


def status(conn, db_path):
    cfg = get_config(conn)
    has, n, files = pending(conn, db_path)
    last_ok, last = _last_ok(conn), _last_run(conn)
    with _LOCK_STATE:
        running = dict(_RUN_STATE)
    if not cfg["enabled"]:
        state, text = "off", "Backup off"
    elif not cfg["remote"]:
        state, text = "setup", "Backup not set up"
    elif running.get("running"):
        state, text = "running", running.get("step") or "Backing up…"
    elif last and not last["ok"]:
        state, text = "error", "Backup needs attention"
    elif has:
        state, text = "pending", ("%d change%s waiting to back up" % (n, "" if n == 1 else "s")) if n else "Changes waiting to back up"
    else:
        state, text = "ok", "Backed up"
    return {"state": state, "text": text, "enabled": cfg["enabled"], "remote": cfg["remote"],
            "last_ok": last_ok["finished_at"] if last_ok else None,
            "last_error": last["error"] if last and not last["ok"] else None,
            "changes_waiting": n, "files_waiting": files, "rclone": bool(rclone_path(cfg)),
            "running": running}


# ------------------------------------------------------------------ snapshot
def make_snapshot(db_path, categories, out_dir):
    """Consistent copy of user.db holding only the chosen categories -> .db.gz. Returns (path, info)."""
    user, _, _, _ = _dirs(db_path)
    os.makedirs(out_dir, exist_ok=True)
    stamp = _now().strftime("%Y%m%dT%H%M%SZ")
    raw = os.path.join(out_dir, f"user-{stamp}.db")
    src = sqlite3.connect(user, timeout=30)
    dst = sqlite3.connect(raw)
    src.backup(dst)                    # online backup: safe while the app is writing
    src.close()
    keep = set()
    for c, on in categories.items():
        if on and c in CATEGORIES:
            keep.update(CATEGORIES[c][2])
    tables = [r[0] for r in dst.execute("SELECT name FROM sqlite_master WHERE type='table' "
                                        "AND name NOT LIKE 'sqlite_%'")]
    counts = {}
    for t in tables:
        if t not in keep or t in NEVER_IN_SNAPSHOT:
            dst.execute(f'DELETE FROM "{t}"')
        else:
            counts[t] = dst.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
    last_cs = None
    if "changesets" in keep:
        r = dst.execute("SELECT MAX(id) FROM changesets").fetchone()
        last_cs = r[0] if r else None
    dst.commit()
    dst.execute("PRAGMA journal_mode=DELETE")
    dst.execute("VACUUM")
    ok = dst.execute("PRAGMA integrity_check").fetchone()[0]
    dst.close()
    if ok != "ok":
        os.remove(raw)
        raise BackupError("The snapshot failed its integrity check: " + ok)
    gz = raw + ".gz"
    with open(raw, "rb") as f, gzip.open(gz, "wb", compresslevel=6) as g:
        shutil.copyfileobj(f, g)
    os.remove(raw)
    h = hashlib.sha256()
    with open(gz, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    info = {"name": os.path.basename(gz), "created_at": _iso(), "sha256": h.hexdigest(),
            "bytes": os.path.getsize(gz), "categories": sorted(c for c, on in categories.items() if on),
            "tables": counts, "last_changeset": last_cs, "format": 1}
    with open(gz[:-3] + ".json", "w") as f:
        json.dump(info, f, indent=1)
    return gz, info


def _remote_snapshot_path(name):
    # user-20261126T094200Z.db.gz -> snapshots/2026/11/...
    return "snapshots/%s/%s/%s" % (name[5:9], name[9:11], name)


# ------------------------------------------------------------------ run
_RUN_LOCK = threading.Lock()
_LOCK_STATE = threading.Lock()
_RUN_STATE = {"running": False}


def _step(text):
    with _LOCK_STATE:
        _RUN_STATE["step"] = text


def run(db_path=None, force=False):
    """One backup run. Returns the backup_log row. Raises nothing: errors are logged."""
    if not _RUN_LOCK.acquire(blocking=False):
        return {"ok": 0, "error": "A backup is already running."}
    with _LOCK_STATE:
        _RUN_STATE.update(running=True, step="Starting backup…")
    conn = dbmod.connect(db_path, journal=False)
    log_id = None
    try:
        cfg = get_config(conn)
        if not force and not cfg["enabled"]:
            return {"ok": 0, "error": "Backup is off."}
        if not cfg["remote"]:
            raise BackupError("No remote chosen.")
        cats = cfg["categories"]
        started = _iso()
        cur = conn.execute("INSERT INTO backup_log(started_at) VALUES(?)", (started,))
        log_id = cur.lastrowid
        conn.commit()
        user, base, data_dir, local_dir = _dirs(db_path)
        remote = cfg["remote"]
        sent_files = sent_bytes = 0
        _rclone(cfg, "mkdir", remote, timeout=300)

        # 1) files you added (before the snapshot that refers to them)
        if cats.get("files"):
            rows = conn.execute("SELECT sha256, ext, bytes FROM blobs WHERE uploaded_at IS NULL").fetchall()
            rows = [r for r in rows if os.path.isfile(blobmod.path_for(data_dir, r["sha256"], r["ext"]))]
            if rows:
                _step("Uploading %d file(s)…" % len(rows))
                with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as lst:
                    for r in rows:
                        lst.write("%s/%s.%s\n" % (r["sha256"][:2], r["sha256"], r["ext"]))
                try:
                    _rclone(cfg, "copy", blobmod.blob_dir(data_dir), _join(remote, "blobs"),
                            "--files-from", lst.name, "--no-traverse", "--immutable")
                finally:
                    os.remove(lst.name)
                now = _iso()
                conn.executemany("UPDATE blobs SET uploaded_at=? WHERE sha256=?", [(now, r["sha256"]) for r in rows])
                conn.commit()
                sent_files += len(rows)
                sent_bytes += sum(r["bytes"] or 0 for r in rows)

        # 2) snapshot of user.db with the chosen categories
        _step("Saving a snapshot…")
        gz, info = make_snapshot(db_path, cats, local_dir)
        _step("Uploading the snapshot…")
        rpath = _remote_snapshot_path(info["name"])
        _rclone(cfg, "copyto", gz, _join(remote, rpath))
        _rclone(cfg, "copyto", gz[:-3] + ".json", _join(remote, rpath[:-3] + ".json"))
        sent_bytes += info["bytes"]

        # 3) the large optional items you ticked
        extras = {}
        if cats.get("base") and os.path.isfile(base):
            _step("Uploading the content database…")
            tmp = os.path.join(local_dir, "base.db")
            s, d = sqlite3.connect(base), sqlite3.connect(tmp)
            s.backup(d); s.close(); d.close()
            _rclone(cfg, "copyto", tmp, _join(remote, "content/base.db"))
            os.remove(tmp)
            extras["base"] = "content/base.db"
        for key, local, rel in (("source", content_dir(), "content/source"),
                                ("media", os.path.join(assets_dir(), "media"), "content/media")):
            if cats.get(key) and os.path.isdir(local):
                _step("Uploading %s…" % CATEGORIES[key][0].lower())
                _rclone(cfg, "copy", local, _join(remote, rel))
                extras[key] = rel

        # 4) manifest last: until it is written the previous backup stays the current one
        manifest = dict(info, snapshot=rpath, remote_extras=extras, blobs_in_cloud=conn.execute(
            "SELECT COUNT(*) FROM blobs WHERE uploaded_at IS NOT NULL").fetchone()[0])
        _rclone(cfg, "rcat", _join(remote, "manifest.json"), input_text=json.dumps(manifest, indent=1))

        # 5) retention
        _step("Tidying old snapshots…")
        try:
            prune_remote(cfg)
        except BackupError:
            pass                      # a failed prune never fails the backup
        _prune_local(local_dir)
        conn.execute("UPDATE backup_log SET finished_at=?, ok=1, snapshot=?, blobs_sent=?, bytes_sent=?, "
                     "last_changeset=?, error=NULL WHERE id=?",
                     (_iso(), info["name"], sent_files, sent_bytes, info["last_changeset"], log_id))
        conn.commit()
        _meta(conn, "backup_failures", "0")
        return dict(conn.execute("SELECT * FROM backup_log WHERE id=?", (log_id,)).fetchone())
    except Exception as e:  # noqa: BLE001 - logged, retried later
        msg = str(e) if isinstance(e, BackupError) else "%s: %s" % (type(e).__name__, e)
        if log_id:
            conn.execute("UPDATE backup_log SET finished_at=?, ok=0, error=? WHERE id=?", (_iso(), msg, log_id))
        else:
            conn.execute("INSERT INTO backup_log(started_at, finished_at, ok, error) VALUES(?,?,0,?)",
                         (_iso(), _iso(), msg))
        conn.commit()
        _meta(conn, "backup_failures", str(int(_meta(conn, "backup_failures") or 0) + 1))
        return {"ok": 0, "error": msg}
    finally:
        conn.close()
        with _LOCK_STATE:
            _RUN_STATE.update(running=False, step=None)
        _RUN_LOCK.release()


def _prune_local(local_dir):
    snaps = sorted(f for f in os.listdir(local_dir) if f.startswith("user-") and f.endswith(".db.gz"))
    for f in snaps[:-LOCAL_KEEP]:
        for p in (f, f[:-3] + ".json"):
            try:
                os.remove(os.path.join(local_dir, p))
            except OSError:
                pass


def list_remote(cfg):
    out = _rclone(cfg, "lsf", "-R", "--files-only", _join(cfg["remote"], "snapshots"), timeout=300)
    names = sorted({line.rsplit("/", 1)[-1] for line in out.splitlines() if line.endswith(".db.gz")},
                   reverse=True)
    return names


def keep_set(names, keep_recent, keep_daily, keep_monthly, now=None):
    """Which snapshot names to keep: the newest N, one a day for D days, one a month for M months."""
    now = now or _now()
    names = sorted(names, reverse=True)
    keep = set(names[:keep_recent])
    days, months = set(), set()
    for n in names:
        ts = n[5:21]
        try:
            dt = datetime.datetime.strptime(ts, "%Y%m%dT%H%M%SZ").replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            keep.add(n)                # unknown name: never delete
            continue
        day, month = dt.strftime("%Y%m%d"), dt.strftime("%Y%m")
        if (now - dt).days < keep_daily and day not in days:
            days.add(day); keep.add(n)
        age_months = (now.year - dt.year) * 12 + (now.month - dt.month)
        if age_months < keep_monthly and month not in months:
            months.add(month); keep.add(n)
    return keep


def prune_remote(cfg):
    names = list_remote(cfg)
    keep = keep_set(names, cfg["keep_recent"], cfg["keep_daily"], cfg["keep_monthly"])
    for n in names:
        if n not in keep:
            p = _remote_snapshot_path(n)
            _rclone(cfg, "deletefile", _join(cfg["remote"], p), timeout=300)
            try:
                _rclone(cfg, "deletefile", _join(cfg["remote"], p[:-3] + ".json"), timeout=300)
            except BackupError:
                pass
    return len(names) - len([n for n in names if n in keep])


# ------------------------------------------------------------------ restore
def snapshot_info(cfg, name):
    try:
        return json.loads(_rclone(cfg, "cat", _join(cfg["remote"], _remote_snapshot_path(name)[:-3] + ".json"),
                                  timeout=300))
    except (BackupError, ValueError):
        return {"name": name}


def restore(db_path=None, name=None, only=None, rebuild=True):
    """Bring back the chosen categories from a cloud snapshot (default: the newest).

    Your current user.db is copied to data/backup/pre-restore-<time>.db first,
    and only the tables of the chosen categories are replaced; everything else
    stays as it is on this computer.
    """
    with _LOCK_STATE:
        _RUN_STATE.update(running=True, step="Restoring…")
    conn = dbmod.connect(db_path, journal=False)
    try:
        cfg = get_config(conn)
        user, base, data_dir, local_dir = _dirs(db_path)
        os.makedirs(local_dir, exist_ok=True)
        if not name:
            names = list_remote(cfg)
            if not names:
                raise BackupError("There are no backups in %s yet." % cfg["remote"])
            name = names[0]
        info = snapshot_info(cfg, name)
        cats = [c for c in (only or info.get("categories") or [k for k in CATEGORIES])
                if c in CATEGORIES and (not info.get("categories") or c in info["categories"]
                                        or c in ("base", "source", "media"))]
        work = tempfile.mkdtemp(prefix="restore-", dir=local_dir)
        _step("Downloading %s…" % name)
        gz = os.path.join(work, name)
        _rclone(cfg, "copyto", _join(cfg["remote"], _remote_snapshot_path(name)), gz)
        if info.get("sha256"):
            h = hashlib.sha256()
            with open(gz, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            if h.hexdigest() != info["sha256"]:
                raise BackupError("The downloaded snapshot is damaged (checksum mismatch).")
        raw = gz[:-3]
        with gzip.open(gz, "rb") as g, open(raw, "wb") as f:
            shutil.copyfileobj(g, f)
        chk = sqlite3.connect(raw)
        if chk.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            chk.close()
            raise BackupError("The downloaded snapshot is damaged.")
        chk.close()

        # safety copy of what is here now
        _step("Keeping a copy of your current data…")
        safety = os.path.join(local_dir, "pre-restore-%s.db" % _now().strftime("%Y%m%dT%H%M%SZ"))
        s, d = sqlite3.connect(user), sqlite3.connect(safety)
        s.backup(d); s.close(); d.close()

        _step("Restoring your data…")
        conn.execute("ATTACH DATABASE ? AS snap", (raw,))
        snap_tables = {r[0] for r in conn.execute("SELECT name FROM snap.sqlite_master WHERE type='table'")}
        restored = {}
        conn.execute("PRAGMA foreign_keys=OFF")
        try:
            for c in cats:
                for t in CATEGORIES[c][2]:
                    if t not in snap_tables:
                        continue
                    cols = [r[1] for r in conn.execute(f'PRAGMA main.table_info("{t}")')]
                    scol = {r[1] for r in conn.execute(f'PRAGMA snap.table_info("{t}")')}
                    use = [x for x in cols if x in scol]
                    cl = ",".join(f'"{x}"' for x in use)
                    conn.execute(f'DELETE FROM main."{t}"')
                    conn.execute(f'INSERT INTO main."{t}"({cl}) SELECT {cl} FROM snap."{t}"')
                    restored[t] = conn.execute(f'SELECT COUNT(*) FROM main."{t}"').fetchone()[0]
            conn.commit()
        finally:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("DETACH DATABASE snap")
        if "files" in cats:
            _step("Downloading files you added…")
            _rclone(cfg, "copy", _join(cfg["remote"], "blobs"), blobmod.blob_dir(data_dir))
            blobmod.index_untracked(conn, data_dir)
            conn.execute("UPDATE blobs SET uploaded_at=COALESCE(uploaded_at, ?)", (_iso(),))
            conn.commit()
        if "source" in cats:
            _step("Downloading captured content…")
            _rclone(cfg, "copy", _join(cfg["remote"], "content/source"), content_dir())
        if "media" in cats:
            _step("Downloading original media…")
            _rclone(cfg, "copy", _join(cfg["remote"], "content/media"), os.path.join(assets_dir(), "media"))
        conn.close()
        conn = None
        rebuilt = False
        if "base" in cats:
            _step("Downloading the content database…")
            tmp = os.path.join(work, "base.db")
            _rclone(cfg, "copyto", _join(cfg["remote"], "content/base.db"), tmp)
            src, dst = sqlite3.connect(tmp), sqlite3.connect(base)
            src.backup(dst)                     # replaces base.db's content in place
            src.close(); dst.close()
            rebuilt = True
        if "edits" in cats and rebuild and not rebuilt:
            # the served library must match the restored structure: rebuild + replay
            _step("Rebuilding the library with your restored changes…")
            from . import loader
            if os.path.isdir(os.path.join(content_dir(), "sections")):
                loader.build(content=content_dir(), db_path=db_path, seed=False)
            else:
                from . import structure
                c3 = dbmod.connect(db_path, journal=False)
                structure.replay(c3)
                c3.close()
        shutil.rmtree(work, ignore_errors=True)
        return {"ok": True, "snapshot": name, "categories": cats, "tables": restored, "safety_copy": safety}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
    finally:
        if conn is not None:
            conn.close()
        with _LOCK_STATE:
            _RUN_STATE.update(running=False, step=None)


_RESTORE_RESULT = {}

# ------------------------------------------------------------------ worker
_WORKER = {"thread": None, "wake": threading.Event(), "db": None}


def _due(conn, db_path, cfg):
    if not cfg["enabled"] or not cfg["remote"] or cfg["schedule"] == "manual":
        return False
    has, _, _ = pending(conn, db_path)
    if not has:
        return False
    now = time.time()
    if now - _last_change_time(db_path) < QUIET_SECONDS:
        return False
    last = _last_run(conn)
    if last:
        t = _parse(last["finished_at"] or last["started_at"])
        since = now - t.timestamp() if t else 1e9
        if not last["ok"]:
            fails = int(_meta(conn, "backup_failures") or 1)
            wait = BACKOFF_MINUTES[min(fails, len(BACKOFF_MINUTES)) - 1] * 60
            return since >= wait
        last_ok = _last_ok(conn)
        t_ok = _parse(last_ok["started_at"]) if last_ok else None
        since_ok = now - t_ok.timestamp() if t_ok else 1e9
        if cfg["schedule"] == "interval":
            return since_ok >= cfg["interval_hours"] * 3600
        return since_ok >= MIN_GAP_SECONDS
    return True


def _loop(db_path):
    while True:
        _WORKER["wake"].wait(30)
        _WORKER["wake"].clear()
        try:
            conn = dbmod.connect(db_path, journal=False)
            try:
                cfg = get_config(conn)
                due = _due(conn, db_path, cfg)
            finally:
                conn.close()
            if due:
                run(db_path)
        except Exception as e:  # noqa: BLE001 - the worker must never die
            print("  ! backup worker:", e)


def start_worker(db_path):
    if _WORKER["thread"] and _WORKER["thread"].is_alive():
        return
    _WORKER["db"] = db_path
    t = threading.Thread(target=_loop, args=(db_path,), name="tempu-backup", daemon=True)
    t.start()
    _WORKER["thread"] = t
    import atexit
    atexit.register(_at_exit, db_path)


def _at_exit(db_path):
    """Back up pending changes when the app stops (only if backups run automatically)."""
    try:
        conn = dbmod.connect(db_path, journal=False)
        cfg = get_config(conn)
        has, _, _ = pending(conn, db_path)
        conn.close()
        if cfg["enabled"] and cfg["remote"] and cfg["schedule"] != "manual" and has:
            print("Backing up your latest changes before exit…")
            run(db_path)
    except Exception:  # noqa: BLE001
        pass


def run_in_background(db_path, fn=None, **kw):
    t = threading.Thread(target=fn or run, args=(db_path,), kwargs=kw, daemon=True)
    t.start()
    return t


# ------------------------------------------------------------------ CLI
def main(argv=None):
    from . import migrate
    ap = argparse.ArgumentParser(description="Back up / restore your TEMP-U data with rclone")
    ap.add_argument("--db", default=None, help="path to data/user.db")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("run", help="back up now (even if automatic backup is off)")
    sub.add_parser("list", help="list snapshots in the cloud")
    r = sub.add_parser("restore", help="restore from the cloud")
    r.add_argument("name", nargs="?", help="snapshot name (default: newest)")
    r.add_argument("--only", help="comma-separated categories: " + ",".join(CATEGORIES))
    r.add_argument("--remote", help="remote to restore from (also saved as your backup remote)")
    c = sub.add_parser("config", help="show or change settings, e.g. config enabled=1 remote=tempu-drive:tempu-backup")
    c.add_argument("pairs", nargs="*")
    a = ap.parse_args(argv)
    migrate.ensure(dbmod.paths(a.db)[2], quiet=True)
    conn = dbmod.connect(a.db, journal=False)
    if a.cmd == "status":
        print(json.dumps(status(conn, a.db), indent=1))
    elif a.cmd == "config":
        changes = {}
        for p in a.pairs:
            k, _, v = p.partition("=")
            if k.startswith("categories."):
                changes.setdefault("categories", {})[k.split(".", 1)[1]] = v not in ("0", "false", "off", "")
            elif k == "enabled":
                changes[k] = v not in ("0", "false", "off", "")
            else:
                changes[k] = v
        print(json.dumps(save_config(conn, changes) if changes else get_config(conn), indent=1))
    elif a.cmd == "list":
        cfg = get_config(conn)
        for n in list_remote(cfg):
            print(n)
    elif a.cmd == "run":
        conn.close()
        print(json.dumps(run(a.db, force=True), indent=1))
        return
    elif a.cmd == "restore":
        if a.remote:
            save_config(conn, {"remote": a.remote})
        conn.close()
        only = [x.strip() for x in a.only.split(",")] if a.only else None
        print(json.dumps(restore(a.db, a.name, only), indent=1))
        return
    conn.close()


if __name__ == "__main__":
    main()
