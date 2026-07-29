"""VaultIndex: match a BookRef to a flat book note (find / find_or_create)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from books.renderers.obsidian.format import link_list, yaml_quote
from books.renderers.obsidian.frontmatter import (
    BOOK_FLAG_DEFAULTS,
    extract_wikilinks,
    frontmatter_values,
    unquote,
    update_frontmatter,
)
from books.renderers.obsidian.layout import BOOKS_DIRNAME, next_free_stem
from books.renderers.obsidian.matching import (
    author_key,
    norm_amazon,
    norm_isbn,
    norm_title,
)


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
        stem = next_free_stem(ref.title, author, self.used_stems)
        self.used_stems.add(stem.lower())
        return self.vault / BOOKS_DIRNAME / f"{stem}.md"

    def find(self, ref: BookRef) -> BookNote | None:
        """Return the existing BookNote for a ref, or None (never creates).

        Used by the highlight-only importers (kobo/highlighted/readwise), which
        enrich notes created by calibre/goodreads but never author book identity
        themselves.
        """
        note = self._match(ref)
        if note is None:
            return None
        self._register(ref, note)
        return BookNote(note, created=False)

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
                **BOOK_FLAG_DEFAULTS,
            })
            note.write_text(stub, encoding="utf-8")
        self._register(ref, note)
        return BookNote(note, created)
