"""Book-note frontmatter: canonical schema, reading, and the never-overwrite merge."""

from __future__ import annotations

import re

# --- Canonical property schema ---------------------------------------------

# Order in which book-note frontmatter keys are emitted. Every book note carries
# all of these (empty when unknown) so any field can be filled later by the other
# importer or by hand.
BOOK_PROPERTY_ORDER = (
    "type",
    "title",
    "authors",
    "topics",
    "series",
    "series_index",
    "publisher",
    "published",
    "language",
    "format",
    "pages",
    "status",
    "highlighted",
    "reviewed",
    "shelves",
    "rating",
    "isbn",
    "amazon",
    "google",
    "goodreads",
    "uuid",
    "calibre_id",
    "date_added",
    "date_read",
    "source",
    "cover",
)

# Book-note flags that record whether derived content (highlights, a review) has
# been imported. They are monotonic: an update of "true" always wins, but the
# "false" default follows the normal never-overwrite path so a flag never
# regresses true -> false regardless of import order.
OVERWRITE_KEYS = frozenset({"highlighted", "reviewed"})

# Default values every book note carries so two-way filtering works in Obsidian.
BOOK_FLAG_DEFAULTS = {"highlighted": "false", "reviewed": "false"}


# --- Frontmatter reading ----------------------------------------------------


def _split_frontmatter(text: str) -> tuple[list[str], str]:
    """Return (frontmatter_lines, body); lines exclude the '---' fences.

    If *text* has no leading frontmatter block, returns ([], text).
    """
    if not text.startswith("---"):
        return [], text
    lines = text.split("\n")
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return lines[1:i], "\n".join(lines[i + 1 :])
    return [], text


def _key_of(line: str) -> str | None:
    """Return the YAML key of a 'key: value' line, else None."""
    if not line or line[0] in (" ", "\t", "#", "-"):
        return None
    if ":" not in line:
        return None
    return line.split(":", 1)[0].strip()


def _is_blank_value(line: str) -> bool:
    """True if a 'key:' line has an empty value (eligible to fill)."""
    return line.partition(":")[2].strip() == ""


def frontmatter_values(text: str) -> dict[str, str]:
    """Return top-level frontmatter key -> raw value string."""
    data: dict[str, str] = {}
    for line in _split_frontmatter(text)[0]:
        key = _key_of(line)
        if key is not None:
            data.setdefault(key, line.partition(":")[2].strip())
    return data


def unquote(value: str) -> str:
    """Reverse yaml_quote for a scalar (leaves unquoted values untouched)."""
    value = value.strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return value


def extract_wikilinks(value: str) -> list[str]:
    """Pull the names out of a YAML list of [[wikilinks]]."""
    return re.findall(r"\[\[([^\]]+)\]\]", value or "")


# --- Frontmatter merge ("never overwrite") ---------------------------------


def update_frontmatter(note_text: str, updates: dict[str, str]) -> str:
    """Return *note_text* with *updates* applied, filling only empty/absent keys.

    - *updates* maps a property key to a pre-formatted YAML scalar (e.g. the
      output of ``yaml_quote`` / ``link_list``). ``""`` means "emit an empty
      ``key:`` placeholder".
    - A key already present with a non-empty value is left untouched, except
      keys in ``OVERWRITE_KEYS``, where a ``"true"`` update always overwrites.
    - A key present but blank is filled from *updates* when that update is
      non-empty.
    - Absent keys are appended in ``BOOK_PROPERTY_ORDER`` order.
    - The note body is preserved exactly.
    """
    fm_lines, body = _split_frontmatter(note_text)

    existing: dict[str, int] = {}
    for idx, line in enumerate(fm_lines):
        key = _key_of(line)
        if key is not None and key not in existing:
            existing[key] = idx

    new_lines = list(fm_lines)

    # 1. Fill blanks in place; OVERWRITE_KEYS with a "true" update always win.
    for key, formatted in updates.items():
        if key not in existing or formatted == "":
            continue
        overwrite = key in OVERWRITE_KEYS and formatted == "true"
        if overwrite or _is_blank_value(new_lines[existing[key]]):
            new_lines[existing[key]] = f"{key}: {formatted}"

    # 2. Append absent keys (canonical order first, then any extras).
    to_add = [k for k in updates if k not in existing]
    ordered = [k for k in BOOK_PROPERTY_ORDER if k in to_add]
    ordered += [k for k in to_add if k not in BOOK_PROPERTY_ORDER]
    for key in ordered:
        formatted = updates[key]
        new_lines.append(f"{key}:" if formatted == "" else f"{key}: {formatted}")

    return "---\n" + "\n".join(new_lines) + "\n---\n" + body
