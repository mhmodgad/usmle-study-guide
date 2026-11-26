"""JSON API for Settings -> Backup and the header status chip (see tempu/backup.py)."""
from flask import Blueprint, current_app, g, request, jsonify

from .. import backup as B

bp = Blueprint("backup_api", __name__, url_prefix="/api/backup")


def _db():
    return current_app.config["DB_PATH"]


@bp.route("/status")
def status():
    return jsonify(B.status(g.db, _db()))


@bp.route("/config", methods=["GET", "POST"])
def config():
    if request.method == "POST":
        cfg = B.save_config(g.db, request.get_json(force=True) or {})
        B._WORKER["wake"].set()
        return jsonify({"ok": True, "config": cfg})
    cfg = B.get_config(g.db)
    cats = [{"key": k, "label": v[0], "description": v[1], "size": v[4], "on": bool(cfg["categories"].get(k))}
            for k, v in B.CATEGORIES.items()]
    return jsonify({"config": cfg, "categories": cats, "rclone": bool(B.rclone_path(cfg))})


@bp.route("/test", methods=["POST"])
def test():
    cfg = B.get_config(g.db)
    cfg.update({k: v for k, v in (request.get_json(silent=True) or {}).items() if k in ("remote", "rclone")})
    try:
        return jsonify({"ok": True, "message": B.test_remote(cfg)})
    except B.BackupError as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@bp.route("/run", methods=["POST"])
def run_now():
    """'Back up now': runs even when automatic backups are off, in the background."""
    cfg = B.get_config(g.db)
    if not cfg["remote"]:
        return jsonify({"ok": False, "error": "Connect Google Drive (or choose another place) first."}), 400
    if not B.rclone_path(cfg):
        return jsonify({"ok": False, "error": "rclone is not installed yet — press Connect Google Drive."}), 400
    with B._LOCK_STATE:
        busy = B._RUN_STATE.get("running")
    if busy:
        return jsonify({"ok": True, "already": True})
    B.run_in_background(_db(), force=True)
    return jsonify({"ok": True})


@bp.route("/log")
def log():
    rows = g.db.execute("SELECT * FROM backup_log ORDER BY id DESC LIMIT 20").fetchall()
    return jsonify([dict(r) for r in rows])


@bp.route("/snapshots")
def snapshots():
    """The snapshots in the cloud — one rclone call. What each one contains is
    fetched only when you open it (``/snapshots/<name>``)."""
    cfg = B.get_config(g.db)
    if not cfg["remote"]:
        return jsonify({"ok": False, "error": "Backup isn't set up yet."}), 400
    try:
        snaps = B.list_remote_detailed(cfg)
    except B.BackupError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True, "snapshots": snaps[:30], "total": len(snaps)})


@bp.route("/snapshots/<name>")
def snapshot_detail(name):
    import re
    if not re.fullmatch(r"user-\d{8}T\d{6}Z\.db\.gz", name):
        return jsonify({"ok": False, "error": "Unknown snapshot."}), 400
    return jsonify(dict(B.snapshot_info(B.get_config(g.db), name), ok=True))


@bp.route("/restore", methods=["POST"])
def restore():
    d = request.get_json(force=True) or {}
    only = [c for c in (d.get("categories") or []) if c in B.CATEGORIES] or None
    if not d.get("name"):
        return jsonify({"ok": False, "error": "Choose a snapshot."}), 400
    with B._LOCK_STATE:
        busy = B._RUN_STATE.get("running")
    if busy:
        return jsonify({"ok": False, "error": "A backup or restore is running. Try again when it has finished."}), 409
    holder = {}

    def job(db_path):
        holder["result"] = B.restore(db_path, d["name"], only)
        B._RESTORE_RESULT.clear()
        B._RESTORE_RESULT.update(holder["result"])
    B._RESTORE_RESULT.clear()
    B.run_in_background(_db(), fn=job)
    return jsonify({"ok": True})


@bp.route("/restore/result")
def restore_result():
    return jsonify(dict(B._RESTORE_RESULT))


@bp.route("/connect-drive", methods=["GET", "POST"])
def connect_drive():
    """One click: install rclone if needed, Google sign-in, configure, switch on, first backup."""
    if request.method == "POST":
        st = B.connect_status()
        if st.get("state") not in ("downloading", "waiting", "finishing"):
            B._set_connect(state="downloading", message="Starting…")
            B.run_in_background(_db(), fn=B.connect_drive)
    return jsonify(B.connect_status())


@bp.route("/disconnect-drive", methods=["POST"])
def disconnect_drive():
    B.disconnect_drive(_db())
    return jsonify({"ok": True})


@bp.route("/connect-drive/cancel", methods=["POST"])
def connect_drive_cancel():
    B.cancel_connect()
    return jsonify({"ok": True})
