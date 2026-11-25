"""Flask application factory for the TEMP-U local app."""
import os

from flask import Flask, g, send_from_directory, redirect, abort

from . import db as dbmod
from . import service

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
# Where the captured fonts / icons / media / logos live (the replica's assets).
DEFAULT_ASSETS = os.environ.get(
    "TEMPU_ASSETS",
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
    app.config["DB_PATH"] = db_path or dbmod.DEFAULT_DB
    app.config["ASSETS_DIR"] = assets_dir or DEFAULT_ASSETS
    app.config["JSON_SORT_KEYS"] = False

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
            return d.strftime("%b %-d")
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
        }

    # ---- serve captured assets (fonts, icons, media, logos) ----
    @app.route("/assets/<path:relpath>")
    def assets(relpath):
        base = app.config["ASSETS_DIR"]
        full = os.path.normpath(os.path.join(base, relpath))
        if not full.startswith(os.path.normpath(base)):
            abort(404)
        directory, fname = os.path.split(full)
        if not os.path.isfile(full):
            abort(404)
        return send_from_directory(directory, fname, max_age=86400)

    # callout/quote icons referenced by rendered content as /editor/quoteIcons/<x>.webp
    @app.route("/editor/<path:relpath>")
    def editor_assets(relpath):
        base = os.path.join(app.config["ASSETS_DIR"], "editor")
        full = os.path.normpath(os.path.join(base, relpath))
        if not full.startswith(os.path.normpath(base)) or not os.path.isfile(full):
            abort(404)
        directory, fname = os.path.split(full)
        return send_from_directory(directory, fname, max_age=86400)

    @app.route("/")
    def index():
        return redirect("/dashboard")

    from .routes.pages import bp as pages_bp
    from .routes.api import bp as api_bp
    app.register_blueprint(pages_bp)
    app.register_blueprint(api_bp)

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
