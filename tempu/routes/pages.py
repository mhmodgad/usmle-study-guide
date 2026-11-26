"""Server-rendered HTML pages."""
import json

from flask import Blueprint, g, abort, request, redirect, url_for

from ..ui import render_template, current as ui_current

from .. import service as S

bp = Blueprint("pages", __name__)


# --------------------------------------------------------------- dashboard
@bp.route("/dashboard")
def dashboard():
    libs = S.library_rows()
    primary = next((l for l in libs if not l["locked"]), libs[0] if libs else None)
    done = total = 0
    if primary:
        done, total = S.library_progress(primary["id"])
    pct = round(100 * done / total) if total else 0
    # consistency summary
    cons = _consistency_summary()
    recent = g.db.execute(
        "SELECT t.id topic_id, t.title topic_title, s.id section_id, s.title section_title, "
        "s.chapter_id, c.library_id, p.last_opened_at, p.completed_at "
        "FROM progress p JOIN topics t ON t.id=p.topic_id "
        "JOIN sections s ON t.section_id=s.id JOIN chapters c ON s.chapter_id=c.id "
        "WHERE p.completed=1 AND p.completed_at IS NOT NULL "
        "ORDER BY p.completed_at DESC LIMIT 6"
    ).fetchall()
    # last-7-days week strip
    import datetime
    unit_sec = 15 * 60
    logmap = {r["day"]: r["credit_seconds"] for r in
              g.db.execute("SELECT day, credit_seconds FROM study_log")}
    week = []
    today = datetime.date.today()
    for i in range(6, -1, -1):
        d = today - datetime.timedelta(days=i)
        units = round((logmap.get(d.isoformat(), 0) or 0) / unit_sec, 1)
        week.append({"label": f"{d:%a} {d.day} {d:%b}", "units": units,
                     "future": d > today, "today": d == today})
    # quick access = pinned chapters
    pinned = []
    for r in g.db.execute("SELECT key FROM settings WHERE key LIKE 'pin:%'"):
        cid = r["key"].split(":", 1)[1]
        ch = g.db.execute("SELECT * FROM chapters WHERE id=?", (cid,)).fetchone()
        if ch:
            pinned.append(ch)
    today_panel = _today_panel() if ui_current() == "new" else None
    return render_template("dashboard.html", active="dashboard", library=primary,
                           done=done, total=total, pct=pct, cons=cons, recent=recent,
                           week=week, pinned=pinned, today=today_panel)


def _section_counts(section_id):
    r = g.db.execute("SELECT COUNT(*) n, SUM(CASE WHEN p.completed=1 THEN 1 ELSE 0 END) d "
                     "FROM topics t LEFT JOIN progress p ON p.topic_id=t.id WHERE t.section_id=?",
                     (section_id,)).fetchone()
    return (r["d"] or 0), (r["n"] or 0)


def _today_panel():
    """What to do now: where you stopped, what's next, cards due."""
    out = {"continue": None, "next": None, "due": 0, "new_in_decks": 0}
    row = g.db.execute(
        "SELECT ss.section_id, ss.last_topic_id, ss.last_opened_at, s.title, s.chapter_id, s.sort_order, "
        "c.title chapter_title, c.library_id FROM section_state ss JOIN sections s ON s.id=ss.section_id "
        "JOIN chapters c ON c.id=s.chapter_id WHERE ss.last_opened_at IS NOT NULL "
        "ORDER BY ss.last_opened_at DESC LIMIT 1").fetchone()
    if row:
        done, total = _section_counts(row["section_id"])
        topic = None
        if row["last_topic_id"]:
            topic = g.db.execute("SELECT COALESCE(e.title,t.title) title FROM topics t LEFT JOIN topic_edits e "
                                 "ON e.topic_id=t.id WHERE t.id=?", (row["last_topic_id"],)).fetchone()
        out["continue"] = {"section_id": row["section_id"], "title": row["title"],
                           "chapter": row["chapter_title"], "done": done, "total": total,
                           "topic_id": row["last_topic_id"] if topic else None,
                           "topic": topic["title"] if topic else None,
                           "finished": total and done >= total, "when": row["last_opened_at"]}
        # up next: the first unfinished section after it in the same chapter
        for s in g.db.execute("SELECT id, title FROM sections WHERE chapter_id=? AND sort_order > ? "
                              "ORDER BY sort_order", (row["chapter_id"], row["sort_order"])):
            d, n = _section_counts(s["id"])
            if n and d < n:
                out["next"] = {"section_id": s["id"], "title": s["title"], "done": d, "total": n,
                               "chapter": row["chapter_title"]}
                break
    now = _nowz()
    out["due"] = g.db.execute("SELECT COUNT(*) FROM card_reviews r WHERE r.due_at IS NOT NULL AND r.due_at <= ? AND " + _LIVE,
                              (now,)).fetchone()[0]
    out["new_in_decks"] = g.db.execute(
        "SELECT COUNT(DISTINCT dc.card_id) FROM deck_cards dc LEFT JOIN card_reviews r ON r.card_id=dc.card_id "
        "WHERE r.card_id IS NULL OR r.state='new'").fetchone()[0]
    return out


# --------------------------------------------------------------- libraries
@bp.route("/libraries")
def libraries():
    libs = []
    hide_locked = ui_current() == "new" and S.get_setting("showOnlineFeatures", "false") != "true"
    for l in S.library_rows():
        if l["locked"] and hide_locked:
            continue          # locked libraries can't be opened offline
        done, total = S.library_progress(l["id"]) if not l["locked"] else (0, 0)
        nchap = g.db.execute("SELECT COUNT(*) n FROM chapters WHERE library_id=?",
                             (l["id"],)).fetchone()["n"]
        libs.append({"row": l, "done": done, "total": total,
                     "pct": round(100 * done / total) if total else 0, "chapters": nchap})
    return render_template("libraries.html", active="libraries", libraries=libs)


@bp.route("/libraries/<library_id>")
def library(library_id):
    lib = g.db.execute("SELECT * FROM libraries WHERE id=?", (library_id,)).fetchone()
    if not lib:
        abort(404)
    if lib["locked"]:
        return render_template("locked.html", active="libraries", library=lib)
    sec_map = S.sections_by_chapter(library_id)
    chapters = []
    for c in S.chapter_rows(library_id):
        done, total = S.chapter_progress(c["id"])
        secs = sec_map.get(c["id"], [])
        pinned = g.db.execute("SELECT 1 FROM settings WHERE key=?",
                              (f"pin:{c['id']}",)).fetchone() is not None
        chapters.append({"row": c, "done": done, "total": total,
                         "sections": len(secs), "section_list": secs,
                         "pct": round(100 * done / total) if total else 0,
                         "icon": S.icon_web_path(c["icon_path"]), "pinned": pinned,
                         "sort": c["sort_order"]})
    chapters.sort(key=lambda x: (0 if x["pinned"] else 1, x["sort"]))
    pin_count = sum(1 for c in chapters if c["pinned"])
    sec_done, sec_total = S.sections_studied(library_id=library_id)
    done, total = S.library_progress(library_id)
    ov = S.library_overview(library_id)
    for c in chapters:
        for sec in c["section_list"]:
            sec.update(ov.get(sec["id"], {"topics": []}))
            sec["downloaded"] = sec["total"] > 0
            sec["status"] = ("empty" if not sec["total"] else "studied" if sec["studied"]
                             else "progress" if sec["done"] else "new")
        c["studied_secs"] = sum(1 for x in c["section_list"] if x["studied"])
        c["mine"] = g.db.execute("SELECT 1 FROM struct_overrides WHERE kind='chapter' AND id=? "
                                 "AND created=1", (c["row"]["id"],)).fetchone() is not None
    search_index = [{"s": sec["id"], "c": c["row"]["id"], "t": [t[1] for t in sec["topics"]],
                     "ti": [t[0] for t in sec["topics"]]}
                    for c in chapters for sec in c["section_list"]]
    return render_template("library.html", active="libraries", library=lib,
                           chapters=chapters, sec_done=sec_done, sec_total=sec_total,
                           libraries=S.library_rows(), pin_count=pin_count,
                           continue_rows=S.continue_reading(library_id, 3),
                           bookmarks=S.bookmarked_sections(library_id),
                           search_index=search_index,
                           pct=round(100 * done / total) if total else 0)


@bp.route("/libraries/<library_id>/organize")
def organize(library_id):
    lib = g.db.execute("SELECT * FROM libraries WHERE id=?", (library_id,)).fetchone()
    if not lib:
        abort(404)
    return render_template("organize.html", active="libraries", library=lib,
                           back_href="/libraries/%s" % library_id)


@bp.route("/libraries/<library_id>/chapters/<chapter_id>")
def chapter(library_id, chapter_id):
    ch = g.db.execute("SELECT * FROM chapters WHERE id=?", (chapter_id,)).fetchone()
    lib = g.db.execute("SELECT * FROM libraries WHERE id=?", (library_id,)).fetchone()
    if not ch or not lib:
        abort(404)
    sections = []
    for s in S.section_rows(chapter_id):
        done, total = S.section_progress(s["id"])
        ncards = g.db.execute(
            "SELECT COUNT(*) n FROM cards cd JOIN topics t ON cd.topic_id=t.id "
            "WHERE t.section_id=?", (s["id"],)).fetchone()["n"]
        topics = [dict(r) for r in g.db.execute(
            "SELECT t.id, COALESCE(e.title,t.title) title, COALESCE(p.completed,0) completed "
            "FROM topics t LEFT JOIN topic_edits e ON e.topic_id=t.id "
            "LEFT JOIN progress p ON p.topic_id=t.id WHERE t.section_id=? "
            "ORDER BY t.sort_order, t.rowid", (s["id"],))]
        st = g.db.execute("SELECT * FROM section_state WHERE section_id=?", (s["id"],)).fetchone()
        sections.append({"row": s, "done": done, "total": total, "cards": ncards,
                         "pct": round(100 * done / total) if total else 0,
                         "icon": S.icon_web_path(s["icon_path"]), "topics": topics,
                         "bookmarked": bool(st and st["bookmarked"]),
                         "last_opened": st["last_opened_at"] if st else None,
                         "minutes": max(1, round((s["total_words"] or 0) / 200)) if s["total_words"] else None})
    done, total = S.chapter_progress(chapter_id)
    sec_done, sec_total = S.sections_studied(chapter_id=chapter_id)
    chs = S.chapter_rows(library_id)
    ids = [c["id"] for c in chs]
    i = ids.index(chapter_id) if chapter_id in ids else -1
    prev_ch = chs[i - 1] if i > 0 else None
    next_ch = chs[i + 1] if 0 <= i < len(chs) - 1 else None
    return render_template("chapter.html", active="libraries", library=lib, chapter=ch,
                           sections=sections, sec_done=sec_done, sec_total=sec_total,
                           prev_ch=prev_ch, next_ch=next_ch,
                           pct=round(100 * done / total) if total else 0)


# --------------------------------------------------------------- reader
@bp.route("/libraries/<library_id>/chapters/<chapter_id>/sections/<section_id>")
def reader_full(library_id, chapter_id, section_id):
    return _reader(section_id)


@bp.route("/sections/<section_id>")
def reader_short(section_id):
    return _reader(section_id)


# in-document cross references, as stored in the content (/r/t/<topic>, /r/b/<topic>/<block>)
@bp.route("/r/t/<topic_id>")
@bp.route("/r/b/<topic_id>/<block_id>")
def xref(topic_id, block_id=None):
    hit = S.resolve_topic(topic_id)
    if not hit:
        return render_template("xref_missing.html", active="libraries", topic_id=topic_id), 404
    frag = ("#block-%s" % block_id) if block_id else ("#topic-%s" % topic_id)
    return redirect("/libraries/%s/chapters/%s/sections/%s%s" % (
        hit["library_id"], hit["chapter_id"], hit["section_id"], frag))


@bp.route("/libraries/<library_id>/chapters/<chapter_id>/sections/<section_id>/topics/<topic_id>/annotate")
def annotate(library_id, chapter_id, section_id, topic_id):
    t = g.db.execute("SELECT * FROM topics WHERE id=?", (topic_id,)).fetchone()
    if not t:
        abort(404)
    back = "/libraries/%s/chapters/%s/sections/%s#topic-%s" % (
        library_id, chapter_id, section_id, topic_id)
    return render_template("annotate.html", active="libraries", topic=t, back_href=back)


def _reader(section_id):
    sec = g.db.execute("SELECT * FROM sections WHERE id=?", (section_id,)).fetchone()
    if not sec:
        abort(404)
    ch = g.db.execute("SELECT * FROM chapters WHERE id=?", (sec["chapter_id"],)).fetchone()
    lib = g.db.execute("SELECT * FROM libraries WHERE id=?", (ch["library_id"],)).fetchone()
    topics = S.topic_rows(section_id)
    tids = [t["id"] for t in topics]
    prog = _progress_map(tids)
    notes = {r["topic_id"]: r for r in g.db.execute(
        "SELECT topic_id FROM topic_notes WHERE topic_id IN (%s)" %
        ",".join("?" * len(tids)) if tids else "SELECT topic_id FROM topic_notes WHERE 0",
        tids)} if tids else {}
    hi = _grouped(tids, "highlights")
    inl = _grouped(tids, "inline_notes")
    prv, nxt = S.section_neighbours(section_id)
    st = g.db.execute("SELECT * FROM section_state WHERE section_id=?", (section_id,)).fetchone()
    sec_mine = g.db.execute("SELECT 1 FROM struct_overrides WHERE kind='section' AND id=? AND created=1",
                            (section_id,)).fetchone() is not None
    words = sum(len((t["plain_text"] or "").split()) for t in topics)
    topic_views = []
    for t in topics:
        topic_views.append({
            "row": t,
            "completed": prog.get(t["id"], {}).get("completed", 0),
            "has_note": t["id"] in notes,
            "highlights": hi.get(t["id"], []),
            "inline_notes": inl.get(t["id"], []),
        })
    sec_done = sum(1 for t in topics if prog.get(t["id"], {}).get("completed"))
    import json as _json
    annotations = {}
    for tid in tids:
        annotations[tid] = {
            "highlights": [{"id": h["id"], "color": h["color"],
                            "selected_text": h["selected_text"],
                            "prefix_text": h["prefix_text"], "suffix_text": h["suffix_text"]}
                           for h in hi.get(tid, [])],
            "inlineNotes": [{"id": n["id"], "note_text": n["note_text"],
                             "selected_text": n["selected_text"],
                             "prefix_text": n["prefix_text"], "suffix_text": n["suffix_text"]}
                            for n in inl.get(tid, [])],
        }
    # section header image intentionally left blank for all sections
    banner = None
    sec_cards = g.db.execute("SELECT (SELECT COUNT(*) FROM cards WHERE topic_id IN (SELECT id FROM topics WHERE section_id=?)) "
                             "+ (SELECT COUNT(*) FROM my_cards WHERE topic_id IN (SELECT id FROM topics WHERE section_id=?))",
                             (sec["id"], sec["id"])).fetchone()[0]
    return render_template("reader.html", active="libraries", library=lib, chapter=ch, sec_cards=sec_cards,
                           section=sec, topics=topic_views, next_section=nxt, prev_section=prv,
                           section_state=dict(st) if st else {}, sec_mine=sec_mine,
                           read_minutes=max(1, round(words / 200)) if words else 0,
                           sec_done=sec_done, sec_total=len(topics), banner=banner,
                           lib_chapters=S.chapter_rows(lib["id"]),
                           chap_sections=S.section_rows(ch["id"]),
                           # "<" escaped: note text like "</script>" can't end the data block
                           annotations_json=_json.dumps(annotations).replace("<", "\\u003c"))


# --------------------------------------------------------------- flashcards
@bp.route("/flashcards")
def flashcards():
    decks = g.db.execute("SELECT * FROM decks ORDER BY created_at").fetchall()
    deck_views = []
    for d in decks:
        stats = _deck_stats(d["id"])
        deck_views.append({"row": d, **stats})
    due_total = g.db.execute(
        "SELECT COUNT(*) n FROM card_reviews r WHERE r.due_at IS NOT NULL AND r.due_at<=? AND " + _LIVE,
        (_nowz(),)).fetchone()["n"]
    weak = []
    if ui_current() == "new":
        weak = g.db.execute(
            "SELECT x.topic_id, COALESCE(e.title, t.title, 'Cards in your own decks') title, COUNT(*) n, SUM(x.lapses) lapses FROM ("
            " SELECT c.topic_id, r.lapses FROM card_reviews r JOIN cards c ON c.id=r.card_id"
            "  WHERE r.lapses>0 OR r.last_rating=1"
            " UNION ALL SELECT m.topic_id, r.lapses FROM card_reviews r JOIN my_cards m ON m.id=r.card_id"
            "  WHERE r.lapses>0 OR r.last_rating=1) x"
            " LEFT JOIN topics t ON t.id=x.topic_id LEFT JOIN topic_edits e ON e.topic_id=x.topic_id"
            " GROUP BY x.topic_id ORDER BY lapses DESC, n DESC LIMIT 8").fetchall()
    return render_template("flashcards.html", active="flashcards", decks=deck_views,
                           due_total=due_total, weak=weak)


@bp.route("/flashcards/library")
def flashcards_library():
    # full 2CK tree with per-chapter/section/topic card counts
    lib_id = request.args.get("library") or S._step2ck()
    chapters = []
    for c in S.chapter_rows(lib_id):
        sections = []
        ch_cards = 0
        for s in S.section_rows(c["id"]):
            rows = g.db.execute(
                "SELECT t.id, t.title, COUNT(cd.id) cards "
                "FROM topics t LEFT JOIN cards cd ON cd.topic_id=t.id "
                "WHERE t.section_id=? GROUP BY t.id HAVING cards>0 ORDER BY t.sort_order",
                (s["id"],)).fetchall()
            sc = sum(r["cards"] for r in rows)
            if sc:
                ch_cards += sc
                sections.append({"row": s, "topics": rows, "cards": sc})
        if ch_cards:
            chapters.append({"row": c, "sections": sections, "cards": ch_cards,
                             "icon": S.icon_web_path(c["icon_path"])})
    libs = [l for l in S.library_rows()]
    return render_template("flashcards_library.html", active="flashcards",
                           chapters=chapters, library_id=lib_id, libraries=libs)


@bp.route("/flashcards/review")
def review():
    scope = request.args.get("scope", "all")
    scope_id = request.args.get("id", "")
    title = request.args.get("title", "Quick review")
    back_href = request.args.get("back") or request.referrer or "/flashcards"
    return render_template("review.html", active="flashcards", scope=scope,
                           scope_id=scope_id, title=title, back_href=back_href)


@bp.route("/flashcards/decks/<deck_id>")
def deck(deck_id):
    d = g.db.execute("SELECT * FROM decks WHERE id=?", (deck_id,)).fetchone()
    if not d:
        abort(404)
    cards = g.db.execute(
        "SELECT c.*, t.title topic_title FROM deck_cards dc "
        "JOIN cards c ON c.id=dc.card_id LEFT JOIN topics t ON t.id=c.topic_id "
        "WHERE dc.deck_id=? ORDER BY dc.added_at", (deck_id,)).fetchall()
    views = [S.render_card(c) for c in cards] + [S.render_my_card(r) for r in S.my_cards_for_scope("deck", deck_id)]
    stats = _deck_stats(deck_id)
    stats.pop("cards", None)  # the template's `cards` is the card list itself
    return render_template("deck.html", active="flashcards", deck=d, cards=views, **stats)


@bp.route("/flashcards/stats")
def flashcards_stats():
    total = g.db.execute("SELECT COUNT(*) n FROM cards").fetchone()["n"]
    reviewed = g.db.execute("SELECT COUNT(*) n FROM card_reviews r WHERE " + _LIVE).fetchone()["n"]
    due = g.db.execute("SELECT COUNT(*) n FROM card_reviews r WHERE r.due_at<=? AND " + _LIVE,
                       (_nowz(),)).fetchone()["n"]
    by_state = {r["state"]: r["n"] for r in g.db.execute(
        "SELECT state, COUNT(*) n FROM card_reviews r WHERE " + _LIVE + " GROUP BY state")}
    return render_template("flashcards_stats.html", active="flashcards", total=total,
                           reviewed=reviewed, due=due, by_state=by_state)


# --------------------------------------------------------------- notes
@bp.route("/notes")
def notes():
    view = request.args.get("view", "topic")
    chapter_filter = request.args.get("chapter")
    if view == "inline":
        rows = g.db.execute(
            "SELECT n.*, t.title topic_title, s.id section_id, s.title section_title, "
            "s.chapter_id, c.title chapter_title, c.library_id "
            "FROM inline_notes n JOIN topics t ON t.id=n.topic_id "
            "JOIN sections s ON t.section_id=s.id JOIN chapters c ON s.chapter_id=c.id "
            "ORDER BY n.updated_at DESC").fetchall()
    else:
        q = ("SELECT n.topic_id, n.plain_text, n.updated_at, t.title topic_title, "
             "s.id section_id, s.title section_title, s.chapter_id, "
             "c.title chapter_title, c.library_id "
             "FROM topic_notes n JOIN topics t ON t.id=n.topic_id "
             "JOIN sections s ON t.section_id=s.id JOIN chapters c ON s.chapter_id=c.id ")
        params = []
        if chapter_filter:
            q += "WHERE c.id=? "
            params.append(chapter_filter)
        q += "ORDER BY n.updated_at DESC"
        rows = g.db.execute(q, params).fetchall()
    chapters = g.db.execute(
        "SELECT c.id, c.title, COUNT(*) n FROM topic_notes tn "
        "JOIN topics t ON t.id=tn.topic_id JOIN sections s ON t.section_id=s.id "
        "JOIN chapters c ON s.chapter_id=c.id GROUP BY c.id ORDER BY c.sort_order").fetchall()
    topic_count = g.db.execute("SELECT COUNT(*) n FROM topic_notes").fetchone()["n"]
    inline_count = g.db.execute("SELECT COUNT(*) n FROM inline_notes").fetchone()["n"]
    return render_template("notes.html", active="notes", view=view, notes=rows,
                           chapters=chapters, topic_count=topic_count,
                           inline_count=inline_count, chapter_filter=chapter_filter)


@bp.route("/notes/export.md")
def notes_export():
    """All your notes, passage notes and highlights as one Markdown file,
    grouped by chapter > section > topic in book order."""
    from flask import Response
    chapter_filter = request.args.get("chapter")
    loc = ("JOIN topics t ON t.id=x.topic_id JOIN sections s ON s.id=t.section_id "
           "JOIN chapters c ON c.id=s.chapter_id ")
    order_cols = "c.sort_order, c.title, s.sort_order, s.title, t.sort_order, t.title"
    sel = ("c.title chapter_title, s.title section_title, t.title topic_title, "
           "c.sort_order co, s.sort_order so, t.sort_order tso")
    where = " WHERE c.id=?" if chapter_filter else ""
    args = [chapter_filter] if chapter_filter else []
    items = []
    for r in g.db.execute(f"SELECT {sel}, x.plain_text body FROM topic_notes x {loc}{where}", args):
        items.append((r, 0, "", r["body"]))
    for r in g.db.execute(f"SELECT {sel}, x.selected_text quote, x.note_text body FROM inline_notes x {loc}{where}", args):
        items.append((r, 1, r["quote"], r["body"]))
    for r in g.db.execute(f"SELECT {sel}, x.selected_text quote FROM highlights x {loc}{where}", args):
        items.append((r, 2, r["quote"], ""))
    import re as _re
    _junk = _re.compile("[\u200b\u200c\u200d\ufeff\ufffc]")
    items = [(r, k, _junk.sub("", q or ""), _junk.sub("", b or "")) for r, k, q, b in items]
    items.sort(key=lambda i: (i[0]["co"] or 0, i[0]["chapter_title"] or "", i[0]["so"] or 0, i[0]["section_title"] or "",
                              i[0]["tso"] or 0, i[0]["topic_title"] or "", i[1]))
    out, last = ["# My notes\n"], (None, None, None)
    for r, kind, quote, body in items:
        ch, se, to = r["chapter_title"], r["section_title"], r["topic_title"]
        if ch != last[0]:
            out.append(f"\n## {ch}\n")
        if (ch, se) != last[:2]:
            out.append(f"\n### {se}\n")
        if (ch, se, to) != last:
            out.append(f"\n#### {to}\n")
        last = (ch, se, to)
        if kind == 0 and (body or "").strip():
            out.append((body or "").strip() + "\n")
        elif kind == 1:
            out.append("> " + " ".join((quote or "").split()) + "\n")
            if (body or "").strip():
                out.append("\n" + body.strip() + "\n")
        elif kind == 2 and (quote or "").strip():
            out.append("- \u201c" + " ".join(quote.split()) + "\u201d\n")
    if not items:
        out.append("\n_No notes or highlights yet._\n")
    return Response("".join(out), mimetype="text/markdown",
                    headers={"Content-Disposition": "attachment; filename=tempu-notes.md"})


# --------------------------------------------------------------- collections
@bp.route("/collections")
def collections():
    tab = request.args.get("tab", "personal")
    kind = "official" if tab == "tempu-hy" else "personal"
    if kind == "personal":
        rows = g.db.execute(
            "SELECT m.*, 'personal' kind, NULL library_title, "
            "(SELECT COUNT(*) FROM my_collection_items i WHERE i.collection_id=m.id) item_count "
            "FROM my_collections m ORDER BY m.created_at DESC, m.rowid DESC").fetchall()
    else:
        rows = g.db.execute(
            "SELECT * FROM collections WHERE kind='official' ORDER BY rowid").fetchall()
    has_official = g.db.execute(
        "SELECT COUNT(*) n FROM collections WHERE kind='official'").fetchone()["n"] > 0
    return render_template("collections.html", active="collections", tab=tab,
                           collections=rows, has_official=has_official)


@bp.route("/collections/<collection_id>")
def collection(collection_id):
    col = g.db.execute("SELECT m.*, 'personal' kind, NULL library_title FROM my_collections m WHERE id=?",
                       (collection_id,)).fetchone()
    items_table = "my_collection_items"
    if not col:
        col = g.db.execute("SELECT * FROM collections WHERE id=? AND kind='official'", (collection_id,)).fetchone()
        items_table = "collection_items"
    if not col:
        abort(404)
    items = g.db.execute(
        "SELECT ci.*, "
        "t.title topic_title, ts.id tsec_id, "
        "sec.title section_title, "
        "COALESCE(ch.id, ch2.id) chapter_id, "
        "COALESCE(ch.title, ch2.title) chapter_title, "
        "COALESCE(ch.library_id, ch2.library_id) library_id, "
        "COALESCE(ts.id, ci.section_id) open_section "
        "FROM " + items_table + " ci "
        "LEFT JOIN topics t ON t.id=ci.topic_id "
        "LEFT JOIN sections ts ON ts.id=t.section_id "
        "LEFT JOIN chapters ch ON ch.id=ts.chapter_id "
        "LEFT JOIN sections sec ON sec.id=ci.section_id "
        "LEFT JOIN chapters ch2 ON ch2.id=sec.chapter_id "
        "WHERE ci.collection_id=? ORDER BY ci.sort_order", (collection_id,)).fetchall()
    views = []
    summary = {"completed": 0, "in_progress": 0, "not_started": 0}
    for it in items:
        icon_section = it["open_section"] if it["item_type"] == "topic" else it["section_id"]
        irow = g.db.execute("SELECT icon_path FROM sections WHERE id=?",
                            (icon_section,)).fetchone() if icon_section else None
        icon = S.icon_web_path(irow["icon_path"]) if irow else None
        if it["item_type"] == "topic":
            title = it["topic_title"]
            breadcrumb = " · ".join(x for x in (it["section_title"], it["chapter_title"]) if x)
            p = g.db.execute("SELECT completed FROM progress WHERE topic_id=?",
                             (it["topic_id"],)).fetchone()
            pct = 100 if (p and p["completed"]) else 0
            open_href = ("/sections/%s#topic-%s" % (it["open_section"], it["topic_id"])
                         if it["open_section"] else "#")
            verb = "topic"
        else:  # section
            title = it["section_title"] or it["chapter_title"]
            breadcrumb = " · ".join(x for x in (it["chapter_title"], col["library_title"]) if x)
            done, total = S.section_progress(it["section_id"]) if it["section_id"] else (0, 0)
            pct = round(100 * done / total) if total else 0
            open_href = "/sections/%s" % it["section_id"] if it["section_id"] else "#"
            verb = "section"
        state = "Completed" if pct >= 100 else ("In progress" if pct > 0 else "Not started")
        key = "completed" if pct >= 100 else ("in_progress" if pct > 0 else "not_started")
        summary[key] += 1
        action = ("Open " + verb) if pct > 0 else ("Start " + verb)
        views.append({"type": it["item_type"], "title": title, "breadcrumb": breadcrumb,
                      "pct": pct, "state": state, "open_href": open_href,
                      "icon": icon, "action": action})
    return render_template("collection.html", active="collections", collection=col,
                           items=views, summary=summary)


# --------------------------------------------------------------- consistency
@bp.route("/consistency")
def consistency():
    cons = _consistency_summary(full=True)
    return render_template("consistency.html", active="consistency", cons=cons)


# --------------------------------------------------------------- settings
@bp.route("/settings")
def settings_index():
    return redirect("/settings/account")


@bp.route("/settings/<page>")
def settings_sub(page):
    valid = {"account", "personal", "preferences", "library", "notifications", "password",
             "history", "backup"}
    if page not in valid:
        abort(404)
    return render_template("settings_%s.html" % page, active="settings",
                           current=S.all_settings())


@bp.route("/activity")
def activity():
    return redirect("/settings/history")


# --------------------------------------------------------------- search
@bp.route("/search")
def search_page():
    q = request.args.get("q", "").strip()
    lib = S._step2ck() if hasattr(S, "_step2ck") else None
    chapters = S.chapter_rows(lib) if lib else []
    return render_template("search.html", active="", q=q, chapters=chapters,
                           kind=request.args.get("kind", "all"), chapter=request.args.get("chapter", ""))


# --------------------------------------------------------------- simple/marketing
@bp.route("/mentorship")
def mentorship():
    return render_template("simple.html", active="mentorship", title="Mentorship",
                           body="One-to-one mentorship and progress tracking.")


@bp.route("/ask-tempu")
def ask_tempu():
    return render_template("simple.html", active="ask-tempu", title="Ask TEMPU",
                           body="TEMPU AI chat requires live AI access (not available offline).")


@bp.route("/tutoring")
def tutoring():
    return render_template("simple.html", active="tutoring", title="Tutoring",
                           body="1-to-1 tutoring over Zoom.")


@bp.route("/billing")
def billing():
    return render_template("simple.html", active="", title="Billing",
                           body="Billing, payments and access requests live on the live TEMP-U site.")


# =============================================================== helpers
def _nowz():
    import datetime
    return datetime.datetime.utcnow().isoformat() + "Z"


def _progress_map(tids):
    if not tids:
        return {}
    rows = g.db.execute(
        "SELECT * FROM progress WHERE topic_id IN (%s)" % ",".join("?" * len(tids)), tids
    ).fetchall()
    return {r["topic_id"]: dict(r) for r in rows}


def _grouped(tids, table):
    if not tids:
        return {}
    rows = g.db.execute(
        "SELECT * FROM %s WHERE topic_id IN (%s)" % (table, ",".join("?" * len(tids))), tids
    ).fetchall()
    out = {}
    for r in rows:
        out.setdefault(r["topic_id"], []).append(dict(r))
    return out


# Review rows outlive their card (a card you made and deleted, a library card
# removed by a content update). Counts only include cards that still exist.
_LIVE = "(r.card_id IN (SELECT id FROM cards) OR r.card_id IN (SELECT id FROM my_cards))"
_LIVE_DC = "(dc.card_id IN (SELECT id FROM cards) OR dc.card_id IN (SELECT id FROM my_cards))"


def _deck_stats(deck_id):
    n = g.db.execute("SELECT COUNT(*) n FROM deck_cards dc WHERE deck_id=? AND " + _LIVE_DC,
                     (deck_id,)).fetchone()["n"]
    due = g.db.execute(
        "SELECT COUNT(*) n FROM deck_cards dc JOIN card_reviews r ON r.card_id=dc.card_id "
        "WHERE dc.deck_id=? AND r.due_at<=? AND " + _LIVE, (deck_id, _nowz())).fetchone()["n"]
    new = g.db.execute(
        "SELECT COUNT(*) n FROM deck_cards dc LEFT JOIN card_reviews r ON r.card_id=dc.card_id "
        "WHERE dc.deck_id=? AND r.card_id IS NULL AND " + _LIVE_DC, (deck_id,)).fetchone()["n"]
    learn = g.db.execute(
        "SELECT COUNT(*) n FROM deck_cards dc JOIN card_reviews r ON r.card_id=dc.card_id "
        "WHERE dc.deck_id=? AND r.state='learning' AND " + _LIVE, (deck_id,)).fetchone()["n"]
    return {"cards": n, "due": due, "new": new, "learn": learn}


def _consistency_summary(full=False):
    rows = g.db.execute(
        "SELECT day, credit_seconds FROM study_log ORDER BY day").fetchall()
    import datetime
    goal_units = int(S.get_setting("dailyStudyGoalUnits", "8"))
    unit_sec = 15 * 60
    days = [{"day": r["day"], "units": round((r["credit_seconds"] or 0) / unit_sec, 1)}
            for r in rows]
    total_units = sum(d["units"] for d in days)
    active = len(days)
    at_goal = sum(1 for d in days if d["units"] >= goal_units)
    today = datetime.date.today().isoformat()
    today_units = next((d["units"] for d in days if d["day"] == today), 0)
    # streak: consecutive days up to today with >=1 unit
    dayset = {d["day"] for d in days if d["units"] >= 1}
    streak = 0
    cur = datetime.date.today()
    while cur.isoformat() in dayset:
        streak += 1
        cur -= datetime.timedelta(days=1)
    # new layout: a streak up to yesterday is still alive today (today isn't over yet)
    live = 0
    cur = datetime.date.today()
    if cur.isoformat() not in dayset:
        cur -= datetime.timedelta(days=1)
    while cur.isoformat() in dayset:
        live += 1
        cur -= datetime.timedelta(days=1)
    last_day = max(dayset) if dayset else None
    days_since = (datetime.date.today() - datetime.date.fromisoformat(last_day)).days if last_day else None
    longest = _longest_streak(sorted(dayset))
    total_minutes = int(round(total_units * 15))
    out = {"goal_units": goal_units, "total_units": round(total_units, 1),
           "active_days": active, "days_at_goal": at_goal, "today_units": today_units,
           "current_streak": streak, "longest_streak": longest,
           "live_streak": live, "studied_today": datetime.date.today().isoformat() in dayset,
           "days_since": days_since,
           "total_hours": total_minutes // 60, "total_mins": total_minutes % 60,
           "avg_units": round(total_units / active, 1) if active else 0}
    if full:
        out["days"] = days
        out["heatmap"], out["months"] = _consistency_heatmap(days, goal_units)
        # current week strip (Mon..Sun)
        by_day = {d["day"]: d["units"] for d in days}
        monday = datetime.date.today() - datetime.timedelta(days=datetime.date.today().weekday())
        out["week"] = []
        for i in range(7):
            dt = monday + datetime.timedelta(days=i)
            u = by_day.get(dt.isoformat(), 0)
            out["week"].append({"label": "MTWTFSS"[i], "date": dt.isoformat(),
                                "units": u, "today": dt == datetime.date.today(),
                                "level": _heat_level(u, goal_units)})
    return out


def _heat_level(units, goal):
    if units <= 0:
        return 0
    if units < goal / 2:
        return 1
    if units < goal:
        return 2
    return 3


def _consistency_heatmap(days, goal, weeks=18):
    """GitHub-style grid: list of week-columns, each 7 day cells (Mon..Sun)."""
    import datetime
    by_day = {d["day"]: d["units"] for d in days}
    today = datetime.date.today()
    # start on the Monday `weeks` weeks back
    start = today - datetime.timedelta(days=today.weekday() + 7 * (weeks - 1))
    grid, month_row, last_month = [], [], None
    cur = start
    for w in range(weeks):
        col = []
        for d in range(7):
            dt = cur + datetime.timedelta(days=d)
            u = by_day.get(dt.isoformat(), 0)
            col.append({"date": dt.isoformat(), "units": u,
                        "level": _heat_level(u, goal) if dt <= today else -1})
        # month label aligned to the column where a new month starts
        mlabel = col[0]["date"][:7]
        if mlabel != last_month:
            month_row.append(datetime.date.fromisoformat(col[0]["date"]).strftime("%b"))
            last_month = mlabel
        else:
            month_row.append("")
        grid.append(col)
        cur += datetime.timedelta(days=7)
    return grid, month_row


def _longest_streak(sorted_days):
    import datetime
    best = run = 0
    prev = None
    for d in sorted_days:
        cur = datetime.date.fromisoformat(d)
        if prev and (cur - prev).days == 1:
            run += 1
        else:
            run = 1
        best = max(best, run)
        prev = cur
    return best
