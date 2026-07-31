"""Integration tests for the Kindle importer command layer."""

from pathlib import Path

from books.commands.kindle import command
from books.core import store

MALCOLM = (
    "﻿The Autobiography of Malcolm X (X, Malcolm)\n"
    "- Your Highlight at location 472-473 | Added on Friday, 31 July 2015 00:17:35\n"
    "\n"
    "old version\n"
    "==========\n"
    "﻿The Autobiography of Malcolm X (X, Malcolm)\n"
    "- Your Highlight at location 472-473 | Added on Friday, 31 July 2015 00:18:38\n"
    "\n"
    "new version\n"
    "==========\n"
    "﻿The Autobiography of Malcolm X (X, Malcolm)\n"
    "- Your Note at location 472 | Added on Friday, 31 July 2015 00:19:00\n"
    "\n"
    "a thought\n"
    "==========\n"
)

UNMATCHED = (
    "Some Book Nobody Owns (Nobody)\n"
    "- Your Highlight at location 5-6 | Added on Monday, 1 June 2020 12:00:00\n"
    "\n"
    "orphan book highlight\n"
    "==========\n"
)


def _clippings(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "My Clippings.txt"
    p.write_text(text, encoding="utf-8")
    return p


def _seed_malcolm(vault: Path) -> None:
    store.write_books_csv(
        vault,
        [
            store.BookRow(
                book_id="The Autobiography of Malcolm X - Malcolm X",
                title="The Autobiography of Malcolm X",
                authors=["Malcolm X"],
            )
        ],
    )


def test_convert_dedups_and_writes_store(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    _seed_malcolm(vault)
    stats = command.convert(_clippings(tmp_path, MALCOLM), vault)
    assert stats["books"] == 1
    assert stats["entries"] == 1  # two events collapse to one
    rows = store.read_highlights(vault, "The Autobiography of Malcolm X - Malcolm X")
    assert len(rows) == 1
    assert rows[0].text == "new version"
    assert rows[0].note == "a thought"


def test_convert_skips_unmatched_book(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    _seed_malcolm(vault)
    stats = command.convert(_clippings(tmp_path, MALCOLM + UNMATCHED), vault)
    assert stats["books"] == 1
    assert stats["skipped"] == 1


def test_default_clippings_path_uses_override(tmp_path):
    override = tmp_path / "custom.txt"
    override.write_text("x", encoding="utf-8")
    result = command.default_clippings_path(tmp_path / "vault", str(override))
    assert result == override
