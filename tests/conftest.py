"""Test fixtures: a tiny generated library (no captured content needed)."""
import os
import sqlite3
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("TEMPU_SKIP_RERENDER", "1")
os.environ.setdefault("TEMPU_NO_BACKUP_WORKER", "1")

LIB = "8f7b96f9-7778-4908-af76-a8ad722cd68a"


def build_tiny(data_dir, legacy=False):
    """2 chapters x 3 sections x 3 topics, written straight into base.db
    (or into a single old-style tempu.db when ``legacy``)."""
    from tempu import db as dbmod
    os.makedirs(data_dir, exist_ok=True)
    if legacy:
        path = os.path.join(data_dir, "tempu.db")
        conn = sqlite3.connect(path)
        conn.executescript(dbmod.CONTENT_SQL.replace("{s}.", "").replace("{s}", "main"))
        conn.executescript(dbmod.USER_SQL.replace("main.", ""))
        conn.execute("DROP TABLE changesets"); conn.execute("DROP TABLE revisions")   # old DBs had no journal
    else:
        from tempu import migrate
        migrate.ensure(data_dir, quiet=True)
        conn = dbmod.connect(os.path.join(data_dir, "user.db"), journal=False)
        dbmod.init_schema(conn)
    conn.execute("INSERT INTO libraries(id,title,slug,exam_scope,sort_order,locked) VALUES(?,?,?,?,0,0)",
                 (LIB, "USMLE STEP 2CK", "step2ck", "step2ck"))
    ids = {"chapters": [], "sections": [], "topics": []}
    for c in range(2):
        cid = f"c{c}000000-0000-4000-8000-000000000000"
        ids["chapters"].append(cid)
        conn.execute("INSERT INTO chapters(id,library_id,title,sort_order) VALUES(?,?,?,?)", (cid, LIB, f"Chapter {c}", c))
        for s in range(3):
            sid = f"5{c}{s}00000-0000-4000-8000-000000000000"
            ids["sections"].append(sid)
            conn.execute("INSERT INTO sections(id,chapter_id,title,sort_order) VALUES(?,?,?,?)", (sid, cid, f"Section {c}.{s}", s))
            for t in range(3):
                tid = f"7{c}{s}{t}0000-0000-4000-8000-000000000000"
                ids["topics"].append(tid)
                conn.execute("INSERT INTO topics(id,section_id,title,sort_order,document_version,document_html,plain_text) "
                             "VALUES(?,?,?,?,1,?,?)", (tid, sid, f"Topic {c}.{s}.{t}", t,
                                                       f"<p>Original text {c}{s}{t} words here</p>", f"Original text {c}{s}{t} words here"))
    conn.commit()
    conn.close()
    return ids


@pytest.fixture
def env(tmp_path):
    data = str(tmp_path / "data")
    ids = build_tiny(data)
    from tempu.app import create_app
    app = create_app(db_path=os.path.join(data, "user.db"), assets_dir=str(tmp_path / "assets"))
    app.config["TESTING"] = True
    return {"app": app, "client": app.test_client(), "data": data, "ids": ids,
            "db": os.path.join(data, "user.db")}


def snapshot(db_path):
    from tempu import db as dbmod
    c = dbmod.connect(db_path, journal=False)
    out = {}
    for t, q in [("chapters", "SELECT id,library_id,title,icon_path,sort_order FROM chapters ORDER BY id"),
                 ("sections", "SELECT id,chapter_id,title,icon_path,sort_order FROM sections ORDER BY id"),
                 ("topics", "SELECT id,section_id,title,sort_order,icon_url FROM topics ORDER BY id"),
                 ("overrides", "SELECT kind,id,created,parent_id,sort_order,title,icon_path,deleted FROM struct_overrides ORDER BY kind,id"),
                 ("edits", "SELECT topic_id,html,title FROM topic_edits ORDER BY topic_id")]:
        out[t] = [tuple(r) for r in c.execute(q)]
    c.close()
    return out
