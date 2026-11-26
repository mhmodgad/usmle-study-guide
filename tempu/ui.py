"""Two layouts side by side: "classic" (templates/) and "new" (templates_new/).

The new layout is an overlay: templates_new/ holds only the templates it
changes, everything else falls back to templates/. Each layout has its own
Jinja environment (and template cache), so a template in one can never leak
into the other. Routes call :func:`render_template` from here instead of
Flask's; it picks the environment for the layout the user chose.

The choice is stored in the ``ui`` setting and switched at /ui/new and
/ui/classic (both menus have a link).
"""
import os

from flask import current_app, g, render_template as _flask_render
from jinja2 import ChoiceLoader, FileSystemLoader

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEW_TEMPLATES = os.path.join(PROJECT, "templates_new")
LAYOUTS = ("classic", "new")


def install(app):
    app.jinja_env_new = app.jinja_env.overlay(
        loader=ChoiceLoader([FileSystemLoader(NEW_TEMPLATES), app.jinja_env.loader]))


def current():
    return getattr(g, "ui", "classic")


def render_template(name, **context):
    if current() == "new":
        app = current_app._get_current_object()
        app.update_template_context(context)
        return app.jinja_env_new.get_template(name).render(context)
    return _flask_render(name, **context)
