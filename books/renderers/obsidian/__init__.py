"""Obsidian renderer: vault layout, frontmatter, sections, matching, formatting."""

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
from books.renderers.obsidian.layout import (
    AUTHORS_DIRNAME,
    BOOKS_DIRNAME,
    COVER_WIDTH,
    COVERS_DIRNAME,
    NOTES_DIRNAME,
    TOPICS_DIRNAME,
    cover_path,
    cover_refs,
    next_free_stem,
    safe_filename,
    sanitize_folder_name,
    strip_subtitle,
    write_if_absent,
    write_stub,
)
from books.renderers.obsidian.matching import (
    author_key,
    fold,
    norm_amazon,
    norm_isbn,
    norm_title,
)
from books.renderers.obsidian.sections import (
    ensure_section,
    ensure_top_embed,
    render_marked_section,
)
from books.renderers.obsidian.vault_index import (
    BookNote,
    BookRef,
    VaultIndex,
    build_index,
)

__all__ = [
    "AUTHORS_DIRNAME", "BOOKS_DIRNAME", "BOOK_FLAG_DEFAULTS", "BOOK_PROPERTY_ORDER",
    "BookNote", "BookRef", "COVERS_DIRNAME", "COVER_WIDTH", "NOTES_DIRNAME",
    "OVERWRITE_KEYS", "TOPICS_DIRNAME", "VaultIndex", "author_key", "build_index",
    "cover_path", "cover_refs", "ensure_section", "ensure_top_embed",
    "extract_wikilinks", "fold", "format_rating", "frontmatter_values",
    "html_to_markdown", "link_list", "next_free_stem", "norm_amazon", "norm_isbn",
    "norm_title", "plain_list", "render_marked_section", "safe_filename",
    "sanitize_folder_name", "strip_subtitle", "unquote", "update_frontmatter",
    "wikilink", "write_if_absent", "write_stub", "yaml_quote",
]
