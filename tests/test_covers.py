"""Tests for the `books covers` capability (booktools.covers)."""

from pathlib import Path

from booktools import covers


def test_dataclasses_exist():
    mb = covers.MissingBook(
        note_path=Path("/x/Books/A.md"),
        title="A Title",
        authors=["An Author"],
        isbn="123",
        amazon="B00XYZ",
    )
    assert mb.title == "A Title"
    assert mb.authors == ["An Author"]

    c = covers.Candidate(
        source="google", label="A Title — An Author",
        image_url="https://x/y.jpg", fmt=None,
    )
    assert c.source == "google"
    assert c.fmt is None


def _write_note(vault: Path, name: str, body: str) -> Path:
    books = vault / "Books"
    books.mkdir(parents=True, exist_ok=True)
    p = books / name
    p.write_text(body, encoding="utf-8")
    return p


def test_find_missing_selects_blank_cover_book_notes(tmp_path):
    # blank cover -> included
    _write_note(tmp_path, "A.md",
        '---\ntype: book\ntitle: "A"\nauthors: ["[[Ann Author]]"]\n'
        'isbn: "111"\namazon: "B001"\ncover:\n---\nbody\n')
    # non-empty cover -> excluded
    _write_note(tmp_path, "B.md",
        '---\ntype: book\ntitle: "B"\ncover: "[[Exports/x/cover.jpg]]"\n---\n')
    # absent cover key -> included
    _write_note(tmp_path, "C.md",
        '---\ntype: book\ntitle: "C"\nauthors: ["[[Cee]]"]\n---\n')
    # not a book -> excluded
    _write_note(tmp_path, "D.md", '---\ntype: author\ncover:\n---\n')

    missing = covers.find_missing(tmp_path)
    titles = sorted(m.title for m in missing)
    assert titles == ["A", "C"]

    a = next(m for m in missing if m.title == "A")
    assert a.authors == ["Ann Author"]
    assert a.isbn == "111"
    assert a.amazon == "B001"


def test_find_missing_no_books_dir_returns_empty(tmp_path):
    assert covers.find_missing(tmp_path) == []


GOOGLE_VOLUME = {
    "items": [
        {
            "volumeInfo": {
                "title": "The Deluge",
                "authors": ["Adam Tooze"],
                "imageLinks": {
                    "smallThumbnail": "http://books.google.com/x?zoom=5&edge=curl",
                    "thumbnail": "http://books.google.com/x?zoom=1&edge=curl",
                    "large": "http://books.google.com/x?zoom=3",
                },
            }
        }
    ]
}


def test_google_books_prefers_largest_and_upgrades_url():
    book = covers.MissingBook(
        note_path=None, title="The Deluge", authors=["Adam Tooze"],
        isbn=None, amazon=None)
    captured = {}

    def fake_fetch(url):
        captured["url"] = url
        return GOOGLE_VOLUME

    cands = covers.google_books_candidates(book, fake_fetch)
    assert len(cands) == 1
    c = cands[0]
    assert c.source == "google"
    assert c.fmt is None
    # 'large' beats the thumbnails
    assert c.image_url.startswith("https://")   # http -> https
    assert "zoom=3" in c.image_url
    # title/author query when no ISBN
    assert "intitle" in captured["url"]
    assert "inauthor" in captured["url"]


def test_google_books_uses_isbn_query_when_present():
    book = covers.MissingBook(
        note_path=None, title="X", authors=[], isbn="9780141032016", amazon=None)
    captured = {}

    def fake_fetch(url):
        captured["url"] = url
        return {"items": []}

    covers.google_books_candidates(book, fake_fetch)
    assert "isbn:9780141032016" in captured["url"]


def test_google_books_strips_edge_curl_when_only_thumbnail():
    book = covers.MissingBook(
        note_path=None, title="X", authors=[], isbn=None, amazon=None)
    data = {"items": [{"volumeInfo": {"title": "X", "imageLinks": {
        "thumbnail": "http://books.google.com/x?zoom=1&edge=curl"}}}]}
    cands = covers.google_books_candidates(book, lambda url: data)
    assert cands and "edge=curl" not in cands[0].image_url
    assert cands[0].image_url.startswith("https://")


def test_google_books_no_images_returns_empty():
    book = covers.MissingBook(
        note_path=None, title="X", authors=[], isbn=None, amazon=None)
    cands = covers.google_books_candidates(
        book, lambda url: {"items": [{"volumeInfo": {"title": "X"}}]})
    assert cands == []


# Open Library search.json shape (title/author path)
OL_SEARCH = {
    "docs": [
        {
            "title": "Napoleon",
            "author_name": ["Andrew Roberts"],
            "cover_i": 8231856,
            "editions": {
                "docs": [
                    {"physical_format": "Hardcover", "cover_i": 111},
                    {"physical_format": "Paperback", "cover_i": 222},
                ]
            },
        }
    ]
}


def test_openlibrary_title_author_paperback_first():
    book = covers.MissingBook(
        note_path=None, title="Napoleon", authors=["Andrew Roberts"],
        isbn=None, amazon=None)
    captured = {}

    def fake_fetch(url):
        captured["url"] = url
        return OL_SEARCH

    cands = covers.openlibrary_candidates(book, fake_fetch)
    assert cands, "expected at least one candidate"
    assert all(c.source == "openlibrary" for c in cands)
    # paperback edition ranked ahead of hardcover
    fmts = [c.fmt for c in cands]
    assert fmts.index("paperback") < fmts.index("hardcover")
    # paperback candidate points at its own cover id
    pb = next(c for c in cands if c.fmt == "paperback")
    assert "222-L.jpg" in pb.image_url
    assert "title=Napoleon" in captured["url"]
    assert "author=Andrew+Roberts" in captured["url"] or "author=Andrew%20Roberts" in captured["url"]


def test_openlibrary_isbn_path_builds_isbn_cover_url():
    book = covers.MissingBook(
        note_path=None, title="X", authors=[], isbn="9780141032016", amazon=None)
    captured = {}

    def fake_fetch(url):
        captured["url"] = url
        return {"physical_format": "Paperback"}

    cands = covers.openlibrary_candidates(book, fake_fetch)
    assert "/isbn/9780141032016.json" in captured["url"]
    assert cands and "isbn/9780141032016-L.jpg" in cands[0].image_url
    assert cands[0].fmt == "paperback"


def test_openlibrary_no_cover_returns_empty():
    book = covers.MissingBook(
        note_path=None, title="X", authors=[], isbn=None, amazon=None)
    cands = covers.openlibrary_candidates(book, lambda url: {"docs": []})
    assert cands == []


def test_amazon_candidate_from_asin():
    book = covers.MissingBook(
        note_path=None, title="X", authors=["Y"], isbn=None, amazon="B00ABCDEFG")
    cands = covers.amazon_candidates(book)
    assert len(cands) == 1
    assert cands[0].source == "amazon"
    assert "B00ABCDEFG" in cands[0].image_url


def test_amazon_no_asin_returns_empty():
    book = covers.MissingBook(
        note_path=None, title="X", authors=[], isbn=None, amazon=None)
    assert covers.amazon_candidates(book) == []


def test_gather_candidates_source_order():
    book = covers.MissingBook(
        note_path=None, title="Napoleon", authors=["Andrew Roberts"],
        isbn=None, amazon="B00ABCDEFG")

    def fake_fetch(url):
        if "googleapis" in url:
            return GOOGLE_VOLUME
        return OL_SEARCH

    cands = covers.gather_candidates(book, fake_fetch)
    sources = [c.source for c in cands]
    assert sources[0] == "google"
    assert "openlibrary" in sources
    assert sources[-1] == "amazon"
    # google before every openlibrary before amazon
    assert sources.index("google") < sources.index("openlibrary") < sources.index("amazon")


def test_is_valid_image():
    assert covers.is_valid_image(b"x" * 5000, "image/jpeg") is True
    assert covers.is_valid_image(b"x" * 5000, "text/html") is False   # wrong type
    assert covers.is_valid_image(b"x" * 10, "image/gif") is False      # too small
    assert covers.is_valid_image(b"x" * 5000, None) is False           # unknown type


def _cand(source):
    return covers.Candidate(source=source, label="L", image_url=f"http://{source}", fmt=None)


def test_pick_cover_auto_first_valid():
    cands = [_cand("google"), _cand("openlibrary")]

    def fetch_bytes(url):
        if url.endswith("google"):
            return (b"x" * 5, "image/jpeg")       # too small -> invalid
        return (b"x" * 5000, "image/jpeg")        # valid

    picked = covers.pick_cover(cands, fetch_bytes, interactive=False, prompt=None)
    assert picked is not None
    cand, data = picked
    assert cand.source == "openlibrary"
    assert data == b"x" * 5000


def test_pick_cover_auto_none_when_all_invalid():
    cands = [_cand("google")]
    picked = covers.pick_cover(
        cands, lambda url: (b"", "text/html"), interactive=False, prompt=None)
    assert picked is None


def test_pick_cover_interactive_next_then_accept():
    cands = [_cand("google"), _cand("openlibrary")]
    answers = iter(["next", "accept"])

    def fetch_bytes(url):
        return (b"x" * 5000, "image/jpeg")

    picked = covers.pick_cover(
        cands, fetch_bytes, interactive=True, prompt=lambda c: next(answers))
    assert picked[0].source == "openlibrary"


def test_pick_cover_interactive_quit_raises():
    cands = [_cand("google")]
    import pytest
    with pytest.raises(covers.QuitRequested):
        covers.pick_cover(
            cands, lambda url: (b"x" * 5000, "image/jpeg"),
            interactive=True, prompt=lambda c: "quit")


def test_apply_cover_writes_file_and_frontmatter(tmp_path):
    from booktools.obsidian import VaultIndex

    note = _write_note(tmp_path, "Napoleon - Andrew Roberts.md",
        '---\ntype: book\ntitle: "Napoleon"\n'
        'authors: ["[[Andrew Roberts]]"]\ncover:\n---\n\nbody\n')
    book = covers.MissingBook(
        note_path=note, title="Napoleon", authors=["Andrew Roberts"],
        isbn=None, amazon=None)
    index = VaultIndex(tmp_path)

    covers.apply_cover(index, book, b"\xff\xd8\xffJPEGDATA" + b"x" * 2000)

    # cover.jpg written under Exports/<Author>/<Title>/
    cover_file = tmp_path / "Exports" / "Andrew Roberts" / "Napoleon" / "cover.jpg"
    assert cover_file.is_file()

    text = note.read_text(encoding="utf-8")
    # frontmatter cover filled with a wikilink to the exported cover
    assert 'cover: "[[Exports/Andrew Roberts/Napoleon/cover.jpg]]"' in text
    # body embed added; original body preserved
    assert "![[Exports/Andrew Roberts/Napoleon/cover.jpg]]" in text
    assert "body" in text


def test_apply_cover_idempotent(tmp_path):
    from booktools.obsidian import VaultIndex

    note = _write_note(tmp_path, "N - A.md",
        '---\ntype: book\ntitle: "N"\nauthors: ["[[A]]"]\ncover:\n---\n')
    book = covers.MissingBook(
        note_path=note, title="N", authors=["A"], isbn=None, amazon=None)
    index = VaultIndex(tmp_path)

    covers.apply_cover(index, book, b"x" * 2000)
    first = note.read_text(encoding="utf-8")
    covers.apply_cover(index, book, b"x" * 2000)
    second = note.read_text(encoding="utf-8")
    assert first == second   # cover already set -> no duplicate embed/frontmatter
    assert second.count("![[Exports/A/N/cover.jpg]]") == 1


def test_terminal_prompt_maps_keys(monkeypatch):
    answers = iter(["y", "n", "s", "q", "?"])
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))
    cand = _cand("google")
    assert covers._terminal_prompt(cand) == "accept"
    assert covers._terminal_prompt(cand) == "next"
    assert covers._terminal_prompt(cand) == "skip"
    assert covers._terminal_prompt(cand) == "quit"
    # unrecognized input defaults to "next" (safe, non-destructive)
    assert covers._terminal_prompt(cand) == "next"


def test_run_fetches_and_applies(tmp_path):
    _write_note(tmp_path, "Napoleon - Andrew Roberts.md",
        '---\ntype: book\ntitle: "Napoleon"\n'
        'authors: ["[[Andrew Roberts]]"]\ncover:\n---\n')
    # a note that already has a cover -> untouched, not counted
    _write_note(tmp_path, "Done.md",
        '---\ntype: book\ntitle: "Done"\ncover: "[[x/cover.jpg]]"\n---\n')

    def fetch_json(url):
        return GOOGLE_VOLUME if "googleapis" in url else {"docs": []}

    def fetch_bytes(url):
        return (b"x" * 3000, "image/jpeg")

    stats = covers.run(
        tmp_path, interactive=False, dry_run=False, limit=None,
        fetch_json=fetch_json, fetch_bytes=fetch_bytes, prompt=None)

    assert stats["missing"] == 1
    assert stats["fetched"] == 1
    assert stats["by_source"]["google"] == 1
    cover_file = tmp_path / "Exports" / "Andrew Roberts" / "Napoleon" / "cover.jpg"
    assert cover_file.is_file()


def test_run_dry_run_writes_nothing(tmp_path):
    _write_note(tmp_path, "Napoleon - Andrew Roberts.md",
        '---\ntype: book\ntitle: "Napoleon"\n'
        'authors: ["[[Andrew Roberts]]"]\ncover:\n---\n')

    stats = covers.run(
        tmp_path, interactive=False, dry_run=True, limit=None,
        fetch_json=lambda url: GOOGLE_VOLUME,
        fetch_bytes=lambda url: (b"x" * 3000, "image/jpeg"), prompt=None)

    assert stats["fetched"] == 1   # would-fetch is still counted
    assert not (tmp_path / "Exports").exists()


def test_run_limit_caps_processing(tmp_path):
    for i in range(3):
        _write_note(tmp_path, f"B{i} - A.md",
            f'---\ntype: book\ntitle: "B{i}"\nauthors: ["[[A]]"]\ncover:\n---\n')

    stats = covers.run(
        tmp_path, interactive=False, dry_run=True, limit=2,
        fetch_json=lambda url: GOOGLE_VOLUME,
        fetch_bytes=lambda url: (b"x" * 3000, "image/jpeg"), prompt=None)
    assert stats["processed"] == 2


def test_run_quit_stops_early(tmp_path):
    for i in range(3):
        _write_note(tmp_path, f"B{i} - A.md",
            f'---\ntype: book\ntitle: "B{i}"\nauthors: ["[[A]]"]\ncover:\n---\n')

    stats = covers.run(
        tmp_path, interactive=True, dry_run=False, limit=None,
        fetch_json=lambda url: GOOGLE_VOLUME,
        fetch_bytes=lambda url: (b"x" * 3000, "image/jpeg"),
        prompt=lambda c: "quit")
    assert stats["fetched"] == 0


def test_note_to_missing_eligible_and_ineligible(tmp_path):
    note = _write_note(tmp_path, "A - Ann.md",
        '---\ntype: book\ntitle: "A"\nauthors: ["[[Ann]]"]\ncover:\n---\n')
    mb = covers.note_to_missing(note)
    assert mb is not None
    assert mb.title == "A" and mb.authors == ["Ann"]

    has_cover = _write_note(tmp_path, "B - Bee.md",
        '---\ntype: book\ntitle: "B"\ncover: "[[x/cover.jpg]]"\n---\n')
    assert covers.note_to_missing(has_cover) is None   # cover already set

    not_book = _write_note(tmp_path, "C.md", '---\ntype: author\ncover:\n---\n')
    assert covers.note_to_missing(not_book) is None    # wrong type


def test_run_single_book_only_processes_that_note(tmp_path):
    target = _write_note(tmp_path, "Napoleon - Andrew Roberts.md",
        '---\ntype: book\ntitle: "Napoleon"\n'
        'authors: ["[[Andrew Roberts]]"]\ncover:\n---\n')
    # another missing-cover book that must NOT be touched
    _write_note(tmp_path, "Other - X.md",
        '---\ntype: book\ntitle: "Other"\nauthors: ["[[X]]"]\ncover:\n---\n')

    stats = covers.run(
        tmp_path, interactive=False, dry_run=False, limit=None,
        fetch_json=lambda url: GOOGLE_VOLUME,
        fetch_bytes=lambda url: (b"x" * 3000, "image/jpeg"),
        prompt=None, book_path=target)

    assert stats["scanned"] == 1
    assert stats["missing"] == 1
    assert stats["fetched"] == 1
    assert (tmp_path / "Exports" / "Andrew Roberts" / "Napoleon" / "cover.jpg").is_file()
    assert not (tmp_path / "Exports" / "X").exists()


def test_run_single_book_ineligible_is_no_op(tmp_path):
    target = _write_note(tmp_path, "Done - Y.md",
        '---\ntype: book\ntitle: "Done"\ncover: "[[x/cover.jpg]]"\n---\n')
    stats = covers.run(
        tmp_path, interactive=False, dry_run=False, limit=None,
        fetch_json=lambda url: GOOGLE_VOLUME,
        fetch_bytes=lambda url: (b"x" * 3000, "image/jpeg"),
        prompt=None, book_path=target)
    assert stats["missing"] == 0
    assert stats["fetched"] == 0


def test_cli_covers_dry_run(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from booktools.cli import app

    _write_note(tmp_path, "Napoleon - Andrew Roberts.md",
        '---\ntype: book\ntitle: "Napoleon"\n'
        'authors: ["[[Andrew Roberts]]"]\ncover:\n---\n')

    # stub the network so the CLI test stays offline
    monkeypatch.setattr(covers, "default_fetch_json", lambda url: GOOGLE_VOLUME)
    monkeypatch.setattr(
        covers, "default_fetch_bytes", lambda url: (b"x" * 3000, "image/jpeg"))

    result = CliRunner().invoke(
        app, ["covers", "-o", str(tmp_path), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "missing" in result.output.lower()
    assert not (tmp_path / "Exports").exists()


def test_cli_covers_registered():
    from booktools.cli import app
    names = {c.name for c in app.registered_commands}
    assert "covers" in names


def test_cli_covers_single_book_interactive_by_default(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from booktools.cli import app

    note = _write_note(tmp_path, "Napoleon - Andrew Roberts.md",
        '---\ntype: book\ntitle: "Napoleon"\n'
        'authors: ["[[Andrew Roberts]]"]\ncover:\n---\n')
    # another missing-cover book that must NOT be touched
    _write_note(tmp_path, "Other - X.md",
        '---\ntype: book\ntitle: "Other"\nauthors: ["[[X]]"]\ncover:\n---\n')

    monkeypatch.setattr(covers, "default_fetch_json", lambda url: GOOGLE_VOLUME)
    monkeypatch.setattr(
        covers, "default_fetch_bytes", lambda url: (b"x" * 3000, "image/jpeg"))
    # single-book mode is interactive by default -> the prompt is used; accept it.
    monkeypatch.setattr(covers, "_terminal_prompt", lambda c: "accept")

    result = CliRunner().invoke(app, ["covers", "-b", str(note)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "Exports" / "Andrew Roberts" / "Napoleon" / "cover.jpg").is_file()
    assert not (tmp_path / "Exports" / "X").exists()


def test_cli_covers_single_book_rejects_note_outside_books(tmp_path):
    from typer.testing import CliRunner
    from booktools.cli import app

    stray = tmp_path / "stray.md"
    stray.write_text('---\ntype: book\ntitle: "S"\ncover:\n---\n', encoding="utf-8")
    result = CliRunner().invoke(app, ["covers", "-b", str(stray)])
    assert result.exit_code != 0
