"""Minimal HTML sanitizer for content saved from the in-app editor.

The editor works on the reader's own markup (BlockNote-style divs/spans), so
this keeps every tag and attribute except things that could run code:
<script>/<style>/<object>/<embed>, on* event attributes, javascript: URLs,
and iframes that aren't YouTube embeds.
"""
import html as H
from html.parser import HTMLParser

DROP_WITH_CONTENT = {"script", "style", "object", "embed", "noscript", "template",
                     # SVG animation can set href="javascript:..." at run time
                     "animate", "set", "animatemotion", "animatetransform", "handler", "listener"}
# page-level tags that change how the WHOLE page behaves; dropped, content (if any) kept
DROP_TAG_ONLY = {"base", "meta", "link", "form", "frameset", "frame"}
VOID = {"area", "base", "br", "col", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
URL_ATTRS = {"href", "src", "data-url", "xlink:href", "action", "formaction", "poster"}
IFRAME_OK = ("https://www.youtube-nocookie.com/", "https://www.youtube.com/", "https://youtube.com/",
             "https://player.vimeo.com/")


SAFE_DATA = ("data:image/png", "data:image/jpeg", "data:image/jpg", "data:image/gif", "data:image/webp",
             "data:image/avif", "data:image/bmp")


def _safe_url(v):
    s = (v or "").strip().replace("\x00", "")
    low = "".join(s.split()).lower()
    if low.startswith(("javascript:", "vbscript:")):
        return None
    if low.startswith("data:") and not low.startswith(SAFE_DATA):
        return None              # only plain images may be inlined as data: URLs
    return s


class _San(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.skip = 0
        self.dropped = {}

    def handle_starttag(self, tag, attrs, closing=False):
        tag = tag.lower()
        if tag in DROP_WITH_CONTENT:
            if tag not in VOID and not closing:
                self.skip += 1
            return
        if self.skip or tag in DROP_TAG_ONLY:
            return
        keep = []
        for k, v in attrs:
            k = (k or "").lower()
            if not k or k.startswith("on") or k in ("srcdoc", "formaction"):
                continue
            if k in URL_ATTRS:
                v = _safe_url(v)
                if v is None:
                    continue
            if k == "style" and v and ("expression(" in v.lower() or "url(javascript" in v.lower()):
                continue
            keep.append((k, v))
        if tag == "iframe":
            src = dict(keep).get("src") or ""
            if not src.startswith(IFRAME_OK):
                if not closing:
                    self.dropped[tag] = self.dropped.get(tag, 0) + 1
                return
        a = "".join(f' {k}' if v is None else f' {k}="{H.escape(v, quote=True)}"' for k, v in keep)
        self.out.append(f"<{tag}{a}{' /' if closing and tag not in VOID else ''}>")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs, closing=True)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in DROP_WITH_CONTENT:
            if self.skip:
                self.skip -= 1
            return
        if self.skip or tag in VOID or tag in DROP_TAG_ONLY:
            return
        if self.dropped.get(tag):
            self.dropped[tag] -= 1
            return
        self.out.append(f"</{tag}>")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(H.escape(data, quote=False).replace("\xa0", "&nbsp;"))

    def handle_comment(self, data):
        pass


def clean_html(html):
    p = _San()
    p.feed(html or "")
    p.close()
    return "".join(p.out)


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in DROP_WITH_CONTENT:
            self.skip += 1
        elif tag in ("p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "br", "td", "th", "div"):
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in DROP_WITH_CONTENT and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def plain_text(html):
    p = _Text()
    p.feed(html or "")
    p.close()
    return " ".join("".join(p.parts).replace("​", "").split())
