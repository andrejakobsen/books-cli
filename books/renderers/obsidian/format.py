"""YAML scalar, wikilink, and HTML→Markdown formatting helpers."""

from __future__ import annotations

from html.parser import HTMLParser


def yaml_quote(value: str) -> str:
    """Double-quote a scalar, escaping backslashes and quotes."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def format_rating(value: float | int | None) -> str:
    """Render a 0-5 rating as star emoji (``3`` -> ``⭐⭐⭐``).

    Fractional ratings (e.g. Calibre's 3.5) round to the nearest whole star.
    A present rating is always at least one star, so an explicit ``0`` (or a
    rating that rounds down to 0) renders as ``⭐``. Only a missing rating
    (``None``) renders as the empty string.
    """
    if value is None:
        return ""
    return "⭐" * max(1, round(value))


def wikilink(name: str) -> str:
    """Wrap *name* in an Obsidian [[wikilink]], sanitizing illegal chars."""
    clean = name.replace("[", "(").replace("]", ")").replace("|", "-")
    clean = clean.replace("#", "").replace("^", "")
    return f"[[{clean}]]"


def link_list(names: list[str]) -> str:
    """Render a YAML flow list of quoted wikilinks."""
    return "[" + ", ".join(yaml_quote(wikilink(n)) for n in names) + "]"


def plain_list(values: list[str]) -> str:
    """Render a YAML flow list of quoted plain scalars."""
    return "[" + ", ".join(yaml_quote(v) for v in values) + "]"


# --- HTML -> Markdown -------------------------------------------------------

class _HTMLToMarkdown(HTMLParser):
    """Minimal HTML->Markdown for book descriptions and reviews.

    Handles the simple tags these sources emit: div, p, br, i/em, b/strong,
    ul/ol, li, a.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._list_stack: list[str] = []
        self._href: str | None = None
        self._link_text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in ("p", "div"):
            self._newline_block()
        elif tag == "br":
            self.parts.append("\n")
        elif tag in ("i", "em"):
            self.parts.append("*")
        elif tag in ("b", "strong"):
            self.parts.append("**")
        elif tag in ("ul", "ol"):
            self._newline_block()
            self._list_stack.append(tag)
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag == "a":
            self._href = dict(attrs).get("href")
            self._link_text = []

    def handle_endtag(self, tag):
        if tag in ("p", "div"):
            self._newline_block()
        elif tag in ("i", "em"):
            self.parts.append("*")
        elif tag in ("b", "strong"):
            self.parts.append("**")
        elif tag in ("ul", "ol"):
            if self._list_stack:
                self._list_stack.pop()
            self._newline_block()
        elif tag == "a":
            text = "".join(self._link_text).strip()
            if self._href and text:
                self.parts.append(f"[{text}]({self._href})")
            elif text:
                self.parts.append(text)
            self._href = None
            self._link_text = []

    def handle_data(self, data):
        if self._href is not None:
            self._link_text.append(data)
        else:
            self.parts.append(data)

    def _newline_block(self):
        if self.parts and not self.parts[-1].endswith("\n\n"):
            self.parts.append("\n\n")

    def result(self) -> str:
        text = "".join(self.parts)
        lines = [ln.rstrip() for ln in text.split("\n")]
        out: list[str] = []
        blank = 0
        for ln in lines:
            if ln == "":
                blank += 1
                if blank <= 1:
                    out.append("")
            else:
                blank = 0
                out.append(ln)
        return "\n".join(out).strip()


def html_to_markdown(html: str) -> str:
    if not html:
        return ""
    parser = _HTMLToMarkdown()
    parser.feed(html)
    return parser.result()
