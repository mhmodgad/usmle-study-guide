# local/ — your data (gitignored, not in the repo)

Place your data here so the app runs fully offline. Everything in this folder
is ignored by git.

```
local/
├── content/   # the captured study data the loader reads (JSON)
│   ├── library-step2ck-structure.json
│   ├── sections/<id>/section.json
│   ├── cards/step2ck/*.json
│   ├── collections*.json
│   └── user-topic-state.json         # optional: seeds your progress/notes/highlights
├── assets/    # ALL media — images, videos, fonts, chapter/section icons
│   ├── fonts/
│   ├── icons/           # icons/medical/*.webp  +  icons/icon-*.png (custom)
│   ├── media/           # topic images & self-hosted videos
│   └── editor/          # editor/quoteIcons/*.webp (logo, callout icons)
└── css/       # optional: source TEMP-U stylesheet, only needed to rebuild app.css
    └── reader-heartsounds.css (+ the other captured css parts)
```

The app resolves these automatically (no env vars needed) as long as they sit
under `local/`. You can still override any of them with the `TEMPU_CONTENT`,
`TEMPU_ASSETS`, `TEMPU_REPLICA_CSS` environment variables.
