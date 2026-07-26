#!/usr/bin/env python3
"""Convert a Calibre library into an Obsidian-friendly markdown vault.

Reads each book's ``metadata.opf`` (XML), copies ``cover.jpg``, and writes a
markdown note with YAML frontmatter (Obsidian properties). Authors and genres
become ``[[wikilinks]]`` so they cluster in Obsidian's graph, and stub hub notes
are generated for each. Ebook files and Calibre internals are ignored.

Standard library only.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from xml.etree import ElementTree as ET

import typer

from booktools import config, resolve_path
from booktools.obsidian import (
    BookRef,
    VaultIndex,
    cover_refs,
    ensure_top_embed,
    format_rating,
    html_to_markdown,
    link_list,
    update_frontmatter,
    write_stub,
    yaml_quote,
)

# --- XML namespaces used in Calibre .opf files -----------------------------

NS = {
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
}

# Files/dirs we never copy or recurse into.
IGNORED_NAMES = {
    ".calnotes",
    ".caltrash",
    "metadata.db",
    "metadata_db_prefs_backup.json",
}
IGNORED_EBOOK_SUFFIXES = {
    ".epub", ".mobi", ".azw", ".azw3", ".azw4", ".kfx", ".pdf",
    ".fb2", ".djvu", ".lit", ".pdb", ".rtf", ".txt", ".docx", ".cbz", ".cbr",
}


# --- Metadata extraction ---------------------------------------------------

class BookMetadata:
    def __init__(self) -> None:
        self.title: str | None = None
        self.authors: list[str] = []
        self.genres: list[str] = []
        self.publisher: str | None = None
        self.published: str | None = None
        self.language: str | None = None
        self.rating: float | None = None
        self.isbn: str | None = None
        self.amazon: str | None = None
        self.google: str | None = None
        self.uuid: str | None = None
        self.calibre_id: str | None = None
        self.date_added: str | None = None
        self.series: str | None = None
        self.series_index: str | None = None
        self.description: str = ""


def _date_only(value: str | None) -> str | None:
    if not value:
        return None
    return value[:10]  # YYYY-MM-DD


def parse_opf(opf_path: Path) -> BookMetadata:
    """Parse a Calibre metadata.opf file into a BookMetadata object."""
    meta = BookMetadata()
    root = ET.parse(opf_path).getroot()
    metadata = root.find("opf:metadata", NS)
    if metadata is None:
        # Some opf files omit namespaces on <metadata>; fall back to any match.
        metadata = root.find(".//{*}metadata")
    if metadata is None:
        return meta

    def findall(local):
        return metadata.findall(f".//{{*}}{local}")

    title_el = metadata.find(".//{*}title")
    if title_el is not None and title_el.text:
        meta.title = title_el.text.strip()

    for creator in findall("creator"):
        role = creator.get(f"{{{NS['opf']}}}role")
        if role in (None, "aut") and creator.text:
            meta.authors.append(creator.text.strip())

    for subject in findall("subject"):
        if subject.text:
            meta.genres.append(subject.text.strip())

    pub = metadata.find(".//{*}publisher")
    if pub is not None and pub.text:
        meta.publisher = pub.text.strip()

    date = metadata.find(".//{*}date")
    if date is not None and date.text:
        meta.published = _date_only(date.text.strip())

    lang = metadata.find(".//{*}language")
    if lang is not None and lang.text:
        meta.language = lang.text.strip()

    for ident in findall("identifier"):
        scheme = ident.get(f"{{{NS['opf']}}}scheme")
        value = (ident.text or "").strip()
        if not value:
            continue
        key = (scheme or "").upper()
        if key == "ISBN":
            meta.isbn = value
        elif key == "AMAZON":
            meta.amazon = value
        elif key == "GOOGLE":
            meta.google = value
        elif key == "UUID":
            meta.uuid = value
        elif key == "CALIBRE":
            meta.calibre_id = value

    for m in findall("meta"):
        name = m.get("name")
        content = m.get("content")
        if not name or content is None:
            continue
        if name == "calibre:timestamp":
            meta.date_added = _date_only(content)
        elif name == "calibre:rating":
            try:
                meta.rating = float(content) / 2.0  # Calibre stores 0-10
            except ValueError:
                pass
        elif name == "calibre:series":
            meta.series = content.strip()
        elif name == "calibre:series_index":
            meta.series_index = content.strip()

    desc = metadata.find(".//{*}description")
    if desc is not None and desc.text:
        meta.description = html_to_markdown(desc.text)

    return meta


# --- Frontmatter / note construction ---------------------------------------

def _calibre_updates(meta: BookMetadata, cover_fm: str) -> dict[str, str]:
    """Map a BookMetadata to canonical property -> formatted YAML value.

    *cover_fm* is the pre-formatted ``cover:`` value (a vault-relative wikilink,
    or "" when there is no cover). Goodreads-only fields (pages/status/shelves/
    date_read) are emitted empty so the Goodreads importer or manual editing can
    fill them later.
    """
    u: dict[str, str] = {}
    u["title"] = yaml_quote(meta.title) if meta.title else ""
    u["authors"] = link_list(meta.authors) if meta.authors else ""
    u["genres"] = link_list(meta.genres) if meta.genres else ""
    u["series"] = yaml_quote(meta.series) if meta.series else ""
    u["series_index"] = meta.series_index or ""
    u["publisher"] = yaml_quote(meta.publisher) if meta.publisher else ""
    u["published"] = meta.published or ""
    u["language"] = meta.language or ""
    u["format"] = "ebook"  # everything in a Calibre library is an ebook
    u["pages"] = ""
    u["status"] = ""
    u["shelves"] = ""
    u["rating"] = format_rating(meta.rating)
    u["isbn"] = yaml_quote(meta.isbn) if meta.isbn else ""
    u["amazon"] = yaml_quote(meta.amazon) if meta.amazon else ""
    u["google"] = yaml_quote(meta.google) if meta.google else ""
    u["uuid"] = yaml_quote(meta.uuid) if meta.uuid else ""
    u["calibre_id"] = meta.calibre_id or ""
    u["date_added"] = meta.date_added or ""
    u["date_read"] = ""
    u["source"] = "calibre"
    u["cover"] = cover_fm
    return u


def write_note(note_path: Path, meta: BookMetadata,
               cover_fm: str, cover_embed: str) -> None:
    """Merge Calibre metadata into the flat note.

    Frontmatter is always merged (never overwriting existing values). The cover
    embed and description are placed at the top of the body (cover first), each
    inserted only when absent so the result is idempotent and independent of
    import order. Any other existing body content is left untouched.
    """
    note = update_frontmatter(note_path.read_text(encoding="utf-8"),
                              _calibre_updates(meta, cover_fm))
    # Insert description first, then the cover above it, so the final top-of-body
    # order is: cover embed, then description.
    if meta.description:
        note = ensure_top_embed(note, meta.description)
    if cover_embed:
        note = ensure_top_embed(note, cover_embed)
    note_path.write_text(note, encoding="utf-8")


# --- Main conversion -------------------------------------------------------

def convert(library: Path, output: Path) -> dict:
    stats = {"books": 0, "covers": 0, "skipped": 0, "authors": set(), "genres": set()}

    output.mkdir(parents=True, exist_ok=True)
    index = VaultIndex(output)
    authors_dir = output / "Authors"
    genres_dir = output / "Genres"

    for opf_path in sorted(library.rglob("metadata.opf")):
        # Skip anything inside ignored top-level dirs (.caltrash etc.).
        rel_parts = opf_path.relative_to(library).parts
        if any(part in IGNORED_NAMES for part in rel_parts):
            continue

        book_src = opf_path.parent
        try:
            meta = parse_opf(opf_path)
        except ET.ParseError as exc:
            print(f"WARN: could not parse {opf_path}: {exc}")
            stats["skipped"] += 1
            continue
        if not meta.title:
            stats["skipped"] += 1
            continue

        book = index.find_or_create(
            BookRef(title=meta.title, authors=meta.authors, isbn=meta.isbn))

        cover_src = book_src / "cover.jpg"
        cover_fm = cover_embed = ""
        if cover_src.is_file():
            book.export_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(cover_src, book.export_dir / "cover.jpg")
            cover_fm, cover_embed = cover_refs(book.note_path, book.export_dir)
            stats["covers"] += 1

        write_note(book.note_path, meta, cover_fm, cover_embed)
        stats["books"] += 1

        for author in meta.authors:
            write_stub(authors_dir, author, "author")
            stats["authors"].add(author)
        for genre in meta.genres:
            write_stub(genres_dir, genre, "genre")
            stats["genres"].add(genre)

    return stats


def calibre_to_obsidian(
    library: Path | None = typer.Option(
        None,
        "--library", "-l",
        help="Path to the Calibre library. Defaults to ~/Calibre Library. "
             "Relative paths resolve against your home directory.",
    ),
    output: Path | None = typer.Option(
        None,
        "--output", "-o",
        help="Output Obsidian vault. Defaults to the vault from your config file "
             "(~/.config/booktools/config.toml). Relative paths resolve against the current directory.",
    ),
) -> None:
    """Convert a Calibre library into an Obsidian markdown vault.

    INPUT (--library): a Calibre library folder containing per-book subfolders
    with a metadata.opf (XML) and, usually, a cover.jpg. Ebook files (.epub,
    .mobi, ...) and Calibre internals (metadata.db, .caltrash, ...) are ignored.
    Explicit relative paths resolve against your home directory; default:
    ~/Calibre Library.

    OUTPUT (--output): an Obsidian vault folder. Relative paths resolve against
    the current directory; default: ./Obsidian. For each book it writes a flat
    markdown note under Books/ (YAML properties from the opf + cover embed +
    description), copies cover.jpg into Exports/<Author>/<Title>/, and creates
    linked stub notes under Authors/ and Genres/. Re-running is safe: it never
    overwrites notes it did not create or existing note bodies.
    """
    if library is None:
        library = Path.home() / "Calibre Library"
    else:
        library = resolve_path(library, Path.home())
    output = config.resolve_vault(output)

    if not library.is_dir():
        raise typer.BadParameter(f"library not found: {library}", param_hint="--library")

    output.mkdir(parents=True, exist_ok=True)
    stats = convert(library, output)
    typer.echo(
        f"Done. {stats['books']} books, {stats['covers']} covers, "
        f"{len(stats['authors'])} authors, {len(stats['genres'])} genres, "
        f"{stats['skipped']} skipped.\nOutput: {output}"
    )


def register(app: typer.Typer) -> None:
    """Register this capability's command(s) on the shared Typer app."""
    app.command("calibre")(calibre_to_obsidian)


def main() -> None:
    """Standalone entry point so the shim script keeps working on its own."""
    typer.run(calibre_to_obsidian)


if __name__ == "__main__":
    main()
