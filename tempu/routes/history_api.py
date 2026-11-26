"""JSON API for undo / redo / activity / checkpoints (see tempu/history.py)."""
import json

from flask import Blueprint, g, request, jsonify

from .. import history as H

bp = Blueprint("history_api", __name__, url_prefix="/api/history")


def _cs_out(c):
    reverts = json.loads(c["reverts"] or "[]") if c.get("reverts") else []
    return {"id": c["id"], "label": c["label"], "kind": c["kind"], "at": c["updated_at"],
            "created_at": c["created_at"], "scope_kind": c["scope_kind"], "scope_id": c["scope_id"],
            "undone": bool(c["undone"]), "rows": c["n_rows"], "reverts": reverts,
            "can_undo": not c["undone"] and c["kind"] != "import",
            "can_redo": bool(c["undone"]) and c["kind"] not in ("undo", "redo", "restore", "import")}


def _describe(conflicts):
    """Plain-language summary of what an undo would leave alone."""
    out = []
    for c in conflicts[:20]:
        t, pk = c["table"], c["pk"]
        name = None
        try:
            if t in ("chapters", "sections", "topics"):
                r = g.db.execute(f"SELECT title FROM {t} WHERE id=?", (pk[0],)).fetchone()
                name = r and r["title"]
            elif t == "struct_overrides":
                r = g.db.execute("SELECT title FROM struct_overrides WHERE kind=? AND id=?", pk).fetchone()
                name = r and r["title"]
            elif t == "topic_edits":
                r = g.db.execute("SELECT title FROM topics WHERE id=?", (pk[0],)).fetchone()
                name = r and r["title"]
        except Exception:  # noqa: BLE001
            pass
        what = {"changed since": "was changed again later", "exists again": "exists again",
                "gone": "no longer exists"}.get(c["what"], c["what"])
        fields = ", ".join(f for f in c["fields"] if f not in ("updated_at",))
        out.append(("'%s' " % name if name else "An item ") + what + (" (%s)" % fields if fields else ""))
    return out


@bp.route("/changesets")
def list_changesets():
    rows = H.changesets(g.db, limit=min(int(request.args.get("limit", 50)), 200),
                        before=request.args.get("before"), scope_id=request.args.get("scope"),
                        kind=request.args.get("kind"))
    return jsonify([_cs_out(c) for c in rows])


@bp.route("/state")
def state():
    """What Ctrl+Z / Ctrl+Shift+Z would do right now."""
    u, r = H.latest_undoable(g.db), H.latest_redoable(g.db)
    return jsonify({"undo": _cs_out(H.get(g.db, u)) if u else None,
                    "redo": _cs_out(H.get(g.db, r)) if r else None})


def _do_undo(cid, force):
    try:
        ch, conflicts = H.undo(g.db, cid, force=force)
    except KeyError:
        return jsonify({"ok": False, "error": "not found"}), 404
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    if ch is None and conflicts:
        return jsonify({"ok": False, "needs_confirm": True, "conflicts": _describe(conflicts)}), 409
    return jsonify({"ok": True, "changeset": ch.info() if ch else None,
                    "kept": _describe(conflicts)})


@bp.route("/undo/<cid>", methods=["POST"])
def undo(cid):
    if cid == "latest":
        cid = H.latest_undoable(g.db)
        if not cid:
            return jsonify({"ok": False, "error": "Nothing to undo"}), 404
    return _do_undo(cid, bool((request.get_json(silent=True) or {}).get("force")))


@bp.route("/redo/<cid>", methods=["POST"])
def redo(cid):
    """Redo = undo the undo. ``cid`` is the changeset that was undone, or 'latest'."""
    if cid == "latest":
        target = H.latest_redoable(g.db)
    else:
        r = g.db.execute("SELECT id FROM changesets WHERE kind IN ('undo','restore') AND undone=0 "
                         "AND reverts LIKE ? ORDER BY id DESC LIMIT 1", ('%"' + cid + '"%',)).fetchone()
        target = r[0] if r else None
    if not target:
        return jsonify({"ok": False, "error": "Nothing to redo"}), 404
    return _do_undo(target, bool((request.get_json(silent=True) or {}).get("force")))


@bp.route("/checkpoints", methods=["GET", "POST"])
def checkpoints():
    if request.method == "POST":
        name = ((request.get_json(silent=True) or {}).get("name") or "").strip() or "Checkpoint"
        last = g.db.execute("SELECT id FROM changesets ORDER BY id DESC LIMIT 1").fetchone()
        cpid = H.new_id()
        g.db.execute("INSERT INTO checkpoints(id,name,changeset_id,created_at) VALUES(?,?,?,?)",
                     (cpid, name, last[0] if last else None, H._now()))
        g.db.commit()
        return jsonify({"ok": True, "id": cpid})
    rows = g.db.execute("SELECT * FROM checkpoints ORDER BY created_at DESC").fetchall()
    out = []
    for r in rows:
        since = g.db.execute("SELECT COUNT(*) FROM changesets WHERE undone=0 AND kind!='import' AND id > ?",
                             (r["changeset_id"] or "",)).fetchone()[0]
        out.append({**dict(r), "changes_since": since})
    return jsonify(out)


@bp.route("/checkpoints/<cpid>/restore", methods=["POST"])
def checkpoint_restore(cpid):
    cp = g.db.execute("SELECT * FROM checkpoints WHERE id=?", (cpid,)).fetchone()
    if not cp:
        return jsonify({"ok": False, "error": "not found"}), 404
    ch = H.restore_to(g.db, cp["changeset_id"], "Restored checkpoint '%s'" % cp["name"])
    return jsonify({"ok": True, "changeset": ch.info() if ch else None})


@bp.route("/checkpoints/<cpid>", methods=["DELETE"])
def checkpoint_delete(cpid):
    g.db.execute("DELETE FROM checkpoints WHERE id=?", (cpid,))
    g.db.commit()
    return jsonify({"ok": True})
