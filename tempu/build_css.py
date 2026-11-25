"""Assemble static/css/app.css from the captured replica stylesheets.

Reads the most complete captured stylesheet (reader-heartsounds.css, which
includes the shell + BlockNote reader + flashcard styles), rewrites its
relative font/asset URLs (../assets/...) to absolute /assets/... so they
resolve regardless of page path, appends the replica's functional tweaks, and
writes the result to static/css/app.css.

Usage:  python -m tempu.build_css [--replica-css DIR]
"""
import argparse
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)


def _resolve_css():
    v = os.environ.get("TEMPU_REPLICA_CSS")
    if v:
        return v
    in_project = os.path.join(PROJECT, "local", "css")
    if os.path.isdir(in_project):
        return in_project
    return os.path.join(os.path.dirname(PROJECT), "tempu-replica", "css")


DEFAULT_REPLICA_CSS = _resolve_css()
OUT = os.path.join(PROJECT, "static", "css", "app.css")

BASE = "reader-heartsounds.css"      # superset: shell + reader + cards
EXTRA = ["functional.css", "replica.css"]


def build(replica_css=DEFAULT_REPLICA_CSS):
    parts = []
    base_path = os.path.join(replica_css, BASE)
    if not os.path.isfile(base_path):
        raise SystemExit(f"base css not found: {base_path}")
    with open(base_path, encoding="utf-8") as f:
        parts.append(f.read())
    for e in EXTRA:
        p = os.path.join(replica_css, e)
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as f:
                parts.append("\n/* --- %s --- */\n" % e + f.read())
    css = "\n".join(parts)
    # relative replica paths -> absolute asset route
    css = css.replace("../assets/", "/assets/").replace('url(assets/', 'url(/assets/')
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(css)
    print(f"wrote {OUT} ({len(css):,} bytes) from {base_path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--replica-css", default=DEFAULT_REPLICA_CSS)
    a = ap.parse_args()
    build(a.replica_css)
