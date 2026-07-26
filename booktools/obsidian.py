"""Shared helpers for writing Obsidian book-note vaults.

Both the Calibre and Goodreads importers write book notes with the same YAML
frontmatter schema and the same "never overwrite" rule, so their data (plus your
own manual edits) composes without clobbering. Everything they share lives here.

Standard library only.
"""

from __future__ import annotations

import re
import unicodedata
from html.parser import HTMLParser
from pathlib import Path


# --- Canonical property schema ---------------------------------------------

# Order in which book-note frontmatter keys are emitted. Every book note carries
# all of these (empty when unknown) so any field can be filled later by the other
# importer or by hand.
BOOK_PROPERTY_ORDER = (
    "type",
    "title",
    "authors",
    "genres",
    "series",
    "series_index",
    "publisher",
    "published",
    "language",
    "format",
    "pages",
    "status",
    "shelves",
    "rating",
    "isbn",
    "amazon",
    "google",
    "uuid",
    "calibre_id",
    "date_added",
    "date_read",
    "cover",
)


# --- YAML / link formatting -------------------------------------------------

def yaml_quote(value: str) -> str:
    """Double-quote a scalar, escaping backslashes and quotes."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


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


# --- Filesystem helpers -----------------------------------------------------

_ILLEGAL_FS = re.compile(r'[/\\:*?"<>|\x00-\x1f]')


def sanitize_folder_name(name: str) -> str:
    """Strip a trailing Calibre ' (NN)' id suffix from a book folder name."""
    return re.sub(r"\s*\(\d+\)$", "", name).strip()


def safe_filename(name: str) -> str:
    """Make *name* safe to use as a single path segment."""
    cleaned = _ILLEGAL_FS.sub("_", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = cleaned.rstrip(". ")
    return cleaned or "Untitled"


def write_if_absent(path: Path, content: str) -> bool:
    """Write only if the file does not exist yet. Returns True if written."""
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def write_stub(hub_dir: Path, name: str, note_type: str) -> None:
    """Create a stub hub note (author/genre) if it does not already exist."""
    safe = safe_filename(wikilink(name)[2:-2])
    write_if_absent(hub_dir / f"{safe}.md", f"---\ntype: {note_type}\n---\n")


def ensure_embed_section(note_text: str, heading: str, target: str) -> str:
    """Append a '## <heading>' section embedding *target* iff not already present.

    Uses a relative Markdown embed (``![](target)``) so generic leaf filenames
    (Highlights.md/Review.md) resolve against the note's own folder. The existing
    body is otherwise untouched.
    """
    if re.search(rf"(?m)^##\s+{re.escape(heading)}\s*$", note_text):
        return note_text
    sep = "" if note_text.endswith("\n") else "\n"
    return f"{note_text}{sep}\n## {heading}\n![]({target})\n"


# --- Frontmatter reading ----------------------------------------------------

def _split_frontmatter(text: str) -> tuple[list[str], str]:
    """Return (frontmatter_lines, body); lines exclude the '---' fences.

    If *text* has no leading frontmatter block, returns ([], text).
    """
    if not text.startswith("---"):
        return [], text
    lines = text.split("\n")
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return lines[1:i], "\n".join(lines[i + 1:])
    return [], text


def _key_of(line: str) -> str | None:
    """Return the YAML key of a 'key: value' line, else None."""
    if not line or line[0] in (" ", "\t", "#", "-"):
        return None
    if ":" not in line:
        return None
    return line.split(":", 1)[0].strip()


def _is_blank_value(line: str) -> bool:
    """True if a 'key:' line has an empty value (eligible to fill)."""
    return line.partition(":")[2].strip() == ""


def frontmatter_values(text: str) -> dict[str, str]:
    """Return top-level frontmatter key -> raw value string."""
    data: dict[str, str] = {}
    for line in _split_frontmatter(text)[0]:
        key = _key_of(line)
        if key is not None:
            data.setdefault(key, line.partition(":")[2].strip())
    return data


def unquote(value: str) -> str:
    """Reverse yaml_quote for a scalar (leaves unquoted values untouched)."""
    value = value.strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return value


def extract_wikilinks(value: str) -> list[str]:
    """Pull the names out of a YAML list of [[wikilinks]]."""
    return re.findall(r"\[\[([^\]]+)\]\]", value or "")


# --- Frontmatter merge ("never overwrite") ---------------------------------

def update_frontmatter(note_text: str, updates: dict[str, str]) -> str:
    """Return *note_text* with *updates* applied, filling only empty/absent keys.

    - *updates* maps a property key to a pre-formatted YAML scalar (e.g. the
      output of ``yaml_quote`` / ``link_list``). ``""`` means "emit an empty
      ``key:`` placeholder".
    - A key already present with a non-empty value is left untouched.
    - A key present but blank is filled from *updates* when that update is
      non-empty.
    - Absent keys are appended in ``BOOK_PROPERTY_ORDER`` order.
    - The note body is preserved exactly.
    """
    fm_lines, body = _split_frontmatter(note_text)

    existing: dict[str, int] = {}
    for idx, line in enumerate(fm_lines):
        key = _key_of(line)
        if key is not None and key not in existing:
            existing[key] = idx

    new_lines = list(fm_lines)

    # 1. Fill blanks in place.
    for key, formatted in updates.items():
        if key in existing and formatted != "" and _is_blank_value(new_lines[existing[key]]):
            new_lines[existing[key]] = f"{key}: {formatted}"

    # 2. Append absent keys (canonical order first, then any extras).
    to_add = [k for k in updates if k not in existing]
    ordered = [k for k in BOOK_PROPERTY_ORDER if k in to_add]
    ordered += [k for k in to_add if k not in BOOK_PROPERTY_ORDER]
    for key in ordered:
        formatted = updates[key]
        new_lines.append(f"{key}:" if formatted == "" else f"{key}: {formatted}")

    return "---\n" + "\n".join(new_lines) + "\n---\n" + body


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


# --- Matching normalization -------------------------------------------------

def fold(text: str) -> str:
    """Lowercase and strip accents (NFKD + drop combining marks)."""
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def norm_title(title: str) -> str:
    """Normalized title for matching: folded, punctuation collapsed to spaces."""
    return re.sub(r"[^a-z0-9]+", " ", fold(title)).strip()


def norm_isbn(isbn: str | None) -> str | None:
    """Digits-only ISBN (keeps a trailing X check digit); None if empty."""
    if not isbn:
        return None
    return re.sub(r"[^0-9x]", "", fold(isbn)).upper() or None


def author_key(name: str) -> tuple[str, str]:
    """Reduce an author name to (first, last), ignoring middle names/initials.

    Handles both "First Last" and "Last, First" orderings.
    """
    name = fold(name)
    if "," in name:
        last, _, first = name.partition(",")
        tokens = first.split() + last.split()
    else:
        tokens = name.split()
    tokens = [re.sub(r"[^a-z0-9]", "", t) for t in tokens]
    tokens = [t for t in tokens if t]
    if not tokens:
        return ("", "")
    if len(tokens) == 1:
        return (tokens[0], tokens[0])
    return (tokens[0], tokens[-1])
