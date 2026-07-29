"""Obsidian renderer: vault layout, frontmatter, sections, matching, formatting."""

from books.core.matching import (
    BookRef,
    author_key,
    fold,
    norm_amazon,
    norm_isbn,
    norm_title,
)
from books.core.naming import next_free_stem, safe_filename, strip_subtitle
from books.renderers.obsidian.format import (
    format_rating,
    html_to_markdown,
    link_list,
    plain_list,
    wikilink,
    yaml_quote,
)
from books.renderers.obsidian.frontmatter import (
    BOOK_FLAG_DEFAULTS,
    BOOK_PROPERTY_ORDER,
    OVERWRITE_KEYS,
    extract_wikilinks,
    frontmatter_values,
    unquote,
    update_frontmatter,
)
from books.renderers.obsidian.highlights import build_anchors, render_highlights
from books.renderers.obsidian.layout import (
    AUTHORS_DIRNAME,
    BOOKS_DIRNAME,
    COVER_WIDTH,
    COVERS_DIRNAME,
    NOTES_DIRNAME,
    TOPICS_DIRNAME,
    cover_path,
    cover_refs,
    sanitize_folder_name,
    write_if_absent,
    write_stub,
)
from books.renderers.obsidian.sections import (
    ensure_section,
    ensure_top_embed,
    render_marked_section,
)
__all__ = [
    "AUTHORS_DIRNAME", "BOOKS_DIRNAME", "BOOK_FLAG_DEFAULTS", "BOOK_PROPERTY_ORDER",
    "BookRef", "COVERS_DIRNAME", "COVER_WIDTH", "NOTES_DIRNAME",
    "OVERWRITE_KEYS", "TOPICS_DIRNAME", "author_key", "build_anchors",
    "render_highlights",
    "cover_path", "cover_refs", "ensure_section", "ensure_top_embed",
    "extract_wikilinks", "fold", "format_rating", "frontmatter_values",
    "html_to_markdown", "link_list", "next_free_stem", "norm_amazon", "norm_isbn",
    "norm_title", "plain_list", "render_marked_section", "safe_filename",
    "sanitize_folder_name", "strip_subtitle", "unquote", "update_frontmatter",
    "wikilink", "write_if_absent", "write_stub", "yaml_quote",
]
