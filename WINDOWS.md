# Running on Windows (from scratch)

This guide sets up and runs the app on a Windows PC that has **nothing**
installed — no Python, no Git, no tools. The setup script installs everything
it needs.

---

## What you copy to the Windows PC

Copy the **whole project folder** (`usmle-study-guide`) to the Windows PC —
for example to `C:\usmle-study-guide`. Then add your data into the project's
`local\` folder (this folder is gitignored, so it is never in the repo):

```
usmle-study-guide\
├── setup-windows.bat        <- double-click this ONCE to install everything
├── run-windows.bat          <- double-click this to start the app
├── tempu\  templates\  static\  requirements.txt  README.md
├── data\                    <- the database is built/kept here
└── local\                   <- YOUR DATA GOES HERE (gitignored)
    ├── content\             <- the study content the app loads (JSON)
    ├── assets\              <- ALL media: images, videos, fonts, icons
    └── css\                 <- (optional) source stylesheet, only to rebuild app.css
```

You need **two** things from your current machine:

1. **Media + content.** Copy your `content` and `assets` into `local\content`
   and `local\assets` (see "Where to put media" below).
2. **The database** — you can either let the setup script build it from
   `local\content`, **or** copy your already-built `data\tempu.db` straight into
   the `data\` folder (faster, and keeps all your progress/notes/decks exactly).

> Quickest path: copy your existing `data\tempu.db` **and** `local\assets`.
> Then you don't need `local\content` at all — the database already contains the
> text, and `assets` provides the pictures/videos.

> **Copying the whole folder is fine.** If your copy happens to include a
> `.venv` or `__pycache__` from your Mac/Linux machine, don't worry —
> `setup-windows.bat` detects a non-Windows `.venv` and rebuilds it, and stale
> `.pyc` files are ignored. You do **not** have to delete anything before
> copying.

---

## Where to put media / images / videos

All media goes in **`local\assets\`**, mirroring how the app references it:

```
local\assets\
├── fonts\                         web fonts
├── icons\
│   ├── medical\*.webp             chapter / section icons (built-in set)
│   └── icon-*.png                 custom chapter icons (e.g. Nutrition)
├── media\<topicId>\<file>         topic images and self-hosted videos
└── editor\quoteIcons\*.webp       logo + callout icons
```

- **Images** for a topic live under `local\assets\media\<topicId>\`.
- **Videos** that are self-hosted live in the same place; YouTube videos are
  embedded from youtube.com and need no local file.
- **Icons/logos** live under `local\assets\icons\` and `local\assets\editor\`.

You don't configure any paths — as long as everything is under `local\assets\`,
the app finds it automatically. (Advanced: you can override with the
`TEMPU_ASSETS`, `TEMPU_CONTENT`, `TEMPU_REPLICA_CSS` environment variables.)

---

## Step by step

1. **Copy** the project folder to the PC (e.g. `C:\usmle-study-guide`).
2. **Add your data**: put `content` into `local\content` and `assets` into
   `local\assets`. (Or copy your prebuilt `data\tempu.db` into `data\`.)
3. **Double-click `setup-windows.bat`.** It will:
   - install Python 3.12 if it isn't already there,
   - create a private virtual environment (`.venv`),
   - install the one dependency (Flask),
   - build the database from `local\content` (unless `data\tempu.db` already exists).
   The first run takes a few minutes (Python download). If it tells you Python
   was just installed, **close the window, open the folder again, and
   double-click `setup-windows.bat` once more.**
4. **Double-click `run-windows.bat`.** Your browser opens at
   **http://127.0.0.1:5000/** and the app is running. Leave that black window
   open while you use the app; press **Ctrl+C** (or close it) to stop.

That's it — nothing is installed system-wide except Python; everything else
lives inside the project folder.

---

## Rebuilding / updating

- **Rebuild the database** (after changing content): open `run`'s folder, hold
  **Shift + right-click → "Open PowerShell window here"**, then:
  ```powershell
  .\.venv\Scripts\python.exe -m tempu.loader
  ```
  This keeps your progress/notes/decks and only rebuilds content. Add
  `--wipe-user` to reseed user state, or `--step1` to also load STEP 1 cards.
- **Rebuild the stylesheet** (only if you changed `local\css`):
  ```powershell
  .\.venv\Scripts\python.exe -m tempu.build_css
  ```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Python is not recognized" after install | Close the window, open a new one, run `setup-windows.bat` again. Windows only picks up the new PATH in fresh windows. |
| `setup-windows.bat` closes instantly | Run it from PowerShell to see the error: `powershell -ExecutionPolicy Bypass -File setup-windows.ps1` |
| Port 5000 is busy | Start on another port: `.\.venv\Scripts\python.exe -m tempu.app --port 5050` then open http://127.0.0.1:5050/ |
| Images/videos don't show | They're missing from `local\assets`. Check `local\assets\media\<topicId>\`. |
| No database / blank library | You have neither `data\tempu.db` nor `local\content`. Add one and re-run setup. |
| Windows SmartScreen warns on the Python installer | It's the official installer from python.org; choose "More info → Run anyway", or pre-install Python yourself from the Microsoft Store. |

---

## Requirements summary

- **Windows 10 or 11.**
- An internet connection **for the first setup only** (to download Python).
- ~Disk space for your `local\assets` media (the only large part).
- Everything else is handled by `setup-windows.bat`.
