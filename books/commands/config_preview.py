"""Pure helpers for `books config export`: sample data, discovery, preview.

No TUI/prompt_toolkit here — these functions are the testable core the config
command's shell delegates to. `render_preview` reuses the real Obsidian renderer
so a preview is byte-accurate to a real export.
"""

from __future__ import annotations

from pathlib import Path

from books.core import config
from books.core.highlights import Highlight
from books.renderers.obsidian import render_highlights
from books.renderers.obsidian.templates import resolve_template, scaffold_templates

_SUFFIX = ".md.jinja"


def sample_highlights() -> list[Highlight]:
    """A small, representative highlight set that exercises every template field.

    Covers a chapter title (so chapter subheaders render), an author note, tags,
    links, a percent locator, a page locator, and dated highlights. A single
    (unset) source keeps the preview free of source headers.
    """
    return [
        Highlight(
            text="The quick brown fox jumps over the lazy dog.",
            note="A marginal note from the reader.",
            chapter_index=1,
            chapter_title="On Foxes",
            progress=0.42,
            date="2024-03-15T14:30:00Z",
            tags=["history", "nature"],
            links=["Charles Darwin"],
        ),
        Highlight(
            text="A second highlight a little later in the same chapter.",
            chapter_index=1,
            chapter_title="On Foxes",
            progress=0.58,
            page="42",
            date="2024-03-15T15:10:00Z",
        ),
        Highlight(
            text="A highlight in the next chapter, with no note or tags.",
            chapter_index=2,
            chapter_title="On Dogs",
            progress=0.10,
            date="2024-03-16T09:00:00Z",
        ),
    ]


def template_label(path: Path) -> str:
    """Human label for a template file (``callout.md.jinja`` -> ``callout``)."""
    return path.name[: -len(_SUFFIX)] if path.name.endswith(_SUFFIX) else path.stem


def list_obsidian_templates() -> list[Path]:
    """Scaffold the packaged examples, then return all ``*.md.jinja``, sorted."""
    scaffold_templates()
    obsidian_dir = config.templates_dir() / "obsidian"
    if not obsidian_dir.is_dir():
        return []
    return sorted(obsidian_dir.glob(f"*{_SUFFIX}"))


def render_preview(path: Path) -> str:
    """Render the sample highlights through the template at *path*.

    Uses ``resolve_template`` (explicit path wins) and the real
    ``render_highlights`` so the output matches a real export exactly.
    """
    template = resolve_template(str(path))
    return render_highlights(sample_highlights(), template=template)
