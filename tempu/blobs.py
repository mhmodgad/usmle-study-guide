"""Files you add (editor images, uploaded icons): a content-addressed store.

Each file is saved once under its SHA-256, ``data/blobs/3f/3fa91c…e2.webp``,
and served at ``/blobs/<sha>.<ext>``. A file's name is its content, so it
never changes once written: the browser can cache it forever, the backup
uploads it exactly once, and adding the same image twice stores it once.

Files are never deleted while anything — the current content OR any version
in the change journal — still refers to them (see :func:`collect_garbage`).
"""
import datetime
import hashlib
import os
import re
import zlib

NAME_RE = re.compile(r"^([0-9a-f]{64})\.([a-z0-9]{1,8})$")
URL_RE = re.compile(r"/blobs/([0-9a-f]{64})\.[a-z0-9]{1,8}")
MIME = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif",
        "webp": "image/webp", "avif": "image/avif", "bmp": "image/bmp", "svg": "image/svg+xml"}


def _now():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def blob_dir(data_dir):
    return os.path.join(data_dir, "blobs")


def path_for(data_dir, sha, ext):
    return os.path.join(blob_dir(data_dir), sha[:2], f"{sha}.{ext}")


def url_for(sha, ext):
    return f"/blobs/{sha}.{ext}"


def save_bytes(conn, data_dir, data, ext, original_name=None):
    """Store bytes (write temp file, fsync, rename, then record). Returns the /blobs/ URL."""
    ext = (ext or "bin").lower().lstrip(".")
    sha = hashlib.sha256(data).hexdigest()
    final = path_for(data_dir, sha, ext)
    if not os.path.isfile(final):
        tmpdir = os.path.join(blob_dir(data_dir), "tmp")
        os.makedirs(tmpdir, exist_ok=True)
        os.makedirs(os.path.dirname(final), exist_ok=True)
        tmp = os.path.join(tmpdir, f"{sha}.{os.getpid()}.part")
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, final)
    conn.execute("INSERT OR IGNORE INTO blobs(sha256,ext,mime,bytes,original_name,created_at) "
                 "VALUES(?,?,?,?,?,?)", (sha, ext, MIME.get(ext), len(data), original_name, _now()))
    conn.commit()
    return url_for(sha, ext)


def save_upload(conn, data_dir, fileobj, ext, original_name=None):
    return save_bytes(conn, data_dir, fileobj.read(), ext, original_name)


def cleanup_temp(data_dir):
    """Remove half-written files left by a crash."""
    tmpdir = os.path.join(blob_dir(data_dir), "tmp")
    if os.path.isdir(tmpdir):
        for fn in os.listdir(tmpdir):
            try:
                os.remove(os.path.join(tmpdir, fn))
            except OSError:
                pass


def index_untracked(conn, data_dir):
    """Record files on disk that have no row (e.g. written just before a crash)."""
    root = blob_dir(data_dir)
    if not os.path.isdir(root):
        return 0
    known = {r[0] for r in conn.execute("SELECT sha256 FROM blobs")}
    n = 0
    for sub in os.listdir(root):
        d = os.path.join(root, sub)
        if sub == "tmp" or not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            m = NAME_RE.match(fn)
            if m and m.group(1) not in known:
                conn.execute("INSERT OR IGNORE INTO blobs(sha256,ext,mime,bytes,created_at) VALUES(?,?,?,?,?)",
                             (m.group(1), m.group(2), MIME.get(m.group(2)),
                              os.path.getsize(os.path.join(d, fn)), _now()))
                n += 1
    conn.commit()
    return n


# ------------------------------------------------------------------ references / cleanup
def referenced(conn):
    """Every blob sha mentioned by current content or by any journal version."""
    refs = set()

    def scan(text):
        if text:
            refs.update(URL_RE.findall(text if isinstance(text, str) else str(text)))
    queries = [
        "SELECT html FROM topic_edits", "SELECT body_html FROM topic_notes",
        "SELECT icon_path FROM struct_overrides", "SELECT payload FROM struct_overrides",
        "SELECT value FROM settings", "SELECT note_text FROM inline_notes",
        "SELECT icon_path FROM chapters", "SELECT icon_path FROM sections",
        "SELECT icon_url FROM topics", "SELECT icon_path FROM libraries",
        "SELECT before FROM revisions", "SELECT after FROM revisions",
    ]
    for q in queries:
        try:
            for (v,) in conn.execute(q):
                scan(v)
        except Exception:  # noqa: BLE001 - table not there
            pass
    for (body,) in conn.execute("SELECT body FROM doc_texts"):
        try:
            scan(zlib.decompress(body).decode("utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return refs


def collect_garbage(conn, data_dir, grace_days=30):
    """Delete files nothing refers to any more, once they are older than ``grace_days``."""
    refs = referenced(conn)
    cutoff = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=grace_days)) \
        .replace(microsecond=0).isoformat().replace("+00:00", "Z")
    removed = 0
    for r in conn.execute("SELECT sha256, ext, created_at FROM blobs").fetchall():
        if r["sha256"] in refs or (r["created_at"] or "") > cutoff:
            continue
        try:
            os.remove(path_for(data_dir, r["sha256"], r["ext"]))
        except OSError:
            pass
        conn.execute("DELETE FROM blobs WHERE sha256=?", (r["sha256"],))
        removed += 1
    conn.commit()
    return removed
