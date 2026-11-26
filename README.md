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
│   ├── launch.py           # launcher: update from the public repo, then serve
│   ├── db.py               # SQLite schema + connection: user.db + attached base.db
│   ├── history.py          # change journal: undo / redo / versions / checkpoints
│   ├── blobs.py            # content-addressed store for files you add (data/blobs)
│   ├── backup.py           # rclone cloud backup + restore (worker, CLI)
│   ├── migrate.py          # one-time upgrade from the old single tempu.db
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
├── data/                   # base.db + user.db + blobs/ (gitignored)
├── requirements.txt
├── run.sh                  # Linux/macOS: launch the app
├── setup.sh                # Linux/macOS: one-time setup
└── run-windows.bat / setup-windows.bat   # Windows equivalents
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
| `TEMPU_DATA` | `data/` | Folder for `base.db`, `user.db`, `blobs/`, `backup/`. |

`loader.py` expects, under `TEMPU_CONTENT`:
`library-step2ck-structure.json`, `sections/<id>/section.json`,
`cards/step2ck/*.json`, `collections*.json`, and (optionally) a
`user-topic-state.json` snapshot for seeding progress/highlights/notes.

## Quick start

```bash
pip install -r requirements.txt
python -m tempu.build_css      # -> static/css/app.css   (from TEMPU_REPLICA_CSS)
python -m tempu.loader         # -> data/base.db          (from TEMPU_CONTENT)
python -m tempu.app --port 5000
# open http://127.0.0.1:5000/
```

`./setup.sh` does the same three steps inside a virtualenv, and `./run.sh`
starts the app (Linux/macOS). On Windows the same role is played by
`setup-windows.bat` + `run-windows.bat` — see [`WINDOWS.md`](WINDOWS.md).

### Launchers & automatic updates

Both platforms share one launcher: `python -m tempu.launch`. Before serving,
it checks the public GitHub repo for a newer `main` and applies it — but **only
when the repo is strictly ahead of your copy** (a fast-forward):

- Pulling a **public** repo needs **no GitHub account, login or SSH key**.
- A folder that was copied rather than cloned has no history to compare. On
  first run the launcher links it to the release its files came from without
  touching a file, and treats it like any other copy from then on. (Git itself
  is installed by `setup-windows.bat` if missing.)
- If your copy has commits the repo doesn't have, **nothing is changed** — the
  app just runs. Uncommitted edits survive an update too; if the update would
  overwrite one, the whole update is skipped and the files are named.
- Your data (`data/`, `local/content/`, `local/assets/media/`, `.venv/`) is
  gitignored and is never touched; `requirements.txt` changes are
  pip-installed automatically after an update.
- Offline / no git → a notice is printed and the installed version starts.
- Skip the check with `--no-update` (or `TEMPU_NO_UPDATE=1`); check without
  starting the server with `--update-only`.

On Windows, put your data in the in-project `local\` folder (`local\content`,
`local\assets`); it's gitignored.

Rebuild the database any time with `python -m tempu.loader`. By default it
**preserves your study state** (progress, notes, decks, reviews) and only
rebuilds the content tables. Flags:

- `--wipe-user` — reseed user state from the captured snapshot
- `--step1` — also load the STEP 1 flashcards
- `--no-reset` — don't clear content tables first
- `--rerender` — only re-render the stored topic documents (the app also does this
  automatically, once, after an update that changes the reader HTML)

## Features

| Area | Behaviour |
|---|---|
| **Libraries / chapters / sections** | Full 2CK structure with live progress bars. Pinned chapters show as cards; the rest as an expandable accordion of sections. STEP 1 shown locked. |
| **Reader** | Each topic rendered from its BlockNote document: columns, tables, images, self-hosted + YouTube video, callouts, colored headings. Per-topic complete toggle, whole-section complete, next-section link. |
| **Content editor** | "Edit content" on any topic: type and rearrange like a word processor — text styles (normal/H1–H3/lists/quote), bold/italic/underline/strike, text colour, highlight, block colour, indent/outdent, drag any block or image to a new place (⋮⋮ handle), drop/paste/upload images, resize and caption images, edit the topic title, links (Ctrl+K — to a web page or to any topic in the library, which then opens in the split view), tables (Tab between cells, add/remove rows and columns, header row), callout boxes, toggle lists, quotes, dividers, alignment, and paste from Word/web that keeps bold/italic/links/headings/lists. Auto-saves to `topic_edits` in `user.db` (survives content rebuilds); every version is kept in Version history and "Restore original" can be undone. Images you add are stored in `data/blobs/` (gitignored). |
| **Library navigation** | "Continue reading" (last sections + the topic you stopped at), bookmarked sections, a search box that finds chapters, sections **and topics** (press `/`), filters (not started / in progress / studied / needs revision / bookmarked / has notes / edited / not downloaded), "Revised N×", notes/highlight counts, last-opened dates, remembered open chapters. Chapter pages show each section's topic outline, reading time, prev/next chapter and "+ New section". |
| **Organize (structure editor)** | `/libraries/<id>/organize`: drag-and-drop tree of chapters › sections › topics. Add, rename (double-click / F2), change icons (upload), reorder (drag or Alt+↑/↓), move sections between chapters and topics between sections (drag or "Move to…"), delete to Trash, restore or delete forever. Stored in `struct_overrides` and re-applied after every `tempu.loader` rebuild. |
| **Reader** | Reading-progress bar, "continue where you left off", previous/next section across your own structure (Alt+←/→), reading time, bookmark, remembered collapsed topics, "+ Topic", per-topic add-below / move up / move down / move to another section / delete, double-click the section title to rename. |
| **Edit mode** | Names, icons/logos, order, adding and deleting are locked until you press **✎ Edit** (Libraries page, library page, chapter page, section reader). Then click a name to rename it, click an icon/logo to change it (icon library or upload). **Done** or Esc leaves edit mode. |
| **Edit sections on the chapter page** | In edit mode, on a section card: ✎ rename, click the icon to pick from the icon library or upload your own, ⋮⋮ drag cards to reorder, ⋯ for add-after / move to another chapter / move earlier-later / delete. The chapter's own name and icon are editable in its header. |
| **Image editing** | Click an image while editing a topic, then use the mouse: drag the corners/sides to resize, drag the round knob above it to rotate (snaps to 90°), drag the image sideways along its own row to align it left/center/right, drag it to another place to move it (drop on a block's left/right edge to put it **side by side**), and **Crop** lets you drag the crop edges directly on the image (Enter to apply). A small toolbar adds align, text wrap, flip, caption, replace and a ⋯ menu (fit width, 1:1, beside above/below, out of columns, alt text, duplicate, full view). Rotate/flip/crop save a new image file in `data/blobs/`. |
| **App icon** | The browser tab shows your logo from `local/assets` (`favicon.png`, `logos/applogo.webp` or `TEMPU_Logo.png`), or a neutral built-in icon. |
| **Cross-references & split view** | In-text links to other topics open the linked section in a split pane beside the current one (swap, open in new tab, close), scrolled to the exact paragraph. Links to topics that aren't in your local data say so instead of failing. |
| **Images** | Click any image to open it full-screen (click/scroll to zoom, Esc to close). |
| **Notes** | Topic notes (auto-saving rich-text drawer, server-side), inline notes, and multi-color highlights with text-quote re-anchoring. Search + chapter filter. |
| **Flashcards** | Card library tree by system; quick-review by topic / section / chapter / deck / due. Focused study session: reveal (Space), rate 1–4 with per-rating interval previews, cloze hide/reveal, shuffle, Open-topic. |
| **Spaced repetition** | SM-2 scheduler (`srs.py`); every rating persists a due date. "Due today" and per-deck new/learning/due counts are real. |
| **Decks** | Create decks, add cards by scope or individually, study, delete. Personal cards supported. |
| **Collections** | Official HY collections + personal collections with their items; create your own. |
| **Consistency** | Streaks, days studied, days-at-goal, heatmap, and a working "Log study activity" dialog. |
| **Settings** | Display name, avatar, daily goal, reader text size/spacing, theme (persisted), notifications. |
| **Search** | SQLite FTS5 full-text over every topic (LIKE fallback), in the header (⌘/Ctrl-K) and on `/search`. |

All writes go through the JSON API under `/api/*` and land in `data/user.db`.

## Data storage

Two SQLite files in `data/` (WAL mode), opened together on one connection
(`user.db` as `main`, `base.db` attached as `base`):

| File | Holds | Rebuildable? | Backed up |
|---|---|---|---|
| `data/base.db` | The library as served: libraries, chapters, sections, topics (pre-rendered HTML), cards, collections, search index. Built by `tempu.loader` from `local/content`, with your structure changes re-applied. | Yes, from `local/content` + `user.db` | Only if you tick it |
| `data/user.db` | Everything that is yours: the change journal, topic edits, structure changes, progress, highlights, notes, reviews, decks, settings, backup state. | No | Yes (the categories you choose) |
| `data/blobs/` | Images/icons you add, stored once under their SHA-256 and served at `/blobs/<sha>.<ext>`. | No | Yes, if ticked |
| `local/assets/media/` | Original topic images and videos. | You supply it | Only if you tick it |

An old single-file `data/tempu.db` is upgraded automatically on first start
(it is kept as `tempu.db.pre-migration`; old `/uploads/` images move into
`data/blobs/`). Flashcards keep their raw Lexical JSON and are rendered on
demand so cloze hide/reveal stays authoritative.

### Undo, history and checkpoints (`tempu/history.py`)

Every change to the library is one **changeset**: a label ("Moved 'Syncope'
to 'Cardio'") plus the before/after state of every row it touched, recorded
automatically by per-connection triggers. Undo writes the "before" values back
inside a new changeset (so undo can itself be undone); fields changed again
later are kept and reported. Autosaves of one editing session within 2 minutes
are one entry; large texts are stored once, compressed (`doc_texts`).

- **Undo toast** after any structure change; **Ctrl+Z / Ctrl+Shift+Z** outside text fields.
- **Version history** for each topic (⋮ menu, or the editor's menu): compare any
  version with the current text and restore it, or restore the original.
- **Settings → History**: every change, undo/redo any of them, and **checkpoints**
  (restoring one undoes everything after it in one step).
- Study state (progress, highlights, reviews) is backed up but not journaled.

### Cloud backup (`tempu/backup.py`, Settings → Backup)

Saving never depends on the network: a change is done when it is in
`user.db`. Backups run in the background with [rclone](https://rclone.org),
so any rclone remote works (Google Drive's free 15 GB is the default suggestion).
You choose:

- **on/off**, and **when**: shortly after changes (max every 10 min), every N hours, or only on "Back up now";
- **what**: content edits & history, study progress, highlights & notes,
  flashcards & decks, settings, files you added — and, unticked by default,
  the content database, captured JSON and original media;
- **where** (`remote:folder`) and **how many** snapshots to keep (latest N + daily + monthly).

Each run uploads new files first, then a filtered, gzipped snapshot of
`user.db` (`snapshots/YYYY/MM/user-<time>.db.gz` + `.json`), then
`manifest.json` last. Restore lets you pick a snapshot **and** which kinds of
data to bring back; a copy of your current `user.db` is kept in `data/backup/`
first. Backups are not encrypted.

One-time Google Drive setup:

```bash
rclone config create tempu-drive drive scope=drive.file   # browser sign-in; rclone sees only its own files
# Settings -> Backup: remote = tempu-drive:tempu-backup, Test connection, tick "Back up automatically"
```

Command line: `python -m tempu.backup status | run | list | restore [NAME] [--only notes,study]`
and `python -m tempu.backup config enabled=1 remote=tempu-drive:tempu-backup categories.media=1`.

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
