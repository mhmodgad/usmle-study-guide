# USMLE Study Guide — local study app

A self-hosted reconstruction of the TEMP-U USMLE study platform
(`app.tempusmle.com`): a **Flask backend + SQLite database + server-rendered
frontend** that runs entirely on your machine. It reproduces the real app's
reader, flashcards, spaced repetition, notes, highlights, collections,
consistency tracking and settings, and persists all of your study activity
in a local database instead of `localStorage`.

> **Note on content:** this repository contains the **application only** — no
> educational content, no media/assets, and no built database. The TEMP-U
> learning content is copyrighted and is **not** redistributed here. To run the
> app you supply your own `content/` and `assets/` directories (see
> [Data you provide](#data-you-provide)). Everything in this repo is the engine
> that turns that data into the app.

## Architecture

```
usmle-study-guide/
├── tempu/                  # backend package
│   ├── app.py              # Flask factory, asset serving, shell/nav context
│   ├── db.py               # SQLite schema + connection (WAL, FTS5)
│   ├── loader.py           # builds the DB from your content dir
│   ├── build_css.py        # assembles static/css/app.css from the source CSS
│   ├── service.py          # shared queries + card/section helpers
│   ├── srs.py              # SM-2 spaced-repetition scheduler
│   ├── nav.py              # sidebar navigation + icons
│   ├── notifications_data.py
│   ├── data/               # small app config (e.g. the personal deck definition)
│   ├── render/             # document renderers
│   │   ├── bn_render.py    # BlockNote topic docs  -> reader HTML
│   │   └── card_render.py  # Lexical flashcards     -> card HTML (cloze hide/reveal)
│   └── routes/
│       ├── pages.py        # server-rendered pages
│       └── api.py          # JSON API (progress, review, notes, decks, search…)
├── templates/              # Jinja templates (TEMP-U CSS classes)
├── static/                 # app.css (built), overrides.css, JS
├── data/                   # tempu.db is built here (gitignored)
├── requirements.txt
└── setup.sh
```

## Requirements

- Python 3.9+
- Flask (`pip install -r requirements.txt`)
- A `content/` directory (your captured/exported study data — not included)
- An `assets/` directory (fonts, icons, images) and the source `css/` — not included

## Data you provide

The app is driven by two external directories you point it at with environment
variables (defaults assume they sit next to this repo):

| Env var | Default | What it is |
|---|---|---|
| `TEMPU_CONTENT` | `../content` | Structure, topic documents, flashcards, collections, and your captured user-state snapshot. Read by `loader.py`. |
| `TEMPU_ASSETS` | `../tempu-replica/assets` | Fonts, chapter/section icons, images — served at `/assets`. |
| `TEMPU_REPLICA_CSS` | `../tempu-replica/css` | Source stylesheet compiled into `static/css/app.css` by `build_css`. |
| `TEMPU_DB` | `data/tempu.db` | Output SQLite database. |

`loader.py` expects, under `TEMPU_CONTENT`:
`library-step2ck-structure.json`, `sections/<id>/section.json`,
`cards/step2ck/*.json`, `collections*.json`, and (optionally) a
`user-topic-state.json` snapshot for seeding progress/highlights/notes.

## Quick start

```bash
pip install -r requirements.txt
python -m tempu.build_css      # -> static/css/app.css   (from TEMPU_REPLICA_CSS)
python -m tempu.loader         # -> data/tempu.db         (from TEMPU_CONTENT)
python -m tempu.app --port 5000
# open http://127.0.0.1:5000/
```

`./setup.sh` does the same three steps inside a virtualenv.

Rebuild the database any time with `python -m tempu.loader`. By default it
**preserves your study state** (progress, notes, decks, reviews) and only
rebuilds the content tables. Flags:

- `--wipe-user` — reseed user state from the captured snapshot
- `--step1` — also load the STEP 1 flashcards
- `--no-reset` — don't clear content tables first

## Features

| Area | Behaviour |
|---|---|
| **Libraries / chapters / sections** | Full 2CK structure with live progress bars. Pinned chapters show as cards; the rest as an expandable accordion of sections. STEP 1 shown locked. |
| **Reader** | Each topic rendered from its BlockNote document: columns, tables, images, self-hosted + YouTube video, callouts, colored headings. Per-topic complete toggle, whole-section complete, next-section link. |
| **Notes** | Topic notes (auto-saving rich-text drawer, server-side), inline notes, and multi-color highlights with text-quote re-anchoring. Search + chapter filter. |
| **Flashcards** | Card library tree by system; quick-review by topic / section / chapter / deck / due. Focused study session: reveal (Space), rate 1–4 with per-rating interval previews, cloze hide/reveal, shuffle, Open-topic. |
| **Spaced repetition** | SM-2 scheduler (`srs.py`); every rating persists a due date. "Due today" and per-deck new/learning/due counts are real. |
| **Decks** | Create decks, add cards by scope or individually, study, delete. Personal cards supported. |
| **Collections** | Official HY collections + personal collections with their items; create your own. |
| **Consistency** | Streaks, days studied, days-at-goal, heatmap, and a working "Log study activity" dialog. |
| **Settings** | Display name, avatar, daily goal, reader text size/spacing, theme (persisted), notifications. |
| **Search** | SQLite FTS5 full-text over every topic (LIKE fallback), in the header (⌘/Ctrl-K) and on `/search`. |

All writes go through the JSON API under `/api/*` and land in `data/tempu.db`.

## Database

Single SQLite file (`data/tempu.db`, WAL mode). Content tables
(`libraries, chapters, sections, topics, cards, collections,
collection_items`) are rebuilt by the loader; user-state tables
(`progress, highlights, inline_notes, topic_notes, card_reviews, decks,
deck_cards, study_log, settings`) are yours and survive content rebuilds.
Topic documents are pre-rendered to HTML at load time; flashcards keep their
raw Lexical JSON and are rendered on demand so cloze hide/reveal stays
authoritative.

## Notes & limitations

- **Media & fonts** are served from `TEMPU_ASSETS`. Self-hosted images/videos
  are local; YouTube embeds stay remote.
- **STEP 1** content is not loaded by default; load its flashcards with `--step1`.
- **Consistency history** before "today" is approximated from each section's
  `lastOpenedAt`; everything logged from now on is exact.
- Ask TEMPU (AI chat) and billing/payments are intentionally stubs.

## Configuration

See [Data you provide](#data-you-provide) for the `TEMPU_*` environment
variables. All are optional and default to paths next to this repo.

## License

Application code only. The TEMP-U brand and educational content are the
property of their respective owners and are not included or licensed here.
