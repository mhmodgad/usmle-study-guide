#!/usr/bin/env python3
"""BlockNote document -> reader HTML renderer for the TEMP-U replica.

Emits the exact DOM structure the live app renders (verified against captured
reader DOM in gen/raw/pages/reader-heartsounds.html and
content/flight-section-mycobacteria-dom-expanded.html):

  bn-block-outer / bn-block / bn-block-content wrappers
  block types: paragraph, heading (incl. toggleable), bulletListItem,
  numberedListItem, toggleListItem, quote, real-quote, image, video, youtube,
  table (headerRows/headerCols -> th/td, legacy list-cells), divider,
  columnList/column
  inline: bold/italic/underline, textColor/backgroundColor style spans,
  calloutIcon marks, inline math (^sup), <br> for newlines

Run with `python3 -I` (consumes captured downloads).
"""
import html as H
import os

ANALYSIS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
MEDIA_DIR = os.path.join(ANALYSIS, "content", "media", "topics")

VID_EXT = (".mp4", ".webm", ".mov", ".m4v")

# Bump when the HTML this module emits changes; the app re-renders stored
# topic documents automatically when the stored version is older.
RENDER_VERSION = 2

import re as _re_mod
_XREF_RE = _re_mod.compile(r"^/r/(t|b)/([0-9a-f-]{36})(?:/([0-9a-f-]{36}))?")


def link_open(href):
    """Opening <a> for a BlockNote link run.

    In-app cross references (/r/t/<topicId>, /r/b/<topicId>/<blockId>) become
    data-attributed links the reader resolves locally and opens in a split
    view; anything else is a normal external link.
    """
    href = href or ""
    m = _XREF_RE.match(href)
    if m:
        kind, tid, bid = m.group(1), m.group(2), m.group(3) or ""
        return (f'<a class="tempu-xref" href="/r/{kind}/{tid}{"/" + bid if bid else ""}" '
                f'data-ref-topic="{tid}" data-ref-block="{bid}">')
    return (f'<a class="tempu-extlink" href="{H.escape(href, quote=True)}" '
            'target="_blank" rel="noopener noreferrer">')

IMAGE_ICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
    'class="lucide lucide-image custom_readerImageIcon__2ILdD" aria-hidden="true">'
    '<rect width="18" height="18" x="3" y="3" rx="2" ry="2"></rect>'
    '<circle cx="9" cy="9" r="2"></circle>'
    '<path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"></path></svg>'
)
TOGGLE_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" height="24px" viewBox="0 -960 960 960" width="24px" '
    'fill="CURRENTCOLOR"><path d="M320-200v-560l440 280-440 280Z"></path></svg>'
)


def esc(s):
    if s is None:
        return ""
    return H.escape(str(s), quote=False).replace("\xa0", "&nbsp;")


def media_src(url):
    """Image/video URL -> replica-local URL when the file is staged on disk.

    Images and videos are embedded locally (assets/media/<topicId>/<file>) when
    the file has been placed by tools/place_media.py; otherwise the CDN URL is kept.
    """
    if not url or not isinstance(url, str):
        return url
    if "media.tempusmle.com" not in url or "/topics/" not in url:
        return url
    parts = url.split("/topics/", 1)[-1].split("?")[0].split("/")
    if len(parts) != 2:
        return url
    tid, fname = parts
    staged = os.path.join(MEDIA_DIR, tid, fname)
    placed = os.path.join(os.path.dirname(MEDIA_DIR), "..", "..", "tempu-replica",
                          "assets", "media", tid, fname)
    if os.path.exists(staged) or os.path.exists(placed):
        return f"assets/media/{tid}/{fname}"
    return url


def yt_embed(url):
    """watch URL -> youtube-nocookie embed URL (rel=0, start from t=)."""
    import re as _re
    from urllib.parse import urlparse, parse_qs
    try:
        q = parse_qs(urlparse(url).query)
        vid = (q.get("v") or [None])[0]
        if not vid:
            m = _re.search(r"youtu\.be/([^?&#]+)", url)
            vid = m.group(1) if m else None
        start = 0
        t = (q.get("t") or ["0"])[0]
        m = _re.match(r"(\d+)(s)?$", t)
        if m:
            start = int(m.group(1))
        if not vid:
            return None
        suffix = f"&start={start}" if start else ""
        return f"https://www.youtube-nocookie.com/embed/{vid}?rel=0{suffix}", start
    except Exception:
        return None


# ---------------------------------------------------------------- inline
def callout_icon_span(icon):
    return (
        '<span class="react-renderer mark-calloutIcon">'
        f'<span class="callout-icon-marker" data-icon="{esc(icon)}" '
        'style="display: inline-block; width: 0px; height: 0px;">'
        f'<span class="callout-icon-image" style="width: 20px; height: 20px; position: absolute; '
        f'left: 13px; top: 21.75px; user-select: none; '
        f'background-image: url(&quot;/editor/quoteIcons/{esc(icon)}.webp?v=1&quot;); '
        'background-size: contain; background-repeat: no-repeat; background-position: center center;">'
        '</span><span data-mark-view-content=""><span>\u200b</span></span></span></span>'
    )


def math_html(equation):
    """Trivial superscript equations (^3, ^c, ^sc) -> captured katex DOM."""
    eq = (equation or "").strip()
    body = eq[1:] if eq.startswith("^") else eq
    mord = "mn" if body.isdigit() else "mi"
    return (
        '<span class="react-renderer node-math bn-ic-react-node-view-renderer" contenteditable="false">'
        '<span as="span" class="bn-inline-content-section" data-inline-content-type="math" '
        f'data-equation="{esc(eq)}" data-node-view-wrapper="" style="white-space: normal;">'
        '<span class="custom_inlineMathShell__7SM8J" contenteditable="false">'
        '<span class="custom_inlineMathEquation__sgAM5"><span class="katex">'
        '<span class="katex-mathml"><math xmlns="http://www.w3.org/1998/Math/MathML"><semantics>'
        f'<msup><mrow></mrow><{mord}>{esc(body)}</{mord}></msup></mrow>'
        f'<annotation encoding="application/x-tex">{esc(eq)}</annotation></semantics></math></span>'
        '<span class="katex-html" aria-hidden="true"><span class="base">'
        '<span class="strut" style="height:0.8141em;"></span><span class="mord"><span></span>'
        '<span class="msupsub"><span class="vlist-t"><span class="vlist-r">'
        '<span class="vlist" style="height:0.8141em;">'
        '<span style="top:-3.063em;margin-right:0.05em;">'
        '<span class="pstrut" style="height:2.7em;"></span>'
        f'<span class="sizing reset-size6 size3 mtight"><span class="mord mtight">{esc(body)}</span>'
        "</span></span></span></span></span></span></span></span></span></span></span></span></span>"
    )


_MARK_ORDER = ("bold", "italic", "underline")


def _mark_pair(kind, value=None):
    """(open, close) wrapper pair for one style mark."""
    if kind == "bold":
        return ("<strong>", "</strong>")
    if kind == "italic":
        return ("<em>", "</em>")
    if kind == "underline":
        return ("<u>", "</u>")
    if kind == "textColor":
        return (f'<span data-style-type="textColor" data-value="{esc(value)}" data-editable="">', "</span>")
    if kind == "backgroundColor":
        return (f'<span data-style-type="backgroundColor" data-value="{esc(value)}" data-editable="">', "</span>")
    raise ValueError(kind)


def _run_marks(styles):
    """Canonical-order mark list for a run's styles (PM nesting convention)."""
    marks = []
    for kind in _MARK_ORDER:
        if styles.get(kind):
            marks.append(_mark_pair(kind))
    tc = styles.get("textColor")
    if tc and tc != "default":
        marks.append(_mark_pair("textColor", tc))
    bg = styles.get("backgroundColor")
    if bg and bg != "default":
        marks.append(_mark_pair("backgroundColor", bg))
    return marks


def inline_html(content):
    """Render BlockNote inline content (list of text/math runs) to HTML.

    Uses the ProseMirror mark-stack convention verified against captured DOM:
    runs sharing style prefixes keep wrappers open; '\\n' inside text is a bare
    mark-less <br> node that closes/reopens the stack (never <br> inside spans).
    """
    if not content:
        return '<br class="ProseMirror-trailingBreak">'
    out = []
    stack = []
    last_br = False  # consecutive bare breaks get a ProseMirror-separator between them

    def push(node_html, styles):
        nonlocal stack, last_br
        tgt = _run_marks(styles or {})
        k = 0
        while k < min(len(stack), len(tgt)) and stack[k] == tgt[k]:
            k += 1
        for o in reversed(stack[k:]):
            out.append(o[1])
        for o in tgt[k:]:
            out.append(o[0])
        stack = tgt
        if node_html == "<br>" and last_br:
            out.append('<img class="ProseMirror-separator" alt="">')
        last_br = node_html == "<br>"
        out.append(node_html)

    for run in content:
        if not isinstance(run, dict):
            if isinstance(run, str):
                push(esc(run), {})
            continue
        rtype = run.get("type") or "text"
        styles = run.get("styles") or {}
        if rtype == "link":
            # close any open marks, emit the link with its own inner runs
            for o in reversed(stack):
                out.append(o[1])
            stack = []
            inner = inline_html(run.get("content") or [])
            if inner == '<br class="ProseMirror-trailingBreak">':
                inner = esc(run.get("href") or "")
            out.append(link_open(run.get("href")) + inner + "</a>")
            last_br = False
            continue
        if rtype == "math":
            push(math_html((run.get("props") or {}).get("equation")), styles)
            continue
        text = run.get("text") or ""
        icon = styles.get("calloutIcon")
        if text == "\u200b" and not icon:
            continue  # zero-width style carrier, visually empty in captured DOM
        if icon:
            push(callout_icon_span(icon), styles)
            if text and text != "\u200b":
                push(esc(text), styles)
            continue
        parts = text.split("\n")
        for i, part in enumerate(parts):
            if i:
                push("<br>", {})
            if part:
                push(esc(part), styles)
    for o in reversed(stack):
        out.append(o[1])
    if not out:
        return '<br class="ProseMirror-trailingBreak">'
    if last_br:
        # a hard break at the end of a block is followed by a trailing break
        out.append('<br class="ProseMirror-trailingBreak">')
    return "".join(out)


def block_attrs(props):
    a = []
    bg = (props or {}).get("backgroundColor")
    if bg and bg != "default":
        a.append(f' data-background-color="{esc(bg)}"')
    tc = (props or {}).get("textColor")
    if tc and tc != "default":
        a.append(f' data-text-color="{esc(tc)}"')
    ta = (props or {}).get("textAlignment")
    if ta and ta != "left":
        a.append(f' data-text-alignment="{esc(ta)}"')
    lvl = (props or {}).get("level")
    if lvl:
        a.append(f' data-level="{esc(lvl)}"')
    if (props or {}).get("isToggleable"):
        a.append(' data-is-toggleable="true"')
    return "".join(a)


def _is_run(item):
    """Legacy cell content: items can be bare inline runs, not wrapped in blocks."""
    if isinstance(item, str):
        return True
    if not isinstance(item, dict):
        return False
    return "text" in item or (item.get("type") in ("text", "math") and "content" not in item)


def cell_inner_html(cell):
    """Table cell -> paragraphs (no bn-inline-content class inside cells)."""
    content = cell.get("content")
    if isinstance(content, dict):  # legacy safety
        content = [content]
    items = [c for c in (content or []) if c is not None]
    if items and all(_is_run(c) for c in items):
        return f"<p>{inline_html(items)}</p>"
    out = []
    for blk in items:
        if not isinstance(blk, dict):
            s = blk if isinstance(blk, str) else ""
            out.append(f"<p>{esc(s)}</p>" if s else "")
            continue
        if blk.get("type") == "math":
            out.append(math_html((blk.get("props") or {}).get("equation")))
            continue
        out.append(f"<p>{inline_html(blk.get('content'))}</p>")
    return "".join(out) or '<p><br class="ProseMirror-trailingBreak"></p>'


def youtube_html(b):
    props = b.get("props") or {}
    url = props.get("url") or ""
    pw = props.get("previewWidth")
    ta = props.get("textAlignment") or "left"
    cap = props.get("caption")
    emb = yt_embed(url)
    cls = {"left": "custom_youtubeAlignLeft__56_v1",
           "center": "custom_youtubeAlignCenter__v0u5n",
           "right": "custom_youtubeAlignRight__NqkIn"}.get(ta, "custom_youtubeAlignLeft__56_v1")
    style = f' style="width: {int(pw)}px;"' if pw else ""
    data_pw = f' data-preview-width="{esc(pw)}"' if pw else ""
    data_ta = f' data-text-alignment="{esc(ta)}"' if ta and ta != "left" else ""
    if emb:
        iframe = (f'<iframe src="{esc(emb[0])}" title="YouTube video" allow="accelerometer; '
                  'clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" '
                  'allowfullscreen="" loading="lazy" referrerpolicy="strict-origin-when-cross-origin">'
                  "</iframe>")
    else:
        iframe = ""
    caption = f'<figcaption class="custom_youtubeCaption__uMpzf">{esc(cap)}</figcaption>' if cap else ""
    return (
        '<div class="react-renderer node-youtube bn-react-node-view-renderer" contenteditable="false">'
        f'<div class="bn-block-content" data-content-type="youtube" data-url="{esc(url)}"{data_pw}{data_ta} '
        'data-node-view-wrapper="" style="white-space: normal;">'
        f'<div class="custom_youtubeShell__7j8WS {cls}" contenteditable="false"{style}>'
        f'<div class="custom_youtubeFrame__0Ra0d">{iframe}</div>{caption}</div></div></div>'
    )


def image_html(b):
    props = b.get("props") or {}
    url = props.get("url") or ""
    pw = props.get("previewWidth")
    ta = props.get("textAlignment")
    cap = props.get("caption")
    src = media_src(url)
    width = f' width="{esc(pw)}"' if pw else ""
    var_style = f' style="--reader-image-width: {esc(pw)}px;"' if pw else ""
    data_ta = f' data-text-alignment="{esc(ta)}"' if ta and ta != "left" else ""
    data_pw = f' data-preview-width="{esc(pw)}"' if pw else ""
    data_cap = f' data-caption="{esc(cap)}"' if cap else ""
    media = (
        f'<img class="bn-visual-media custom_readerImage__IUONH" alt=""{width} loading="lazy" '
        f'decoding="async" contenteditable="false" draggable="false" src="{esc(src)}">'
        f'<div class="custom_readerImageStatus__C0xox" data-image-status="loaded">{IMAGE_ICON_SVG}</div>'
    )
    frame = '<div class="bn-visual-media-wrapper custom_readerImageFrame__fggjz custom_readerImageFrameLoaded__NfvPJ" data-image-state="loaded">' + media + "</div>"
    if cap:
        inner = (
            f'<figure class="bn-file-block-content-wrapper custom_readerImageBlock__gqKMu"{var_style}>'
            f'{frame}<figcaption class="bn-file-caption">{esc(cap)}</figcaption></figure>'
        )
    else:
        inner = (f'<div class="bn-file-block-content-wrapper custom_readerImageBlock__gqKMu"{var_style}>'
                 f"{frame}</div>")
    return (
        '<div class="react-renderer node-image bn-react-node-view-renderer" contenteditable="false">'
        f'<div class="bn-block-content" data-content-type="image"{data_ta} data-url="{esc(url)}"{data_cap}{data_pw} '
        'data-file-block="true" data-node-view-wrapper="" style="white-space: normal;">'
        f"{inner}</div></div>"
    )


def video_html(b):
    props = b.get("props") or {}
    url = props.get("url") or ""
    src = media_src(url)
    return (
        f'<div class="bn-block-content" data-content-type="video" data-url="{esc(url)}" '
        'data-file-block="" contenteditable="false">'
        '<div class="bn-file-block-content-wrapper" style="position: relative; width: fit-content;">'
        '<div class="bn-visual-media-wrapper">'
        f'<video class="bn-visual-media" src="{esc(src)}" controls="" contenteditable="false" '
        'draggable="false"></video>'
        '<div class="bn-resize-handle" style="left: 4px; display: none;"></div>'
        '<div class="bn-resize-handle" style="right: 4px; display: none;"></div>'
        "</div></div></div>"
    )


def table_html(b):
    content = b.get("content") or {}
    rows = content.get("rows") or []
    n_rows = len(rows)
    n_cols = max([len(r.get("cells") or []) for r in rows if isinstance(r, dict)] or [1])
    hr = content.get("headerRows") or 0
    hc = content.get("headerCols") or 0
    cols = "".join("<col>" for _ in range(n_cols))
    trs = []
    for ri, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        tds = []
        for ci, cell in enumerate(row.get("cells") or []):
            is_header = ri < hr or ci < hc
            if isinstance(cell, dict):
                props = cell.get("props") or {}
                colspan = props.get("colspan", 1)
                rowspan = props.get("rowspan", 1)
                bg = props.get("backgroundColor")
                ta = props.get("textAlignment")
                inner = cell_inner_html(cell)
            else:
                colspan = rowspan = 1
                bg = ta = None
                inner = cell_inner_html({"content": cell if isinstance(cell, list) else [cell]})
            tag = "th" if is_header else "td"
            attrs = ""
            if bg and bg != "default":
                attrs += f' data-background-color="{esc(bg)}"'
            if ta and ta != "left":
                attrs += f' data-text-alignment="{esc(ta)}"'
            attrs += f' colspan="{esc(colspan)}" rowspan="{esc(rowspan)}"'
            tds.append(f"<{tag}{attrs}>{inner}</{tag}>")
        trs.append(f"<tr>{''.join(tds)}</tr>")
    return (
        '<div class="bn-block-content" data-content-type="table">'
        '<div class="tableWrapper"><div class="tableWrapper-inner">'
        f'<table style="--default-cell-min-width: 120px; min-width: {120 * n_cols}px;">'
        f"<colgroup>{cols}</colgroup><tbody>{''.join(trs)}</tbody></table></div>"
        '<div class="table-widgets-container" style="position: relative;"></div></div></div>'
    )


def content_div(b, inner, extra_attrs="", contenteditable=False):
    ce = ' contenteditable="false"' if contenteditable else ""
    return (f'<div class="bn-block-content" data-content-type="{b.get("type")}"'
            f'{block_attrs(b.get("props"))}{extra_attrs}{ce}>{inner}</div>')


def toggle_inner(b, inline, tag="p"):
    return (
        f"<div><div class=\"bn-toggle-wrapper\" data-show-children=\"true\">"
        f'<button class="bn-toggle-button" type="button">{TOGGLE_SVG}</button>'
        f"<{tag} class=\"bn-inline-content\">{inline}</{tag}></div></div>"
    )


def block_content_html(b, num_index):
    """Inner of bn-block / bn-block-content for a block (no children)."""
    t = b.get("type")
    props = b.get("props") or {}
    inline = inline_html(b.get("content"))
    if t == "paragraph":
        return content_div(b, f'<p class="bn-inline-content">{inline}</p>')
    if t == "heading":
        lvl = props.get("level") or 3
        if props.get("isToggleable"):
            return content_div(b, toggle_inner(b, inline, f"h{min(lvl, 6)}"))
        return content_div(b, f'<h{min(lvl, 6)} class="bn-inline-content">{inline}</h{min(lvl, 6)}>')
    if t in ("bulletListItem",):
        return content_div(b, f'<p class="bn-inline-content">{inline}</p>')
    if t == "numberedListItem":
        return content_div(b, f'<p class="bn-inline-content">{inline}</p>',
                           extra_attrs=f' data-index="{num_index}"')
    if t == "toggleListItem":
        return content_div(b, toggle_inner(b, inline))
    if t == "quote":
        return content_div(b, f'<blockquote class="bn-inline-content">{inline}</blockquote>')
    if t == "real-quote":
        return (
            '<div class="react-renderer node-real-quote bn-react-node-view-renderer">'
            '<div class="bn-block-content" data-content-type="real-quote" data-node-view-wrapper="" '
            'style="white-space: normal;">'
            '<blockquote class="custom_realQuote__npWRJ">'
            '<div class="bn-inline-content inline-content custom_realQuoteContent__JT5WN" data-node-view-content="">'
            f'<div data-node-view-content-react="" data-node-view-wrapper="" style="white-space: inherit;">{inline}</div>'
            "</div></blockquote></div></div>"
        )
    if t == "image":
        return image_html(b)
    if t == "video":
        return video_html(b)
    if t == "youtube":
        return youtube_html(b)
    if t == "table":
        return table_html(b)
    if t == "divider":
        return content_div(b, "<hr>", contenteditable=True)
    # unknown block type: fall back to a paragraph so nothing is dropped
    return content_div(b, f'<p class="bn-inline-content">{inline}</p>')


def render_blocks(blocks):
    """Blocks (top-level or children) -> bn-block-outer sequence."""
    out = []
    num = 0
    prev_numbered = False
    for b in blocks or []:
        if not isinstance(b, dict):
            continue
        t = b.get("type")
        bid = b.get("id") or ""
        num_index = 0
        if t == "numberedListItem":
            start = (b.get("props") or {}).get("start")
            if start:
                num = start
            elif prev_numbered:
                num += 1
            else:
                num = 1
            num_index = num
            prev_numbered = True
        else:
            prev_numbered = False
        if t == "columnList":
            cols = []
            for col in b.get("children") or []:
                if not isinstance(col, dict) or col.get("type") != "column":
                    continue
                w = (col.get("props") or {}).get("width") or 1
                inner = render_blocks(col.get("children"))
                cols.append(
                    f'<div class="bn-block-column" data-node-type="column" data-id="{esc(col.get("id") or "")}" '
                    f'data-width="{esc(w)}" style="flex-grow: {esc(w)};">{inner}</div>'
                )
            # captured DOM: columnList sits directly in the block group (no block-outer wrapper)
            out.append(
                f'<div class="bn-block-column-list" data-node-type="columnList" data-id="{esc(bid)}" '
                f'style="display: flex;">{"".join(cols)}</div>'
            )
            prev_numbered = False
            continue
        content = block_content_html(b, num_index)
        children = b.get("children")
        kids = render_blocks(children) if isinstance(children, list) and children else ""
        group = f'<div class="bn-block-group" data-node-type="blockGroup">{kids}</div>' if kids else ""
        out.append(
            f'<div class="bn-block-outer" data-node-type="blockOuter" data-id="{esc(bid)}">'
            f'<div class="bn-block" data-node-type="blockContainer" data-id="{esc(bid)}">'
            f"{content}{group}</div></div>"
        )
        prev_numbered = t == "numberedListItem"
    return "".join(out)


def render_document(doc):
    if isinstance(doc, list):
        return render_blocks(doc)
    if isinstance(doc, dict):
        return render_blocks(doc.get("children") or [])
    return ""
