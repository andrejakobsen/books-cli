"""Obsidian renderer: vault layout, frontmatter schema, sections, formatting."""

from books.renderers.obsidian.format import format_rating, wikilink
from books.renderers.obsidian.frontmatter import (
    BOOK_PROPERTY_ORDER,
    NOTE_PROPERTY_ORDER,
    PRESERVED_EXTRA_KEYS,
    RENDER_KEY_ORDER,
    dump_frontmatter,
    load_note,
    split_frontmatter,
)
from books.renderers.obsidian.highlights import build_anchors, render_highlights
from books.renderers.obsidian.layout import (
    AUTHORS_DIRNAME,
    BOOKS_DIRNAME,
    COVER_WIDTH,
    COVERS_DIRNAME,
    cover_embed,
    cover_link,
    write_stub,
)
from books.renderers.obsidian.note import (
    ObsidianRenderer,
    book_frontmatter,
    render,
    render_body,
    render_note,
    render_rating,
)
from books.renderers.obsidian.sections import (
    ensure_section,
    ensure_top_embed,
    render_marked_section,
)
from books.renderers.obsidian.templates import resolve_template, scaffold_templates

__all__ = [
    "AUTHORS_DIRNAME",
    "BOOKS_DIRNAME",
    "BOOK_PROPERTY_ORDER",
    "COVERS_DIRNAME",
    "COVER_WIDTH",
    "NOTE_PROPERTY_ORDER",
    "PRESERVED_EXTRA_KEYS",
    "RENDER_KEY_ORDER",
    "ObsidianRenderer",
    "book_frontmatter",
    "build_anchors",
    "cover_embed",
    "cover_link",
    "dump_frontmatter",
    "ensure_section",
    "ensure_top_embed",
    "format_rating",
    "load_note",
    "render",
    "render_body",
    "render_highlights",
    "render_marked_section",
    "render_note",
    "render_rating",
    "resolve_template",
    "scaffold_templates",
    "split_frontmatter",
    "wikilink",
    "write_stub",
]
