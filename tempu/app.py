"""Flask application factory for the TEMP-U local app."""
import os

from flask import Flask, g, send_from_directory, redirect, abort, request

from . import db as dbmod
from . import service

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)


def resolve_dir(env_key, in_project, legacy):
    """Resolve a data directory: env var > in-project ./local/<x> > legacy ../ path."""
    v = os.environ.get(env_key)
    if v:
        return v
    if os.path.isdir(in_project):
        return in_project
    return legacy


# Where the fonts / icons / media / logos live. Prefer an in-project, gitignored
# ./local/assets folder (portable); fall back to the old replica assets dir.
DEFAULT_ASSETS = resolve_dir(
    "TEMPU_ASSETS",
    os.path.join(PROJECT, "local", "assets"),
    os.path.join(os.path.dirname(PROJECT), "tempu-replica", "assets"),
)

NAV_ITEMS = [
    ("dashboard", "/dashboard", "Dashboard"),
    ("mentorship", "/mentorship", "Mentorship"),
    ("libraries", "/libraries", "Libraries"),
    ("ask-tempu", "/ask-tempu", "Ask TEMPU"),
    ("collections", "/collections", "Collections"),
    ("notes", "/notes", "Notes"),
    ("flashcards", "/flashcards", "Flashcards"),
    ("consistency", "/consistency", "Consistency"),
    ("tutoring", "/tutoring", "Tutoring"),
    ("settings", "/settings", "Settings"),
]


def create_app(db_path=None, assets_dir=None):
    app = Flask(__name__,
                template_folder=os.path.join(PROJECT, "templates"),
                static_folder=os.path.join(PROJECT, "static"),
                static_url_path="/static")
    user_db, _base_db, data_dir = dbmod.paths(db_path)
    app.config["DB_PATH"] = user_db               # data/user.db (data/base.db is attached to it)
    app.config["DATA_DIR"] = data_dir
    app.config["ASSETS_DIR"] = assets_dir or DEFAULT_ASSETS
    app.config["JSON_SORT_KEYS"] = False
    # images added before the blob store existed (kept after the upgrade as uploads.migrated)
    app.config["UPLOADS_DIR"] = os.environ.get("TEMPU_UPLOADS", os.path.join(data_dir, "uploads"))
    app.config["MAX_CONTENT_LENGTH"] = 40 * 1024 * 1024

    # one-time upgrade of an old single-file database + start-up checks (safe, idempotent)
    from . import migrate
    try:
        migrate.ensure(data_dir)
    except Exception as e:  # noqa: BLE001
        print("  ! could not prepare your data:", e)
        raise
    if not os.environ.get("TEMPU_SKIP_RERENDER"):
        from . import loader as _loader
        _loader.ensure_render_current(app.config["DB_PATH"])

    @app.before_request
    def _open_db():
        g.db = dbmod.connect(app.config["DB_PATH"])

    @app.teardown_request
    def _close_db(exc):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    import datetime as _dt

    @app.template_filter("monthday")
    def _monthday(iso):
        if not iso:
            return ""
        try:
            d = _dt.datetime.fromisoformat(str(iso).replace("Z", "").split("+")[0])
            return f"{d:%b} {d.day}"
        except (ValueError, TypeError):
            return str(iso)[:10]

    from .nav import NAV, GO_BACK_SVG

    @app.context_processor
    def _inject():
        settings = service.all_settings()
        return {
            "nav_items": NAV_ITEMS,
            "nav": NAV,
            "go_back_svg": GO_BACK_SVG,
            "settings": settings,
            "theme": settings.get("theme", "dark"),
            "display_name": settings.get("displayName", "Student"),
            "initials": settings.get("initials", "ST"),
            "notif_unread": service.notif_unread(),
            "embed": request.args.get("embed") == "1",
            "icon_web": service.icon_web_path,
        }

    # ---- serve captured assets (fonts, icons, media, logos) ----
    @app.route("/assets/<path:relpath>")
    def assets(relpath):
        base = os.path.normpath(app.config["ASSETS_DIR"])
        full = os.path.normpath(os.path.join(base, relpath))
        if not full.startswith(base + os.sep):
            abort(404)
        directory, fname = os.path.split(full)
        if not os.path.isfile(full):
            abort(404)
        return send_from_directory(directory, fname, max_age=86400)

    # callout/quote icons referenced by rendered content as /editor/quoteIcons/<x>.webp
    @app.route("/editor/<path:relpath>")
    def editor_assets(relpath):
        base = os.path.normpath(os.path.join(app.config["ASSETS_DIR"], "editor"))
        full = os.path.normpath(os.path.join(base, relpath))
        if not full.startswith(base + os.sep):
            abort(404)
        if not os.path.isfile(full):
            # callout icons that aren't in your assets: use the built-in set (static/callout-icons)
            name = os.path.splitext(os.path.basename(relpath))[0]
            fallback = os.path.join(app.static_folder, "callout-icons", name + ".svg")
            if relpath.startswith("quoteIcons/") and os.path.isfile(fallback):
                return send_from_directory(os.path.dirname(fallback), os.path.basename(fallback), max_age=86400)
            abort(404)
        directory, fname = os.path.split(full)
        return send_from_directory(directory, fname, max_age=86400)

    # files you added (editor images, icons): data/blobs/<sha[:2]>/<sha>.<ext>.
    # The name is the content's hash, so the browser may cache it forever.
    from . import blobs as blobmod

    @app.route("/blobs/<name>")
    def blob(name):
        m = blobmod.NAME_RE.match(name)
        if not m:
            abort(404)
        full = blobmod.path_for(app.config["DATA_DIR"], m.group(1), m.group(2))
        if not os.path.isfile(full):
            abort(404)
        resp = send_from_directory(os.path.dirname(full), name, max_age=31536000)
        resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return resp

    # images added before the upgrade, at their old /uploads/ address
    @app.route("/uploads/<path:relpath>")
    def uploads(relpath):
        for folder in (app.config["UPLOADS_DIR"], app.config["UPLOADS_DIR"] + ".migrated"):
            base = os.path.normpath(folder)
            full = os.path.normpath(os.path.join(base, relpath))
            if full.startswith(base + os.sep) and os.path.isfile(full):
                directory, fname = os.path.split(full)
                return send_from_directory(directory, fname, max_age=86400)
        abort(404)

    # browser tab icon: your own logo from the assets folder if present,
    # otherwise a neutral built-in icon (branding is not shipped in the repo)
    @app.route("/favicon.ico")
    @app.route("/app-icon")
    def favicon():
        base = app.config["ASSETS_DIR"]
        for rel in ("favicon.png", "favicon.ico", "logos/applogo.webp", "TEMPU_Logo.png", "logos/applogo.png"):
            full = os.path.join(base, rel)
            if os.path.isfile(full):
                small = os.path.join(os.path.dirname(os.path.abspath(app.config["DB_PATH"])), "app-icon-64.png")
                try:   # a small copy loads faster; needs Pillow, otherwise send the original
                    if not os.path.isfile(small) or os.path.getmtime(small) < os.path.getmtime(full):
                        from PIL import Image
                        im = Image.open(full).convert("RGBA")
                        im.thumbnail((128, 128))
                        im.save(small, "PNG")
                    return send_from_directory(os.path.dirname(small), os.path.basename(small), max_age=86400)
                except Exception:  # noqa: BLE001
                    d, f = os.path.split(full)
                    return send_from_directory(d, f, max_age=86400)
        return send_from_directory(app.static_folder, "favicon.svg", max_age=86400)

    @app.route("/")
    def index():
        return redirect("/dashboard")

    from .routes.pages import bp as pages_bp
    from .routes.api import bp as api_bp
    from .routes.history_api import bp as history_bp
    from .routes.backup_api import bp as backup_bp
    app.register_blueprint(pages_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(history_bp)
    app.register_blueprint(backup_bp)

    # background cloud backup (does nothing until you turn it on in Settings -> Backup).
    # Started by the first request, so only the process that serves pages runs it
    # (not the file-watcher parent of the debug reloader, not scripts importing the app).
    @app.before_request
    def _start_backup_worker():
        if not app.config.get("_backup_worker") and not os.environ.get("TEMPU_NO_BACKUP_WORKER"):
            app.config["_backup_worker"] = True
            from . import backup
            backup.start_worker(app.config["DB_PATH"])

    return app


app = create_app()


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--debug", action="store_true")
    a = ap.parse_args()
    app.run(host=a.host, port=a.port, debug=a.debug)
