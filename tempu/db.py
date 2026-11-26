"""SQLite access layer for the TEMP-U local app.

The app keeps its data in two SQLite files in ``data/``:

``base.db``  the content as it is served: libraries -> chapters -> sections ->
             topics -> cards, collections, the search index. Built by
             ``tempu/loader.py`` from ``local/content``; your structure changes
             are applied to it too (and replayed after every rebuild). It is
             disposable: everything in it can be rebuilt from your content
             folder plus ``user.db``, so it is never backed up.

``user.db``  everything that is yours and can't be rebuilt: the change journal
             (changesets / revisions, see tempu/history.py), your topic edits
             and structure overrides, study state (progress, highlights, notes,
             reviews, decks...), settings, the index of files you added
             (data/blobs, see tempu/blobs.py) and backup state. This is the
             file that is backed up to the cloud (tempu/backup.py).

Every connection opens ``user.db`` as ``main`` and attaches ``base.db`` as
``base``. Table names are unique across the two files, so queries keep using
plain names (``topics``, ``progress``) and SQLite finds the right file.
"""
import os
import sqlite3

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _data_dir():
    v = os.environ.get("TEMPU_DATA")
    if v:
        return v
    legacy = os.environ.get("TEMPU_DB")          # older setups pointed at data/tempu.db
    if legacy:
        return os.path.dirname(os.path.abspath(legacy))
    return os.path.join(PROJECT, "data")


DATA_DIR = _data_dir()
DEFAULT_DB = os.path.join(DATA_DIR, "user.db")   # what callers pass around as "the db path"


def paths(db_path=None):
    """(user_db, base_db, data_dir) for a db path (the user.db path, or any file in the data dir)."""
    p = os.path.abspath(db_path or DEFAULT_DB)
    d = os.path.dirname(p)
    user = p if os.path.basename(p) == "user.db" else os.path.join(d, "user.db")
    return user, os.path.join(d, "base.db"), d


# ---------------------------------------------------------------- content (base.db)
# "{s}" is replaced by the schema name (base) so the tables land in base.db.
CONTENT_SQL = r"""
CREATE TABLE IF NOT EXISTS {s}.libraries (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    slug        TEXT,
    exam_scope  TEXT,
    sort_order  INTEGER DEFAULT 0,
    locked      INTEGER DEFAULT 0,
    icon_path   TEXT
);

CREATE TABLE IF NOT EXISTS {s}.chapters (
    id              TEXT PRIMARY KEY,
    library_id      TEXT NOT NULL REFERENCES libraries(id),
    title           TEXT NOT NULL,
    slug            TEXT,
    icon_path       TEXT,
    icon_alt        TEXT,
    is_public_sample INTEGER DEFAULT 0,
    sort_order      INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS {s}.idx_chapters_library ON chapters(library_id);

CREATE TABLE IF NOT EXISTS {s}.sections (
    id              TEXT PRIMARY KEY,
    chapter_id      TEXT NOT NULL REFERENCES chapters(id),
    title           TEXT NOT NULL,
    slug            TEXT,
    icon_path       TEXT,
    icon_alt        TEXT,
    is_public_sample INTEGER DEFAULT 0,
    sort_order      INTEGER DEFAULT 0,
    total_words     INTEGER DEFAULT 0,
    total_topics    INTEGER DEFAULT 0,
    next_section_id TEXT
);
CREATE INDEX IF NOT EXISTS {s}.idx_sections_chapter ON sections(chapter_id);

CREATE TABLE IF NOT EXISTS {s}.topics (
    id               TEXT PRIMARY KEY,
    section_id       TEXT NOT NULL REFERENCES sections(id),
    title            TEXT NOT NULL,
    sort_order       INTEGER DEFAULT 0,
    document_version INTEGER DEFAULT 1,
    icon_url         TEXT,
    document_html    TEXT,     -- pre-rendered BlockNote reader HTML
    plain_text       TEXT,     -- flattened text for search
    has_cards        INTEGER DEFAULT 0,
    updated_at       TEXT
);
CREATE INDEX IF NOT EXISTS {s}.idx_topics_section ON topics(section_id);

CREATE TABLE IF NOT EXISTS {s}.cards (
    id            TEXT PRIMARY KEY,
    topic_id      TEXT NOT NULL,
    note_id       TEXT,
    chapter_id    TEXT,
    library_id    TEXT,
    ordinal       INTEGER,
    kind          TEXT,
    is_beta       INTEGER DEFAULT 0,
    sort_order    INTEGER DEFAULT 0,
    front_json    TEXT,       -- raw Lexical side document (JSON)
    back_json     TEXT,
    front_text    TEXT,       -- plain text (search / preview)
    back_text     TEXT
);
CREATE INDEX IF NOT EXISTS {s}.idx_cards_topic ON cards(topic_id);
CREATE INDEX IF NOT EXISTS {s}.idx_cards_chapter ON cards(chapter_id);

CREATE TABLE IF NOT EXISTS {s}.collections (
    id          TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,          -- 'official' | 'personal'
    title       TEXT NOT NULL,
    description TEXT,
    exam_scope  TEXT,
    library_id  TEXT,
    library_title TEXT,
    item_count  INTEGER DEFAULT 0,
    share_state TEXT,
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS {s}.collection_items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    item_type     TEXT NOT NULL,        -- 'topic' | 'section'
    topic_id      TEXT,
    section_id    TEXT,
    chapter_id    TEXT,
    entry_id      TEXT,
    sort_order    INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS {s}.idx_colitems_collection ON collection_items(collection_id);

-- build info for the content (render_version, built_at)
CREATE TABLE IF NOT EXISTS {s}.meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

CONTENT_TABLES = ("libraries", "chapters", "sections", "topics", "cards",
                  "collections", "collection_items", "meta", "search_fts")

# ---------------------------------------------------------------- yours (user.db)
USER_SQL = r"""
CREATE TABLE IF NOT EXISTS main.progress (
    topic_id      TEXT PRIMARY KEY,
    completed     INTEGER DEFAULT 0,
    reopened      INTEGER DEFAULT 0,
    completed_at  TEXT,
    last_opened_at TEXT
);

CREATE TABLE IF NOT EXISTS main.highlights (
    id              TEXT PRIMARY KEY,
    topic_id        TEXT NOT NULL,
    color           TEXT DEFAULT 'yellow',
    selected_text   TEXT,
    prefix_text     TEXT,
    suffix_text     TEXT,
    start_block_id  TEXT,
    end_block_id    TEXT,
    start_offset    INTEGER,
    end_offset      INTEGER,
    document_version INTEGER,
    created_at      TEXT
);
CREATE INDEX IF NOT EXISTS main.idx_highlights_topic ON highlights(topic_id);

CREATE TABLE IF NOT EXISTS main.inline_notes (
    id              TEXT PRIMARY KEY,
    topic_id        TEXT NOT NULL,
    note_text       TEXT,
    selected_text   TEXT,
    prefix_text     TEXT,
    suffix_text     TEXT,
    start_block_id  TEXT,
    end_block_id    TEXT,
    start_offset    INTEGER,
    end_offset      INTEGER,
    document_version INTEGER,
    created_at      TEXT,
    updated_at      TEXT
);
CREATE INDEX IF NOT EXISTS main.idx_inlinenotes_topic ON inline_notes(topic_id);

CREATE TABLE IF NOT EXISTS main.topic_notes (
    topic_id    TEXT PRIMARY KEY,
    body_html   TEXT,          -- editable rich/plain note HTML
    plain_text  TEXT,
    updated_at  TEXT
);

CREATE TABLE IF NOT EXISTS main.card_reviews (
    card_id        TEXT PRIMARY KEY,
    state          TEXT DEFAULT 'new',   -- new | learning | review
    reps           INTEGER DEFAULT 0,
    lapses         INTEGER DEFAULT 0,
    ease           REAL DEFAULT 2.5,
    interval_days  REAL DEFAULT 0,
    due_at         TEXT,
    last_rating    INTEGER,
    last_reviewed_at TEXT
);
CREATE INDEX IF NOT EXISTS main.idx_reviews_due ON card_reviews(due_at);

CREATE TABLE IF NOT EXISTS main.decks (
    id             TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    color_key      TEXT,
    parent_deck_id TEXT,
    created_at     TEXT
);

CREATE TABLE IF NOT EXISTS main.deck_cards (
    deck_id   TEXT NOT NULL REFERENCES decks(id) ON DELETE CASCADE,
    card_id   TEXT NOT NULL,
    added_at  TEXT,
    PRIMARY KEY (deck_id, card_id)
);

CREATE TABLE IF NOT EXISTS main.study_log (
    day                  TEXT PRIMARY KEY,   -- YYYY-MM-DD
    english_video_seconds INTEGER DEFAULT 0,
    arabic_video_seconds  INTEGER DEFAULT 0,
    questions_answered    INTEGER DEFAULT 0,
    app_seconds           INTEGER DEFAULT 0,
    credit_seconds        INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS main.settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- current edited version of a topic (replaces the base HTML/title when present)
CREATE TABLE IF NOT EXISTS main.topic_edits (
    topic_id    TEXT PRIMARY KEY,
    html        TEXT NOT NULL,     -- edited reader HTML (replaces document_html)
    title       TEXT,              -- edited topic title (NULL = original)
    plain_text  TEXT,
    base_version INTEGER,          -- base document_version the edit was made on
    updated_at  TEXT
);

-- old per-topic snapshots (before the journal existed); read once by the migration
CREATE TABLE IF NOT EXISTS main.topic_edit_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id    TEXT NOT NULL,
    html        TEXT,
    title       TEXT,
    saved_at    TEXT
);

-- current state of your structure changes (see tempu/structure.py)
CREATE TABLE IF NOT EXISTS main.struct_overrides (
    kind        TEXT NOT NULL,       -- chapter | section | topic
    id          TEXT NOT NULL,
    created     INTEGER DEFAULT 0,   -- made by the user
    parent_id   TEXT,
    sort_order  INTEGER,
    title       TEXT,
    icon_path   TEXT,
    deleted     INTEGER DEFAULT 0,   -- 1 = in trash, 2 = deleted forever
    deleted_at  TEXT,
    payload     TEXT,                -- deleted rows (JSON) for restore
    updated_at  TEXT,
    PRIMARY KEY (kind, id)
);

-- per-section reading state: resume position, visits, bookmark
CREATE TABLE IF NOT EXISTS main.section_state (
    section_id     TEXT PRIMARY KEY,
    last_opened_at TEXT,
    open_count     INTEGER DEFAULT 0,
    last_topic_id  TEXT,
    scroll_ratio   REAL,
    bookmarked     INTEGER DEFAULT 0,
    updated_at     TEXT
);

-- ------------------------------------------------ change journal (tempu/history.py)
-- one user action = one changeset = one undo step
CREATE TABLE IF NOT EXISTS main.changesets (
    id          TEXT PRIMARY KEY,      -- time-sortable id
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    label       TEXT NOT NULL,         -- "Moved 'Syncope' to Cardio"
    kind        TEXT NOT NULL,         -- edit | structure | undo | redo | restore | import
    scope_kind  TEXT,                  -- topic | section | chapter | library
    scope_id    TEXT,
    session     TEXT,                  -- editor session (autosaves coalesce into one changeset)
    reverts     TEXT,                  -- JSON list of changeset ids this one inverted
    undone      INTEGER DEFAULT 0,     -- 1 = its effect is currently reverted
    n_rows      INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS main.idx_changesets_scope ON changesets(scope_id);

-- the state of one row before and after a changeset
CREATE TABLE IF NOT EXISTS main.revisions (
    id           INTEGER PRIMARY KEY,
    changeset_id TEXT NOT NULL REFERENCES changesets(id) ON DELETE CASCADE,
    seq          INTEGER NOT NULL,     -- order inside the changeset
    tbl          TEXT NOT NULL,        -- table the row lives in
    pk           TEXT NOT NULL,        -- JSON array of the primary key values
    op           TEXT NOT NULL,        -- I (created) | U (changed) | D (deleted)
    before       TEXT,                 -- JSON row, or '@<sha256>' -> doc_texts
    after        TEXT
);
CREATE INDEX IF NOT EXISTS main.idx_revisions_cs ON revisions(changeset_id, seq);
CREATE INDEX IF NOT EXISTS main.idx_revisions_row ON revisions(tbl, pk);

-- large revision payloads (topic HTML), stored once per distinct text, zlib-compressed
CREATE TABLE IF NOT EXISTS main.doc_texts (
    hash  TEXT PRIMARY KEY,
    body  BLOB NOT NULL
);

CREATE TABLE IF NOT EXISTS main.checkpoints (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    changeset_id  TEXT,                -- the last changeset included (NULL = before any)
    created_at    TEXT NOT NULL
);

-- ------------------------------------------------ files you add (tempu/blobs.py)
CREATE TABLE IF NOT EXISTS main.blobs (
    sha256        TEXT PRIMARY KEY,
    ext           TEXT NOT NULL,
    mime          TEXT,
    bytes         INTEGER,
    original_name TEXT,
    created_at    TEXT,
    uploaded_at   TEXT                 -- NULL = not in the cloud backup yet
);

-- ------------------------------------------------ cloud backup (tempu/backup.py)
CREATE TABLE IF NOT EXISTS main.backup_log (
    id          INTEGER PRIMARY KEY,
    started_at  TEXT,
    finished_at TEXT,
    ok          INTEGER,
    snapshot    TEXT,
    blobs_sent  INTEGER DEFAULT 0,
    bytes_sent  INTEGER DEFAULT 0,
    last_changeset TEXT,
    error       TEXT
);

CREATE TABLE IF NOT EXISTS main.user_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

USER_TABLES = ("progress", "highlights", "inline_notes", "topic_notes", "card_reviews",
               "decks", "deck_cards", "study_log", "settings", "topic_edits",
               "topic_edit_history", "struct_overrides", "section_state", "changesets",
               "revisions", "doc_texts", "checkpoints", "blobs", "backup_log", "user_meta")


def connect(db_path=None, attach_base=True, journal=True):
    """Open user.db with base.db attached as ``base``.

    ``journal`` installs the per-connection triggers that record changes made
    inside a :class:`tempu.history.Change` (they do nothing outside one).
    """
    user, base, d = paths(db_path)
    os.makedirs(d, exist_ok=True)
    conn = sqlite3.connect(user, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA main.journal_mode = WAL;")
    conn.execute("PRAGMA main.synchronous = FULL;")       # your data: survive power loss
    conn.execute("PRAGMA busy_timeout = 15000;")
    if attach_base:
        conn.execute("ATTACH DATABASE ? AS base", (base,))
        conn.execute("PRAGMA base.journal_mode = WAL;")
        conn.execute("PRAGMA base.synchronous = NORMAL;")  # rebuildable
    conn.execute("PRAGMA foreign_keys = ON;")
    if journal:
        from . import history
        history.install(conn)
    return conn


def init_content_schema(conn, schema="base"):
    conn.executescript(CONTENT_SQL.replace("{s}", schema))
    conn.commit()


def init_user_schema(conn):
    conn.executescript(USER_SQL)
    conn.commit()


def init_schema(conn):
    init_content_schema(conn)
    init_user_schema(conn)
    ensure_user_tables(conn)


def ensure_user_tables(conn):
    """Add tables/columns introduced after a database was first built."""
    conn.executescript(USER_SQL)
    for schema, table, col, decl in (("main", "topic_edits", "title", "TEXT"),
                                     ("main", "topic_edit_history", "title", "TEXT"),
                                     ("base", "libraries", "icon_path", "TEXT")):
        try:
            cols = {r[1] for r in conn.execute(f"PRAGMA {schema}.table_info({table})")}
        except sqlite3.OperationalError:
            continue
        if cols and col not in cols:
            conn.execute(f"ALTER TABLE {schema}.{table} ADD COLUMN {col} {decl}")
    conn.commit()


def init_search(conn):
    """Create the FTS5 full-text search index (in base.db) over topics and cards."""
    try:
        conn.executescript(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS base.search_fts USING fts5(
                ref UNINDEXED, kind UNINDEXED, title, body,
                library_id UNINDEXED, chapter_id UNINDEXED, section_id UNINDEXED,
                tokenize='porter unicode61'
            );
            """
        )
        conn.commit()
        return True
    except sqlite3.OperationalError:
        return False  # FTS5 not compiled in; caller falls back to LIKE


def base_ready(conn):
    """True when base.db has been built (has topics)."""
    try:
        return conn.execute("SELECT 1 FROM base.topics LIMIT 1").fetchone() is not None
    except sqlite3.OperationalError:
        return False
