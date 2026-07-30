"""Obsidian renderer: vault layout, frontmatter schema, sections, formatting."""

from books.renderers.obsidian.format import format_rating, wikilink
from books.renderers.obsidian.frontmatter import BOOK_PROPERTY_ORDER
from books.renderers.obsidian.highlights import build_anchors, render_highlights
from books.renderers.obsidian.layout import (
    AUTHORS_DIRNAME,
    BOOKS_DIRNAME,
    COVER_WIDTH,
    COVERS_DIRNAME,
    write_if_absent,
    write_stub,
)
from books.renderers.obsidian.sections import (
    ensure_section,
    ensure_top_embed,
    render_marked_section,
)

__all__ = [
    "AUTHORS_DIRNAME",
    "BOOKS_DIRNAME",
    "BOOK_PROPERTY_ORDER",
    "COVERS_DIRNAME",
    "COVER_WIDTH",
    "build_anchors",
    "ensure_section",
    "ensure_top_embed",
    "format_rating",
    "render_highlights",
    "render_marked_section",
    "wikilink",
    "write_if_absent",
    "write_stub",
]
