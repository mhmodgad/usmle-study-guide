#!/usr/bin/env python3
"""Render a TEMP-U official flashcard the way the live review page does.

Mirrors the review page's own code (route chunk `app/(user)/flashcards/library/review`,
build f77be7da…, captured 2026-11-24):

  * module 44362 `FlashcardStudyFace`   — the `.card-surface` block: beta badge, wrapper div
    (label + front live region + the lower Extra/Answer block INSIDE the wrapper), the
    front `aria-live` only for cloze cards, back class `text-tag-pink…` when the card has
    no cloze ordinal.
  * module 74969 `FlashcardCardRenderer` — Lexical editor per side, theme module 93165,
    cloze view transform (ordinal/face -> hidden/revealed/plain).
  * Lexical core (chunk b84b5b8e…, v0.46.0) — TextNode.createDOM outer-tag chain
    code(16) > mark(128) > sub(32) > sup(64) with the bold/italic classes on the inner
    element; ListItemNode always sets the `value` attribute; `dir="auto"` only on direct
    children of the root; empty blocks and blocks ending in a linebreak get a managed
    `<br data-lexical-managed-linebreak="true">`.
  * Browser HTML serialisation — text nodes escape `& < >` and nbsp (apostrophes and
    quotes stay raw); attributes additionally escape `"`.

    face(card, revealed, media=None)   -> the `.card-surface` block for one card
    side(document, view, media=None)   -> inner HTML of one editor root
    visible_text(document)             -> plain text (search / previews)
    constructs(card)                   -> set of construct tags the card exercises

Cloze view (what FlashcardCardRenderer does to the FRONT document before rendering):
    ordinal == card.ordinal and face "front"  -> hidden   (shows the hint, else "…")
    ordinal == card.ordinal and face "back"   -> revealed
    every other cloze                        -> plain    (answer shown as ordinary text)

`media(objectKey)` maps a card image's objectKey to the URL the <img> should use
(replica-local path); None keeps the public media URL the live app uses.

Run with -I.
"""
import re
import urllib.parse

MEDIA_PREFIX = "https://media.tempusmle.com/"

EDITOR_ROOT_STYLE = "user-select: text; white-space: pre-wrap; word-break: break-word;"
PARAGRAPH_CLASS = "custom_paragraph__XRwl1"
CLOZE_CLASS = {"edit": "custom_clozeEdit__CUgS4", "hidden": "custom_clozeHidden__JVOWT",
               "revealed": "custom_clozeRevealed__rVvLt", "plain": "custom_clozePlain__FMnl_"}
# theme.text (module 74969): bold / italic / underline only — in TextNode class-add order
TEXT_CLASS = ((1, "font-semibold"), (2, "italic"), (8, "underline underline-offset-2"))
LIST_CLASS = {"ul": "my-2 ml-5 space-y-1 custom_unorderedList__ZQqpF",
              "ol": "my-2 ml-5 list-decimal space-y-1"}
HIDDEN_PLACEHOLDER = "…"
MANAGED_BR = '<br data-lexical-managed-linebreak="true">'

FACE_CLASS = ("relative flex min-h-72 flex-col justify-center rounded-3xl bg-card/95 p-8 "
              "text-card-foreground md:min-h-80 md:p-12 card-surface")
LABEL_CLASS = "mb-3 text-center text-xs font-medium uppercase tracking-widest text-muted-foreground"
MAIN_CLASS = "font-study text-center text-xl font-semibold leading-relaxed text-status-info md:text-2xl"
EXTRA_CLASS = "font-study text-center text-base leading-relaxed text-muted-foreground md:text-lg"
# back side of a card without a cloze ordinal (module 44362: m ? … : "…text-tag-pink md:text-xl")
BACK_PLAIN_CLASS = "font-study text-center text-lg font-semibold leading-relaxed text-tag-pink md:text-xl"
LOWER_CLASS = "mt-8 border-t border-border/80 pt-8"
ALERT_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" '
             'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
             'class="lucide lucide-circle-alert" data-icon="inline-end" aria-hidden="true">'
             '<circle cx="12" cy="12" r="10"></circle><line x1="12" x2="12" y1="8" y2="12"></line>'
             '<line x1="12" x2="12.01" y1="16" y2="16"></line></svg>')
BETA_BADGE = (
    '<span class="inline-flex absolute top-4 right-4 md:top-5 md:right-5">'
    '<button type="button" tabindex="0" data-base-ui-click-trigger="" aria-haspopup="dialog" '
    'aria-expanded="false" data-slot="popover-trigger" aria-label="Beta: about these cards" '
    'class="group/badge inline-flex h-5 w-fit shrink-0 items-center justify-center overflow-hidden rounded-4xl '
    'border px-2 py-0.5 text-xs font-medium whitespace-nowrap transition-all focus-visible:border-ring '
    'focus-visible:ring-[3px] has-data-[icon=inline-start]:pl-1.5 aria-invalid:border-destructive '
    'aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 [&amp;&gt;svg]:pointer-events-none '
    '[&amp;&gt;svg]:size-3! bg-status-info/10 text-status-info-strong border-status-info/20 '
    'focus-visible:ring-status-info/20 dark:bg-status-info/20 dark:focus-visible:ring-status-info/40 '
    '[a]:hover:bg-status-info/20 relative cursor-pointer gap-1 after:absolute after:-inset-3 '
    'has-data-[icon=inline-end]:pr-1.5">Beta' + ALERT_SVG + '</button></span>')

_TAG = re.compile(r"<[^>]+>")


# ------------------------------------------------------- browser serialisation
def esc_text(s):
    """HTML-serialise a TEXT node the way browsers do: & < > and nbsp, quotes raw."""
    return (str(s if s is not None else "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace("\xa0", "&nbsp;"))


def esc_attr(s):
    """Serialise an ATTRIBUTE value: text rules plus `"` (apostrophes stay raw)."""
    return esc_text(s).replace('"', "&quot;")


def media_url(object_key):
    """objectKey -> public media URL (module 13470: each path segment encodeURIComponent)."""
    if not object_key:
        return None
    return MEDIA_PREFIX + "/".join(urllib.parse.quote(seg, safe="-_.!~*'()") for seg in object_key.split("/"))


# ------------------------------------------------------------------ cloze view
def cloze_view(node, view):
    if not isinstance(node, dict):
        return node
    if node.get("type") == "cloze":
        if view and node.get("ordinal") == view["ordinal"]:
            if view["face"] == "front":
                hint = node.get("hint") if isinstance(node.get("hint"), str) else ""
                return {**node, "display": "hidden", "children": [{
                    "type": "text", "version": 1, "text": hint or HIDDEN_PLACEHOLDER,
                    "format": 0, "detail": 0, "mode": "normal", "style": ""}]}
            return {**node, "display": "revealed"}
        return {**node, "display": "plain"}
    if isinstance(node.get("children"), list):
        return {**node, "children": [cloze_view(c, view) for c in node["children"]]}
    return node


# ------------------------------------------------------------------ Lexical DOM
def text_dom(node):
    """Lexical TextNode.createDOM (v0.46.0).

    outer tag chain nY(): code(16) > mark(128) > sub(32) > sup(64), each carrying
    data-lexical-text (+ spellcheck=false for code) and wrapping an inner element that
    carries the theme classes; otherwise one element with both.
    """
    try:
        fmt = int(node.get("format") or 0)
    except (TypeError, ValueError):
        fmt = 0
    text = esc_text(node.get("text"))
    style = node.get("style") or ""
    classes = " ".join(c for bit, c in TEXT_CLASS if fmt & bit)
    cls = f' class="{classes}"' if classes else ""
    style_attr = f' style="{esc_attr(style)}"' if style else ""
    outer = ("code" if fmt & 16 else "mark" if fmt & 128 else
             "sub" if fmt & 32 else "sup" if fmt & 64 else None)
    inner = "strong" if fmt & 1 else "em" if fmt & 2 else "span"
    if outer:
        spell = ' spellcheck="false"' if fmt & 16 else ""
        return (f'<{outer}{spell}{style_attr} data-lexical-text="true">'
                f'<{inner}{cls}>{text}</{inner}></{outer}>')
    return f'<{inner}{cls}{style_attr} data-lexical-text="true">{text}</{inner}>'


def cloze_dom(node):
    """ClozeNode.applyDOMAttributes: className first, then the data-*/aria attributes."""
    display = node.get("display") or "edit"
    attrs = f' data-cloze-ordinal="{esc_attr(node.get("ordinal"))}"'
    hint = node.get("hint")
    if display == "hidden":
        attrs += (' aria-label="Hidden answer, hint: ' + esc_attr(hint) + '"' if hint
                  else ' aria-label="Hidden answer"')
    elif display == "edit" and hint:
        attrs += f' data-cloze-hint="{esc_attr(hint)}" title="Hint: {esc_attr(hint)}"'
    inner = "".join(text_dom(c) for c in (node.get("children") or []) if isinstance(c, dict))
    return f'<span class="{CLOZE_CLASS.get(display, "")}"{attrs}>{inner}</span>'


def inline_dom(node):
    t = node.get("type")
    if t == "text":
        return text_dom(node)
    if t == "linebreak":
        return "<br>"
    if t == "tab":  # TabNode: plain TextNode DOM with a literal tab
        return '<span data-lexical-text="true">\t</span>'
    if t == "cloze":
        return cloze_dom(node)
    return "".join(inline_dom(c) for c in (node.get("children") or []) if isinstance(c, dict))


def image_dom(node, media):
    """content-image decorator (module 47570): figure > div > next/image <img unoptimized>."""
    key = node.get("objectKey")
    src = media(key) if (media and key) else None
    src = src or media_url(key)
    if not src:
        return ""
    label = node.get("label") if node.get("label") is not None else "Card image"
    w = int(node["width"]) if isinstance(node.get("width"), (int, float)) and node.get("width") > 0 else 0
    h = int(node["height"]) if isinstance(node.get("height"), (int, float)) and node.get("height") > 0 else 0
    if not (w and h):
        return ""
    return ('<div data-lexical-decorator="true" contenteditable="false">'
            '<figure class="group relative my-3 overflow-hidden rounded-lg border border-border/60 bg-muted/20">'
            '<div class="relative flex min-h-36 items-center justify-center p-2">'
            f'<img alt="{esc_attr(label)}" loading="lazy" width="{w}" height="{h}" decoding="async" data-nimg="1" '
            f'class="max-h-128 w-auto max-w-full rounded-md object-contain" src="{esc_attr(src)}" '
            'style="color: transparent;"></div></figure></div>')


def _kids(node):
    return [c for c in (node.get("children") or []) if isinstance(c, dict)]


def _managed_br(node):
    """ElementNode line-break management (Lexical e5): empty block, or block whose last
    child is a linebreak, gets a managed <br> appended."""
    kids = _kids(node)
    if not kids:
        return MANAGED_BR
    if kids[-1].get("type") == "linebreak":
        return MANAGED_BR
    return ""


def block_dom(node, media, top):
    """top=True only for direct children of the editor root (the dir="auto" rule, eG)."""
    t = node.get("type")
    kids = _kids(node)
    dir_attr = ' dir="auto"' if top else ""
    if t == "paragraph":
        body = "".join(inline_dom(c) for c in kids)
        return f'<p class="{PARAGRAPH_CLASS}"{dir_attr}>{body}{_managed_br(node)}</p>'
    if t == "list":
        tag = "ol" if node.get("listType") == "number" else "ul"
        start_attr = ""
        if tag == "ol" and isinstance(node.get("start"), int) and node["start"] != 1:
            start_attr = f' start="{int(node["start"])}"'  # ListNode.createDOM: start before class
        return (f'<{tag}{start_attr} class="{LIST_CLASS[tag]}"{dir_attr}>'
                + "".join(block_dom(c, media, False) for c in kids) + f"</{tag}>")
    if t == "listitem":
        # ListItemNode.updateListItemDOM always sets li.value (reflected attribute)
        value = node.get("value")
        value_attr = f' value="{int(value) if isinstance(value, int) else 1}"'
        INLINE = ("text", "linebreak", "tab", "cloze")
        body = "".join(inline_dom(c) if c.get("type") in INLINE else block_dom(c, media, False)
                       for c in kids)
        return f'<li{value_attr} class="pl-1">{body}{_managed_br(node)}</li>'
    if t == "content-image":
        return image_dom(node, media)
    if t in (None, "root"):
        return "".join(block_dom(c, media, True) for c in kids)
    # element not in the card vocabulary: keep its text
    return "".join(block_dom(c, media, top) for c in kids)


def root_children(document):
    blocks = []
    for b in document or []:
        if isinstance(b, dict) and b.get("kind") == "tempu-flashcard-side":
            blocks.extend(((b.get("editorState") or {}).get("root") or {}).get("children") or [])
    return [c for c in blocks if isinstance(c, dict)]


def side(document, view=None, media=None):
    """Inner HTML of one editor root."""
    return "".join(block_dom(cloze_view(c, view), media, True) for c in root_children(document))


def visible_text(document):
    import html as H
    return H.unescape(_TAG.sub("", side(document).replace("<br>", "\n"))).replace("\xa0", " ").strip()


def editor_root(document, aria_label, class_, view=None, media=None):
    # attribute order is the live DOM's (React sets them in JSX order)
    return (f'<div aria-autocomplete="none" aria-label="{esc_attr(aria_label)}" aria-readonly="true" '
            f'class="max-w-none break-words outline-none {class_} custom_editorRoot__WwM7q" '
            f'contenteditable="false" role="textbox" spellcheck="true" data-lexical-editor="true" '
            f'style="{EDITOR_ROOT_STYLE}">{side(document, view, media)}</div>')


def face(card, revealed, media=None):
    """FlashcardStudyFace (module 44362): the `.card-surface` block.

    Everything lives in ONE wrapper div: the label, the front live region, and — on the
    revealed side of a card with a back document — the lower Extra/Answer block as a
    SIBLING of the front live region (source: both are children of the same jsxs div).
    The front region is aria-live only for cloze cards (m ? "polite" : void 0).
    """
    front, back = card.get("front_document"), card.get("back_document")
    m = card.get("kind") == "cloze" and card.get("ordinal") is not None
    main_label = "Answer" if (m and revealed) else "Front"
    lower_label = None if not (revealed and back) else ("Extra" if m else "Answer")
    view = {"ordinal": card.get("ordinal"), "face": "back" if revealed else "front"} if m else None
    out = [f'<div class="{FACE_CLASS}">']
    if card.get("is_beta"):
        out.append(BETA_BADGE)
    out.append('<div>')
    out.append(f'<div class="{LABEL_CLASS}" aria-hidden="true">'
               f'<span class="inline-block">{main_label}</span></div>')
    out.append('<div aria-live="polite">' if m else '<div>')
    out.append(editor_root(front, "Card answer" if (m and revealed) else "Card front", MAIN_CLASS, view, media))
    out.append('</div>')
    if lower_label:
        out.append(f'<div class="{LOWER_CLASS}">')
        out.append(f'<p class="{LABEL_CLASS}">{lower_label}</p>')
        out.append('<div aria-live="polite">')
        out.append(editor_root(back, "Card extra" if m else "Card back",
                               EXTRA_CLASS if m else BACK_PLAIN_CLASS, None, media))
        out.append('</div>')
        out.append('</div>')
    out.append('</div></div>')
    return "".join(out)


def ordinals(document):
    """Sorted distinct cloze ordinals of a card side (module 71498.Nk)."""
    found = set()

    def walk(n):
        if isinstance(n, dict):
            if n.get("type") == "cloze" and isinstance(n.get("ordinal"), int):
                found.add(n["ordinal"])
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for x in n:
                walk(x)

    walk(document)
    return sorted(found)


# ------------------------------------------------------------------ construct census
def constructs(card):
    """Every construct tag a card exercises — the checklist for live-DOM coverage."""
    tags = set()

    def walk(n, in_root):
        if not isinstance(n, dict):
            return
        t = n.get("type")
        if t == "text":
            try:
                fmt = int(n.get("format") or 0)
            except (TypeError, ValueError):
                fmt = 0
            for bit, name in ((1, "bold"), (2, "italic"), (8, "underline"), (16, "code"),
                              (32, "subscript"), (64, "superscript"), (128, "highlight"),
                              (4, "strikethrough")):
                if fmt & bit:
                    tags.add("text:" + name)
            if n.get("style"):
                tags.add("text:style-attr")
            for ch, name in (("&", "amp"), ("<", "lt"), (">", "gt"), ('"', "quote"),
                             ("'", "apostrophe"), ("\xa0", "nbsp"), ("\t", "tab-char")):
                if ch in (n.get("text") or ""):
                    tags.add("text:char-" + name)
        elif t in ("paragraph", "list", "listitem"):
            if t != "paragraph" or not in_root:
                tags.add(t + ":nested")
            if int(n.get("format") or 0):
                tags.add(t + ":align")
            if n.get("indent"):
                tags.add(t + ":indent")
            if t == "paragraph" and not n.get("children"):
                tags.add("paragraph:empty")
            if t == "list":
                lt = n.get("listType")
                tags.add("list:" + str(lt))
                if n.get("listType") == "number" and n.get("start") not in (None, 1):
                    tags.add("list:start")
            if t == "listitem" and n.get("value") is not None and n.get("value") != 1:
                tags.add("listitem:value")
        elif t == "cloze":
            tags.add("cloze:hint" if n.get("hint") else "cloze:no-hint")
            kids = n.get("children") or []
            if len(kids) != 1 or any((k.get("type") != "text") for k in kids if isinstance(k, dict)):
                tags.add("cloze:multi-text")
        elif t == "content-image":
            tags.add("content-image")
        elif t == "flashcard-image":
            tags.add("flashcard-image")
        elif t == "tab":
            tags.add("tab-node")
        elif t == "linebreak":
            pass
        for c in (n.get("children") or []):
            walk(c, False)

    for label, doc in (("front", card.get("front_document")), ("back", card.get("back_document"))):
        blocks = root_children(doc)
        for b in blocks:
            if b.get("type") not in ("paragraph",):
                tags.add("root:" + str(b.get("type")))
            walk(b, True)
        last = blocks[-1] if blocks else None
        if last is not None and last.get("type") in ("paragraph", "list", "listitem"):
            kids = last.get("children") or []
            if not kids or (kids and isinstance(kids[-1], dict) and kids[-1].get("type") == "linebreak"):
                tags.add("block:managed-br")
    if card.get("is_beta"):
        tags.add("beta")
    if card.get("back_document"):
        tags.add("has-back")
    else:
        tags.add("no-back")
    if card.get("kind") != "cloze" or card.get("ordinal") is None:
        tags.add("no-ordinal-face")
    if len(ordinals(card.get("front_document"))) > 1:
        tags.add("multi-ordinal")
    return tags


def signature(card):
    """Back-compat alias for the construct census."""
    return frozenset(constructs(card))
