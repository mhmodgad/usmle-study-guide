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
    B.run_in_background(_db(), force=True)
    return jsonify({"ok": True})


@bp.route("/log")
def log():
    rows = g.db.execute("SELECT * FROM backup_log ORDER BY id DESC LIMIT 20").fetchall()
    return jsonify([dict(r) for r in rows])


@bp.route("/snapshots")
def snapshots():
    cfg = B.get_config(g.db)
    try:
        names = B.list_remote(cfg)
    except B.BackupError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    out = []
    for i, n in enumerate(names[:30]):
        info = B.snapshot_info(cfg, n) if i < 10 else {"name": n}
        out.append(info)
    return jsonify({"ok": True, "snapshots": out})


@bp.route("/restore", methods=["POST"])
def restore():
    d = request.get_json(force=True) or {}
    only = [c for c in (d.get("categories") or []) if c in B.CATEGORIES] or None
    if not d.get("name"):
        return jsonify({"ok": False, "error": "Choose a snapshot."}), 400
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
