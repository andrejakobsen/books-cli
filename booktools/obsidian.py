"""Shared helpers for writing Obsidian book-note vaults.

All importers (Calibre, Goodreads, Kobo, Highlighted) write book notes with the
same YAML frontmatter schema and the same "never overwrite" rule, so their data
(plus your own manual edits) composes without clobbering. Everything they share
lives here.

Standard library only.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
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
    "topics",
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
    "source",
    "cover",
    "notes",
)


# --- Vault layout -----------------------------------------------------------

# Book notes live flat in vault/Books/ and are the single indexed file per book:
# frontmatter + a cover embed + inline highlights (+ an optional review). Covers
# live flat in vault/Covers/ (a visible folder, so the embed renders; the user
# hides it in Obsidian). Personal notes are hand-made in vault/Notes/ and never
# touched by the tooling — the book note only links to them.
BOOKS_DIRNAME = "Books"
COVERS_DIRNAME = "Covers"
NOTES_DIRNAME = "Notes"
AUTHORS_DIRNAME = "Authors"
TOPICS_DIRNAME = "Topics"

# Width (in px) for the cover embed at the top of a book note.
COVER_WIDTH = 150


# --- YAML / link formatting -------------------------------------------------

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


def strip_subtitle(title: str) -> str:
    """Drop everything after the first ':' (the subtitle), for tidy filenames.

    ``"The Deluge: The Great War..."`` -> ``"The Deluge"``. Falls back to the
    full (stripped) title when nothing precedes the colon.
    """
    head = (title or "").split(":", 1)[0].strip()
    return head or (title or "").strip()


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


def _marker_pair(marker: str) -> tuple[str, str]:
    """Return the (start, end) HTML-comment markers for a generated block."""
    return f"%% books:{marker}:start %%", f"%% books:{marker}:end %%"


def render_marked_section(
    note_text: str, heading: str, marker: str, content: str) -> str:
    """Insert-or-replace a '## <heading>' section whose body is marker-delimited.

    The generated body lives between ``%% books:<marker>:start %%`` and
    ``%% books:<marker>:end %%`` comment markers. On a re-run only the text
    between the markers is replaced — the heading and everything outside the
    markers (a hand-written ``## Review`` section, note body, etc.) is left
    untouched. When the markers are absent the whole ``## heading`` section is
    appended. Idempotent for a given *content*.
    """
    start, end = _marker_pair(marker)
    block = f"{start}\n{content.rstrip(chr(10))}\n{end}"
    pattern = re.compile(rf"{re.escape(start)}.*?{re.escape(end)}", re.DOTALL)
    if pattern.search(note_text):
        return pattern.sub(lambda _m: block, note_text)
    sep = "" if note_text.endswith("\n") else "\n"
    return f"{note_text}{sep}\n## {heading}\n{block}\n"


def ensure_section(note_text: str, heading: str, content: str) -> str:
    """Append a '## <heading>' section with inline *content* iff heading absent.

    Write-once: if the note already has a ``## <heading>`` the note is returned
    unchanged (used for the imported review, which must never be clobbered).
    """
    if re.search(rf"(?m)^##\s+{re.escape(heading)}\s*$", note_text):
        return note_text
    sep = "" if note_text.endswith("\n") else "\n"
    return f"{note_text}{sep}\n## {heading}\n{content.rstrip(chr(10))}\n"


def ensure_top_embed(note_text: str, embed: str) -> str:
    """Insert *embed* at the top of the note body iff not already present.

    *embed* is a full embed line (e.g. ``![[Covers/<stem>.jpg|150]]``). The line
    is placed immediately after the frontmatter block, above any existing body.
    A no-op when the exact embed already appears anywhere in the note.
    """
    if embed in note_text:
        return note_text
    if not note_text.startswith("---"):
        body = note_text.lstrip("\n")
        return f"{embed}\n\n{body}" if body else f"{embed}\n"
    fm_lines, body = _split_frontmatter(note_text)
    front = "---\n" + "\n".join(fm_lines) + "\n---\n"
    body = body.lstrip("\n")
    return f"{front}\n{embed}\n\n{body}" if body else f"{front}\n{embed}\n"


def cover_path(note_path: Path) -> Path:
    """The flat cover-image path for a book note: ``vault/Covers/<stem>.jpg``.

    Keyed to the note's own filename stem (which VaultIndex already keeps unique),
    so the cover file matches its note one-to-one.
    """
    vault = note_path.parents[1]
    return vault / COVERS_DIRNAME / f"{note_path.stem}.jpg"


def cover_refs(note_path: Path) -> tuple[str, str]:
    """Return (frontmatter_value, body_embed) wikilinks for a book's cover.

    The frontmatter value is a plain quoted wikilink (for gallery/Bases views);
    the body embed carries the fixed display width (``|150``).
    """
    target = cover_path(note_path).relative_to(note_path.parents[1]).as_posix()
    return yaml_quote(f"[[{target}]]"), f"![[{target}|{COVER_WIDTH}]]"


def notes_ref(note_path: Path) -> str:
    """Yaml-quoted, path-qualified wikilink to the book's personal-notes file.

    Path-qualified (``[[Notes/<stem>]]``) so it does not collide with the
    identically-named ``Books/<stem>`` note. The file itself is hand-made.
    """
    return yaml_quote(f"[[{NOTES_DIRNAME}/{note_path.stem}]]")


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


# --- Book-note orchestration (shared by importers) --------------------------

@dataclass
class BookRef:
    """Source-neutral book identity used for matching and note creation."""
    title: str
    authors: list[str] = field(default_factory=list)
    isbn: str | None = None
    amazon: str | None = None


@dataclass
class BookNote:
    """The flat book note for a ref (the single indexed file per book)."""
    note_path: Path      # vault/Books/<name>.md
    created: bool        # True if the note was created by this call


def build_index(vault: Path) -> tuple[dict[str, Path], dict[tuple, Path], dict[str, Path]]:
    """Index existing flat book notes by normalized ISBN, (title, author), and amazon."""
    by_isbn: dict[str, Path] = {}
    by_title_author: dict[tuple, Path] = {}
    by_amazon: dict[str, Path] = {}
    books_dir = vault / BOOKS_DIRNAME
    if not books_dir.is_dir():
        return by_isbn, by_title_author, by_amazon
    for md in sorted(books_dir.glob("*.md")):
        try:
            text = md.read_text(encoding="utf-8")
        except OSError:
            continue
        fm = frontmatter_values(text)
        if unquote(fm.get("type", "")) != "book":
            continue
        isbn = norm_isbn(unquote(fm.get("isbn", "")))
        if isbn:
            by_isbn.setdefault(isbn, md)
        amazon = norm_amazon(unquote(fm.get("amazon", "")))
        if amazon:
            by_amazon.setdefault(amazon, md)
        title = unquote(fm.get("title", ""))
        authors = extract_wikilinks(fm.get("authors", ""))
        if title and authors:
            by_title_author.setdefault((norm_title(title), author_key(authors[0])), md)
    return by_isbn, by_title_author, by_amazon


class VaultIndex:
    """The single layout authority: match books to flat notes.

    Owns where a book note lives (flat, in ``Books/``) and how flat filenames are
    disambiguated when two different books share a title. A book's cover lives at
    ``cover_path(note)`` (flat, in ``Covers/``), keyed to the note's own stem.
    """

    def __init__(self, vault: Path) -> None:
        self.vault = vault
        self.by_isbn, self.by_ta, self.by_amazon = build_index(vault)
        books_dir = vault / BOOKS_DIRNAME
        self.used_stems: set[str] = (
            {p.stem.lower() for p in books_dir.glob("*.md")}
            if books_dir.is_dir() else set()
        )

    def _match(self, ref: BookRef) -> Path | None:
        isbn = norm_isbn(ref.isbn)
        if isbn and isbn in self.by_isbn:
            return self.by_isbn[isbn]
        amazon = norm_amazon(ref.amazon)
        if amazon and amazon in self.by_amazon:
            return self.by_amazon[amazon]
        if ref.title and ref.authors:
            key = (norm_title(ref.title), author_key(ref.authors[0]))
            if key in self.by_ta:
                return self.by_ta[key]
        return None

    def _register(self, ref: BookRef, note: Path) -> None:
        isbn = norm_isbn(ref.isbn)
        if isbn:
            self.by_isbn.setdefault(isbn, note)
        amazon = norm_amazon(ref.amazon)
        if amazon:
            self.by_amazon.setdefault(amazon, note)
        if ref.title and ref.authors:
            self.by_ta.setdefault(
                (norm_title(ref.title), author_key(ref.authors[0])), note)

    def _new_note_path(self, ref: BookRef) -> Path:
        """Pick a flat, collision-free note filename for a brand-new book.

        Filenames read ``<Title> - <Author>`` with the subtitle (anything after
        the first ':') dropped, e.g. ``The Deluge - Adam Tooze``. When that clean
        stem is already taken (e.g. two Kotkin "Stalin" volumes), the subtitle is
        restored to disambiguate, with the illegal ':' rendered as ','; a numeric
        ``(n)`` suffix is the last resort if even that collides.
        """
        author = ref.authors[0] if ref.authors else ""

        def stem_for(title: str) -> str:
            return safe_filename(f"{title} - {author}" if author else title)

        short = stem_for(strip_subtitle(ref.title))
        if short.lower() not in self.used_stems:
            stem = short
        else:
            full = stem_for(ref.title.replace(":", ","))
            stem = full
            n = 2
            while stem.lower() in self.used_stems:
                stem = safe_filename(f"{full} ({n})")
                n += 1
        self.used_stems.add(stem.lower())
        return self.vault / BOOKS_DIRNAME / f"{stem}.md"

    def find_or_create(self, ref: BookRef) -> BookNote:
        """Return a BookNote, creating a flat stub note when the book is new."""
        note = self._match(ref)
        created = note is None
        if created:
            note = self._new_note_path(ref)
            note.parent.mkdir(parents=True, exist_ok=True)
            stub = update_frontmatter("---\ntype: book\n---\n", {
                "title": yaml_quote(ref.title) if ref.title else "",
                "authors": link_list(ref.authors) if ref.authors else "",
                "notes": notes_ref(note),
            })
            note.write_text(stub, encoding="utf-8")
        self._register(ref, note)
        return BookNote(note, created)


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


def norm_amazon(amazon: str | None) -> str | None:
    """Alphanumeric-only, uppercased Amazon id (ASIN); None if empty."""
    if not amazon:
        return None
    return re.sub(r"[^a-z0-9]", "", fold(amazon)).upper() or None


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
