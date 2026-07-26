# Chapter Subheaders for Highlights Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Group highlights under `## Chapter Title` subheaders (with a hidden `%% Kobo ch. N %%` reading-order comment) when a source knows chapter titles, so all highlights for a chapter collect under one heading.

**Architecture:** All logic lives in `render_highlights` in `books/highlights.py` (the shared renderer). It is gated on chapter data: if no highlight has a `chapter_title` the output is flat and unchanged; otherwise it emits a header at each chapter change and drops the redundant `ch. N` from each callout locator. Kobo passes a `chapter_label="Kobo ch."` so its reading-order index renders as a hidden comment. Page-based sources (Highlighted) and chapter-less exports (Readwise) are unaffected because they never set `chapter_title`.

**Tech Stack:** Python 3 (stdlib only), Typer CLI, pytest. Run tests with `uv run pytest`.

---

## File Structure

- `books/highlights.py` — MODIFY. Add `include_chapter` param to `_label`, add `_chapter_key` and `_chapter_header` helpers, and add grouped-mode logic + `chapter_label` param to `render_highlights`.
- `books/kobo_export.py` — MODIFY (line 173). Pass `chapter_label="Kobo ch."` into `render_highlights`.
- `tests/test_highlights.py` — MODIFY. Add grouped-mode tests; update the one existing test that relied on chapter_title rendering flat.
- `tests/test_kobo_export.py` — MODIFY (lines 62-64). Update the flat locator assertion to the new grouped output.

---

## Task 1: Grouped chapter rendering in `highlights.py`

**Files:**
- Modify: `books/highlights.py` (`_label` ~176-187, `render_highlights` ~196-222)
- Test: `tests/test_highlights.py`

- [ ] **Step 1: Write the failing tests**

Add these to the end of `tests/test_highlights.py`:

```python
# --- chapter subheaders ------------------------------------------------------

def test_grouped_emits_title_header_and_hidden_index_comment():
    hs = [hl.Highlight(text="a", chapter_index=12, chapter_title="The Battle",
                       progress=0.42, block="3", segment="5")]
    out = hl.render_highlights(hs, chapter_label="Kobo ch.")
    assert "## The Battle" in out
    assert "%% Kobo ch. 12 %%" in out
    # locator drops "ch. 12", keeps progress
    assert "> [!quote]+ 42%" in out
    assert "ch. 12" not in out.split("%%")[-1]  # no "ch. 12" in the callout region


def test_grouped_no_label_omits_comment():
    hs = [hl.Highlight(text="a", chapter_index=12, chapter_title="The Battle",
                       progress=0.42, block="3", segment="5")]
    out = hl.render_highlights(hs)  # no chapter_label
    assert "## The Battle" in out
    assert "%%" not in out
    assert "> [!quote]+ 42%" in out


def test_grouped_one_header_per_chapter_run():
    hs = [
        hl.Highlight(text="a", chapter_index=1, chapter_title="One",
                     progress=0.1, block="1"),
        hl.Highlight(text="b", chapter_index=1, chapter_title="One",
                     progress=0.2, block="2"),
        hl.Highlight(text="c", chapter_index=2, chapter_title="Two",
                     progress=0.3, block="3"),
    ]
    out = hl.render_highlights(hs, chapter_label="Kobo ch.")
    assert out.count("## One") == 1   # consecutive same-chapter share one header
    assert out.count("## Two") == 1
    assert out.index("## One") < out.index("## Two")


def test_flat_fallback_when_no_chapter_title():
    # No chapter_title anywhere -> flat output, unchanged, no "##" headers.
    hs = [hl.Highlight(text="a", chapter_index=2, progress=0.42,
                       block="17", segment="5")]
    out = hl.render_highlights(hs, chapter_label="Kobo ch.")
    assert "## " not in out
    assert "> [!quote]+ ch. 2 · 42%" in out  # locator keeps chapter in flat mode


def test_grouped_index_only_run_gets_chapter_fallback_header():
    # A title-less highlight among titled ones gets "## Chapter {index}", no comment.
    hs = [
        hl.Highlight(text="a", chapter_index=1, chapter_title="Intro",
                     progress=0.1, block="1"),
        hl.Highlight(text="b", chapter_index=2, chapter_title=None,
                     progress=0.2, block="2"),
    ]
    out = hl.render_highlights(hs, chapter_label="Kobo ch.")
    assert "## Intro" in out
    assert "## Chapter 2" in out
    assert "%% Kobo ch. 2 %%" not in out  # no comment under a "## Chapter N" header


def test_no_hr_divider_between_highlights():
    hs = [
        hl.Highlight(text="a", chapter_index=1, chapter_title="One", block="1"),
        hl.Highlight(text="b", chapter_index=1, chapter_title="One", block="2"),
    ]
    out = hl.render_highlights(hs, chapter_label="Kobo ch.")
    assert "\n---\n" not in out
    assert "\n***\n" not in out
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `uv run pytest tests/test_highlights.py -k "grouped or flat_fallback or hr_divider" -v`
Expected: FAIL — `render_highlights()` currently takes no `chapter_label` argument (TypeError) and emits no `##` headers.

- [ ] **Step 3: Implement grouped rendering**

In `books/highlights.py`, replace the `_label` function (currently ~176-187) with a version that takes `include_chapter`:

```python
def _label(h: Highlight, include_chapter: bool = True) -> str:
    parts: list[str] = []
    if include_chapter:
        if h.chapter_index is not None:
            parts.append(f"ch. {h.chapter_index}")
        elif h.chapter_title:
            parts.append(h.chapter_title)
    if h.page:
        prefix = h.location_label or "p."
        parts.append(f"{prefix} {h.page.replace('-', '–')}")
    if h.progress is not None:
        parts.append(f"{round(h.progress * 100)}%")
    return " · ".join(parts)


def _chapter_key(h: Highlight) -> tuple:
    """Identity of the chapter a highlight belongs to, for consecutive-run grouping."""
    if h.chapter_title:
        return ("title", h.chapter_title)
    if h.chapter_index is not None:
        return ("index", h.chapter_index)
    return ("none",)


def _chapter_header(h: Highlight, chapter_label: str | None) -> str | None:
    """Markdown header for a chapter run, plus an optional hidden index comment.

    ``## {title}`` when a title is known; the reading-order index renders as a
    hidden ``%% {chapter_label} {index} %%`` comment beneath it (only when both an
    index and a label are present). A title-less run with only an index falls back
    to ``## Chapter {index}`` (no comment). Returns None when the run has neither.
    """
    if h.chapter_title:
        header = f"## {h.chapter_title}"
        if h.chapter_index is not None and chapter_label:
            header += f"\n%% {chapter_label} {h.chapter_index} %%"
        return header
    if h.chapter_index is not None:
        return f"## Chapter {h.chapter_index}"
    return None
```

Then replace the `render_highlights` function (currently ~196-222) with:

```python
def render_highlights(highlights: list[Highlight],
                      chapter_label: str | None = None) -> str:
    """Render an ordered list of highlights as an Obsidian ``Highlights.md`` body.

    When any highlight carries a ``chapter_title`` the output is *grouped*: a
    ``## {title}`` header (with a hidden ``%% {chapter_label} N %%`` reading-order
    comment) is emitted at each chapter change, and each callout's locator drops
    the now-redundant ``ch. N``. When no highlight has a chapter title the output
    is flat (locator keeps ``ch. N``). ``chapter_label`` is the prefix for the
    hidden comment (e.g. Kobo passes ``"Kobo ch."``); when None the comment is
    omitted but grouping still happens.

    Each highlight is a single expanded ``[!quote]`` callout (one block anchor).
    The title line carries the locator plus the ``@links`` as comma-separated
    ``[[wikilinks]]``. The body holds the quoted text, then the author's note as a
    nested blockquote (``>> ...``), then the ``#tags`` on a trailing line.
    """
    anchors = build_anchors(highlights)
    grouped = any(h.chapter_title for h in highlights)
    blocks: list[str] = []
    prev_key = None
    for h, anchor in zip(highlights, anchors):
        if grouped:
            key = _chapter_key(h)
            if key != prev_key:
                header = _chapter_header(h, chapter_label)
                if header:
                    blocks.append(header)
                prev_key = key
        title_parts = [p for p in (_label(h, include_chapter=not grouped),) if p]
        if h.links:
            title_parts.append(", ".join(wikilink(name) for name in h.links))
        title = " · ".join(title_parts)
        lines = ["> [!quote]+" + (f" {title}" if title else "")]
        lines += _quote_lines(h.text, ">")
        if h.note and h.note.strip():
            lines.append(">")
            lines += _quote_lines(h.note, ">>")
        if h.tags:
            lines.append(">")
            lines.append("> " + " ".join(f"#{t}" for t in h.tags))
        lines.append(f"^{anchor}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"
```

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `uv run pytest tests/test_highlights.py -k "grouped or flat_fallback or hr_divider" -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Update the one existing test that relied on flat chapter-title rendering**

The old test `test_render_label_falls_back_to_chapter_title_then_percent` (~line 61) asserted a chapter_title rendered flat as a locator. That behavior is now grouped. Replace that test with:

```python
def test_render_chapter_title_becomes_header_index_absent_no_comment():
    hs = [hl.Highlight(text="x", chapter_title="Intro", progress=0.1, block="2")]
    out = hl.render_highlights(hs, chapter_label="Kobo ch.")
    assert "## Intro" in out
    assert "%%" not in out               # no index -> no hidden comment
    assert "> [!quote]+ 10%" in out      # locator dropped the title, kept percent


def test_render_no_chapter_locator_is_percent_only():
    hs = [hl.Highlight(text="y", progress=0.9, block="2")]
    assert "> [!quote]+ 90%" in hl.render_highlights(hs)
```

- [ ] **Step 6: Run the full highlights suite**

Run: `uv run pytest tests/test_highlights.py -v`
Expected: PASS (all tests, including the updated ones).

- [ ] **Step 7: Commit**

```bash
git add books/highlights.py tests/test_highlights.py
git commit -m "feat(highlights): group highlights under chapter subheaders"
```

---

## Task 2: Kobo passes the reading-order label

**Files:**
- Modify: `books/kobo_export.py:173`
- Test: `tests/test_kobo_export.py:62-64`

- [ ] **Step 1: Update the Kobo obsidian export assertion (failing test)**

In `tests/test_kobo_export.py`, inside `test_export_obsidian_writes_highlights_and_embed`, replace the single assertion line (currently line 63):

```python
    assert "> [!quote]+ ch. 2 · 42%" in highlights
```

with:

```python
    assert "## Chapter 2" in highlights          # chapter title header
    assert "%% Kobo ch. 2 %%" in highlights      # hidden reading-order comment
    assert "> [!quote]+ 42%" in highlights       # locator drops the chapter
```

(The chapter row inserted by `_make_db` has title `"Chapter 2"` and VolumeIndex `2`.)

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_kobo_export.py::test_export_obsidian_writes_highlights_and_embed -v`
Expected: FAIL — the export still calls `render_highlights` without a label, so no header/comment appear and the locator still reads `ch. 2 · 42%`.

- [ ] **Step 3: Pass the chapter label from the Kobo exporter**

In `books/kobo_export.py`, in `export_obsidian` (~line 171-173), change:

```python
        write_leaf_with_embed(
            dest.note_path, dest.export_dir, "Highlights.md",
            with_source("kobo", render_highlights(highlights)), "Highlights")
```

to:

```python
        write_leaf_with_embed(
            dest.note_path, dest.export_dir, "Highlights.md",
            with_source("kobo", render_highlights(highlights, chapter_label="Kobo ch.")),
            "Highlights")
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_kobo_export.py::test_export_obsidian_writes_highlights_and_embed -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS (all tests across all files; Highlighted and Readwise are unaffected since they never set `chapter_title`).

- [ ] **Step 6: Commit**

```bash
git add books/kobo_export.py tests/test_kobo_export.py
git commit -m "feat(kobo): render chapter subheaders with hidden reading-order comment"
```

---

## Notes for the implementer

- **Why grouping triggers on `chapter_title` (not `chapter_index`):** the goal is collecting highlights under a readable chapter name. A source with only reading-order indices and no titles has nothing meaningful to head with, so it stays flat.
- **`prev_key` starts as `None`:** `_chapter_key` always returns a tuple, so the first highlight's key never equals `None` and its header is always emitted.
- **A "none" run** (a highlight with neither title nor index, sitting among titled ones) produces no header — its callout renders bare in reading order. This is rare with Kobo.
- **Do not add `---` dividers.** The renderer joins blocks with a blank line; the regression test in Task 1 locks this in.
```
