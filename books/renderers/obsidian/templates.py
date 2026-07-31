"""Jinja templates for the Obsidian highlight callout: env, filters, resolution, scaffold.

The template controls the shape of a *single* highlight's ``> [!quote]`` block.
Everything else (sort, source/chapter grouping + headers, anchors, time
suppression, block stitching) stays in ``highlights.py``. Resolution order:
the configured path, then ``~/.config/books/templates/obsidian/callout.md.jinja``,
then the packaged backup — each step warns and falls through on failure, so a
broken template never aborts an export.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

import jinja2

from books.core import config, ui
from books.core.paths import resolve_path

# ``templates.py`` (this module) shadows the sibling ``templates/`` data directory
# as an importable name, so anchor resources on the parent package + subdir instead.
_PACKAGE = "books.renderers.obsidian"
_TEMPLATE_SUBDIR = "templates"
DEFAULT_TEMPLATE = "callout.md.jinja"

# The packaged example set: seeds the scaffold + the byte-for-byte backup default.
EXAMPLE_TEMPLATES = (
    "callout.md.jinja",
    "callout-plain-note.md.jinja",
    "blockquote.md.jinja",
    "plain.md.jinja",
    "minimal.md.jinja",
)


def _quote_filter(text: str | None, prefix: str = ">") -> str:
    """Prefix each line of *text* for a callout body; blank lines keep the bare marker."""
    lines = (text or "").split("\n")
    return "\n".join(f"{prefix} {ln}" if ln.strip() else prefix.rstrip() for ln in lines)


def _tag_filter(slug: str) -> str:
    """Render a tag slug as an Obsidian inline tag (``history`` -> ``#history``)."""
    return f"#{slug}"


_ENV = jinja2.Environment(autoescape=False, keep_trailing_newline=False)
_ENV.filters["quote"] = _quote_filter
_ENV.filters["tag"] = _tag_filter


def _packaged_source(name: str) -> str:
    """Read a packaged template file's text."""
    return resources.files(_PACKAGE).joinpath(_TEMPLATE_SUBDIR, name).read_text(encoding="utf-8")


def resolve_template(explicit_path: str | None) -> jinja2.Template:
    """Compile the highlight callout template, following the resolution order.

    1. *explicit_path* (the configured ``[export.obsidian].highlights_template``)
       when set; 2. the scaffolded ``templates/obsidian/callout.md.jinja``;
    3. the packaged backup. A read/compile failure warns and falls through; the
    packaged backup always compiles.
    """
    if explicit_path:
        path = resolve_path(Path(explicit_path), Path.cwd())
        try:
            return _ENV.from_string(path.read_text(encoding="utf-8"))
        except (OSError, jinja2.TemplateError) as exc:
            ui.warn(f"highlight template {path}: {exc}; falling back to default")
    default_path = config.templates_dir() / "obsidian" / DEFAULT_TEMPLATE
    if default_path.is_file():
        try:
            return _ENV.from_string(default_path.read_text(encoding="utf-8"))
        except (OSError, jinja2.TemplateError) as exc:
            ui.warn(f"highlight template {default_path}: {exc}; using packaged default")
    return _ENV.from_string(_packaged_source(DEFAULT_TEMPLATE))


def scaffold_templates() -> None:
    """Copy the packaged examples into ``templates/obsidian/`` (create-missing only).

    Never overwrites a hand-edited file; re-creates a deleted one. Idempotent.
    Swallows ``OSError`` (e.g. read-only config dir) so it never crashes a command.
    """
    dest_dir = config.templates_dir() / "obsidian"
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        for name in EXAMPLE_TEMPLATES:
            dest = dest_dir / name
            if not dest.exists():
                dest.write_text(_packaged_source(name), encoding="utf-8")
    except OSError:
        pass
