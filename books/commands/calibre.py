#!/usr/bin/env python3
"""Parse a Calibre library into the ``calibre`` CSV-store metadata layer.

Reads each book's ``metadata.opf`` (XML) into a :class:`store.BookRow` and writes
them to ``Data/Sources/calibre.csv`` via ``store.write_layer``. Covers are staged
under ``Data/Sources/_covers/calibre/`` and their vault-relative path recorded in
each row's ``cover`` field; the ``render`` command materializes them (after merge)
into ``Data/Covers/<book_id>.jpg`` and creates the notes/stubs. Ebook files and
Calibre internals are ignored.

The layer is written via ``books.core.store`` (pydantic ``BookRow``); this
importer depends only on ``books.core`` (no renderer dependency).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from xml.etree import ElementTree as ET

import typer

from books.core import config, store, ui
from books.core.paths import resolve_path

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
    ".epub",
    ".mobi",
    ".azw",
    ".azw3",
    ".azw4",
    ".kfx",
    ".pdf",
    ".fb2",
    ".djvu",
    ".lit",
    ".pdb",
    ".rtf",
    ".txt",
    ".docx",
    ".cbz",
    ".cbr",
}


# --- Metadata extraction ---------------------------------------------------


class BookMetadata:
    def __init__(self) -> None:
        self.title: str | None = None
        self.authors: list[str] = []
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

    return meta


# --- BookMetadata -> store.BookRow mapping ---------------------------------


def _rating_str(rating: float | None) -> str:
    """Numeric rating as a compact string ('4', '3.5'), '' when absent."""
    if rating is None:
        return ""
    return str(int(rating)) if float(rating).is_integer() else str(rating)


def _to_row(meta: BookMetadata, cover_rel: str) -> store.BookRow:
    """Map parsed Calibre metadata to a store BookRow (cover = staged rel path)."""
    return store.BookRow(
        title=meta.title or "",
        authors=list(meta.authors),
        series=meta.series or "",
        series_index=meta.series_index or "",
        publisher=meta.publisher or "",
        published=meta.published or "",
        language=meta.language or "",
        format="ebook",  # everything in a Calibre library is an ebook
        rating=_rating_str(meta.rating),
        isbn=meta.isbn or "",
        amazon=meta.amazon or "",
        google=meta.google or "",
        uuid=meta.uuid or "",
        calibre_id=meta.calibre_id or "",
        date_added=meta.date_added or "",
        cover=cover_rel,
    )


# --- Main conversion -------------------------------------------------------


def default_library() -> Path:
    """The default Calibre library location (``~/Calibre Library``).

    The single source of truth for the default, shared by the ``calibre`` command
    and ``sync``'s source detection.
    """
    return Path.home() / "Calibre Library"


def convert(library: Path, output: Path) -> dict:
    """Parse a Calibre library into the ``calibre`` metadata layer CSV.

    Covers are staged under ``Data/Sources/_covers/calibre/<n>.jpg`` and their
    vault-relative path recorded in the row's ``cover`` field; ``render``
    materializes them to ``Data/Covers/<book_id>.jpg`` after merge. No notes,
    stubs, or topics are written (topics are user-owned; the renderer owns notes).
    """
    stats = {"books": 0, "covers": 0, "skipped": 0, "authors": set()}
    output.mkdir(parents=True, exist_ok=True)

    staging = store.cover_staging_dir(output, "calibre")
    if staging.exists():
        shutil.rmtree(staging)  # fresh each run so re-runs don't accumulate

    rows: list[store.BookRow] = []
    opf_paths = sorted(library.rglob("metadata.opf"))
    with ui.progress("Scanning Calibre library", total=len(opf_paths)) as prog:
        for opf_path in opf_paths:
            prog.advance(0)
            rel_parts = opf_path.relative_to(library).parts
            if any(part in IGNORED_NAMES for part in rel_parts):
                continue
            try:
                meta = parse_opf(opf_path)
            except ET.ParseError as exc:
                ui.warn(f"could not parse {opf_path}: {exc}")
                stats["skipped"] += 1
                continue
            if not meta.title:
                stats["skipped"] += 1
                continue

            cover_rel = ""
            cover_src = opf_path.parent / "cover.jpg"
            if cover_src.is_file():
                cover_rel = store.stage_cover(output, "calibre", str(len(rows)), src=cover_src)
                stats["covers"] += 1

            rows.append(_to_row(meta, cover_rel))
            stats["books"] += 1
            stats["authors"].update(meta.authors)

    store.write_layer(output, "calibre", rows)
    return stats


def calibre_to_obsidian(
    library: Path | None = typer.Option(
        None,
        "--library",
        "-l",
        help="Path to the Calibre library. Defaults to ~/Calibre Library. "
        "Relative paths resolve against your home directory.",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Output Obsidian vault. Defaults to the vault from your config file "
        "(~/.config/books/config.toml). Relative paths resolve against the current directory.",
    ),
) -> None:
    """Parse a Calibre library into the CSV-store ``calibre`` metadata layer.

    INPUT (--library): a Calibre library folder containing per-book subfolders
    with a metadata.opf (XML) and, usually, a cover.jpg. Ebook files (.epub,
    .mobi, ...) and Calibre internals (metadata.db, .caltrash, ...) are ignored.
    Explicit relative paths resolve against your home directory; default:
    ~/Calibre Library.

    OUTPUT (--output): an Obsidian vault folder. Relative paths resolve against
    the current directory; default: ./Obsidian. Writes one BookRow per book into
    Data/Sources/calibre.csv and stages each cover under
    Data/Sources/_covers/calibre/. Run ``merge`` then ``render`` to turn the
    layer into notes (which also materializes the staged covers). No notes,
    stubs, or topics are written here.
    """
    if library is None:
        library = default_library()
    else:
        library = resolve_path(library, Path.home())
    output = config.resolve_vault(output)

    if not library.is_dir():
        raise typer.BadParameter(f"library not found: {library}", param_hint="--library")

    output.mkdir(parents=True, exist_ok=True)
    stats = convert(library, output)
    ui.info(
        f"Done. {stats['books']} books, {stats['covers']} covers, "
        f"{len(stats['authors'])} authors, {stats['skipped']} skipped.\n"
        f"Output: {output}"
    )


def register(app: typer.Typer) -> None:
    """Register this capability's command(s) on the shared Typer app."""
    app.command("calibre")(calibre_to_obsidian)
