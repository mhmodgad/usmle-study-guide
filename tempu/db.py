"""SQLite access layer for the TEMP-U local app.

A single on-disk database (default: data/tempu.db) holds both the immutable
content library (libraries -> chapters -> sections -> topics -> cards,
collections) and the mutable per-user state (progress, highlights, inline
notes, topic notes, flashcard SRS reviews, decks, study log, settings).

The schema is created by SCHEMA_SQL; the content tables are populated by
tempu/loader.py from the captured ../content JSON. WAL mode + foreign keys are
enabled on every connection.
"""
import os
import sqlite3

DEFAULT_DB = os.environ.get(
    "TEMPU_DB",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "tempu.db"),
)

SCHEMA_SQL = r"""
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------- content
CREATE TABLE IF NOT EXISTS libraries (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    slug        TEXT,
    exam_scope  TEXT,
    sort_order  INTEGER DEFAULT 0,
    locked      INTEGER DEFAULT 0,
    icon_path   TEXT
);

CREATE TABLE IF NOT EXISTS chapters (
    id              TEXT PRIMARY KEY,
    library_id      TEXT NOT NULL REFERENCES libraries(id),
    title           TEXT NOT NULL,
    slug            TEXT,
    icon_path       TEXT,
    icon_alt        TEXT,
    is_public_sample INTEGER DEFAULT 0,
    sort_order      INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_chapters_library ON chapters(library_id);

CREATE TABLE IF NOT EXISTS sections (
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
CREATE INDEX IF NOT EXISTS idx_sections_chapter ON sections(chapter_id);

CREATE TABLE IF NOT EXISTS topics (
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
CREATE INDEX IF NOT EXISTS idx_topics_section ON topics(section_id);

CREATE TABLE IF NOT EXISTS cards (
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
CREATE INDEX IF NOT EXISTS idx_cards_topic ON cards(topic_id);
CREATE INDEX IF NOT EXISTS idx_cards_chapter ON cards(chapter_id);

CREATE TABLE IF NOT EXISTS collections (
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

CREATE TABLE IF NOT EXISTS collection_items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    item_type     TEXT NOT NULL,        -- 'topic' | 'section'
    topic_id      TEXT,
    section_id    TEXT,
    chapter_id    TEXT,
    entry_id      TEXT,
    sort_order    INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_colitems_collection ON collection_items(collection_id);

-- ---------------------------------------------------------------- user state
CREATE TABLE IF NOT EXISTS progress (
    topic_id      TEXT PRIMARY KEY,
    completed     INTEGER DEFAULT 0,
    reopened      INTEGER DEFAULT 0,
    completed_at  TEXT,
    last_opened_at TEXT
);

CREATE TABLE IF NOT EXISTS highlights (
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
CREATE INDEX IF NOT EXISTS idx_highlights_topic ON highlights(topic_id);

CREATE TABLE IF NOT EXISTS inline_notes (
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
CREATE INDEX IF NOT EXISTS idx_inlinenotes_topic ON inline_notes(topic_id);

CREATE TABLE IF NOT EXISTS topic_notes (
    topic_id    TEXT PRIMARY KEY,
    body_html   TEXT,          -- editable rich/plain note HTML
    plain_text  TEXT,
    updated_at  TEXT
);

CREATE TABLE IF NOT EXISTS card_reviews (
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
CREATE INDEX IF NOT EXISTS idx_reviews_due ON card_reviews(due_at);

CREATE TABLE IF NOT EXISTS decks (
    id             TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    color_key      TEXT,
    parent_deck_id TEXT,
    created_at     TEXT
);

CREATE TABLE IF NOT EXISTS deck_cards (
    deck_id   TEXT NOT NULL REFERENCES decks(id) ON DELETE CASCADE,
    card_id   TEXT NOT NULL,
    added_at  TEXT,
    PRIMARY KEY (deck_id, card_id)
);

CREATE TABLE IF NOT EXISTS study_log (
    day                  TEXT PRIMARY KEY,   -- YYYY-MM-DD
    english_video_seconds INTEGER DEFAULT 0,
    arabic_video_seconds  INTEGER DEFAULT 0,
    questions_answered    INTEGER DEFAULT 0,
    app_seconds           INTEGER DEFAULT 0,
    credit_seconds        INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- content edits made in the app's editor. Kept apart from the content
-- tables so rebuilding content from the source JSON never loses them.
CREATE TABLE IF NOT EXISTS topic_edits (
    topic_id    TEXT PRIMARY KEY,
    html        TEXT NOT NULL,     -- edited reader HTML (replaces document_html)
    title       TEXT,              -- edited topic title (NULL = original)
    plain_text  TEXT,
    base_version INTEGER,
    updated_at  TEXT
);

CREATE TABLE IF NOT EXISTS topic_edit_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id    TEXT NOT NULL,
    html        TEXT,
    title       TEXT,
    saved_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_edit_history_topic ON topic_edit_history(topic_id);

-- user changes to the library structure (see tempu/structure.py)
CREATE TABLE IF NOT EXISTS struct_overrides (
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
CREATE TABLE IF NOT EXISTS section_state (
    section_id     TEXT PRIMARY KEY,
    last_opened_at TEXT,
    open_count     INTEGER DEFAULT 0,
    last_topic_id  TEXT,
    scroll_ratio   REAL,
    bookmarked     INTEGER DEFAULT 0,
    updated_at     TEXT
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def connect(db_path=None):
    path = db_path or DEFAULT_DB
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    return conn


def init_schema(conn):
    conn.executescript(SCHEMA_SQL)
    conn.commit()


USER_TABLES_SQL = SCHEMA_SQL[SCHEMA_SQL.index("-- content edits made"):SCHEMA_SQL.index("CREATE TABLE IF NOT EXISTS meta (")] + """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def ensure_user_tables(conn):
    """Add tables introduced after a database was first built."""
    conn.executescript(USER_TABLES_SQL)
    for table, col, decl in (("topic_edits", "title", "TEXT"),
                             ("topic_edit_history", "title", "TEXT"),
                             ("libraries", "icon_path", "TEXT")):
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if cols and col not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
    conn.commit()


def init_search(conn):
    """Create the FTS5 full-text search index over topics and cards."""
    try:
        conn.executescript(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5(
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
