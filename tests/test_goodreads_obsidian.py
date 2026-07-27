"""Tests for the Goodreads -> Obsidian importer."""

from pathlib import Path

from books import goodreads_obsidian as gr


HEADER = (
    "Book Id,Title,Author,Author l-f,Additional Authors,ISBN,ISBN13,My Rating,"
    "Publisher,Binding,Number of Pages,Year Published,Original Publication Year,"
    "Date Read,Date Added,Bookshelves,Bookshelves with positions,Exclusive Shelf,"
    "My Review,Spoiler,Private Notes,Read Count,Owned Copies\n"
)

# A read book with review, a to-read book, and a currently-reading book.
ROWS = (
    '1,"Napoleon: A Life",Andrew Roberts,"Roberts, Andrew",,'
    '"=""0141032014""","=""9780141032016""",5.0,Penguin,Paperback,976,2015,2014,'
    '2026/07/17,2026/05/04,history,history (#1),read,'
    '"Great book.<br/><br/>Loved it.",,note-to-self,1,0\n'
    '2,"The Cold War: A New History",John Lewis Gaddis,"Gaddis, John Lewis",,'
    '"=""0143038273""","=""9780143038276""",0,Penguin,Paperback,352,2006,2005,,'
    '2026/07/14,to-read,to-read (#2),to-read,,,,0,0\n'
    '3,"Stalin: Paradoxes of Power",Stephen Kotkin,"Kotkin, Stephen",,'
    '"=""1594203792""","=""9781594203794""",0,Penguin,Hardcover,976,2014,2014,,'
    '2026/04/30,,,currently-reading,,,,1,0\n'
)


def write_csv(tmp_path: Path) -> Path:
    p = tmp_path / "goodreads_library_export.csv"
    p.write_text(HEADER + ROWS, encoding="utf-8")
    return p


def test_parse_csv_fields(tmp_path):
    books = gr.parse_csv(write_csv(tmp_path))
    assert len(books) == 3
    nap = books[0]
    assert nap.title == "Napoleon: A Life"
    assert nap.book_id == "1"
    assert nap.authors == ["Andrew Roberts"]
    assert nap.isbn13 == "9780141032016"
    assert nap.isbn == "0141032014"
    assert nap.rating == 5
    assert nap.pages == "976"
    assert nap.status == "read"
    assert nap.date_read == "2026-07-17"
    assert nap.date_added == "2026-05-04"
    assert nap.shelves == ["history"]
    assert "Great book." in nap.review

    unrated = books[1]
    assert unrated.rating is None          # My Rating 0 -> unrated
    assert unrated.status == "to-read"

    reading = books[2]
    assert reading.status == "reading"     # currently-reading normalized


def test_normalization_helpers():
    from books import obsidian as ob
    assert ob.norm_isbn('="9780698176287"') == "9780698176287"
    assert ob.norm_title("The Cold War: A New History") == \
        ob.norm_title("The Cold War - A New History")
    assert ob.author_key("Terry Martin") == ob.author_key("Terry L. Martin")
    assert ob.author_key("Roberts, Andrew") == ob.author_key("Andrew Roberts")
    assert ob.author_key("Broué, Pierre") == ob.author_key("Pierre Broue")


def test_convert_default_imports_read_and_currently_reading(tmp_path):
    out = tmp_path / "Obsidian"
    stats = gr.convert(write_csv(tmp_path), out)
    # By default the "read" (Napoleon) and "currently-reading" (Stalin) books
    # are created; only the "to-read" book is skipped.
    assert stats["created"] == 2
    assert stats["skipped"] == 1
    # Filenames read "<Title> - <Author>" with the subtitle dropped.
    assert (out / "Books" / "Napoleon - Andrew Roberts.md").exists()
    assert (out / "Books" / "Stalin - Stephen Kotkin.md").exists()


def test_convert_shelf_read_only_excludes_currently_reading(tmp_path):
    out = tmp_path / "Obsidian"
    stats = gr.convert(write_csv(tmp_path), out, shelf="read")
    assert stats["created"] == 1
    assert stats["skipped"] == 2
    assert (out / "Books" / "Napoleon - Andrew Roberts.md").exists()
    assert not (out / "Books" / "Stalin - Stephen Kotkin.md").exists()


def test_norm_format_maps_bindings():
    assert gr._norm_format("Paperback") == "physical"
    assert gr._norm_format("Hardcover") == "physical"
    assert gr._norm_format("Mass Market Paperback") == "physical"
    assert gr._norm_format("Kindle Edition") == "ebook"
    assert gr._norm_format("ebook") == "ebook"
    assert gr._norm_format("Audiobook") == "audiobook"
    assert gr._norm_format(None) == "physical"   # unknown/missing -> physical
    assert gr._norm_format("") == "physical"


def test_convert_sets_format_from_binding(tmp_path):
    out = tmp_path / "Obsidian"
    gr.convert(write_csv(tmp_path), out)  # Napoleon is a Paperback
    note = (out / "Books" / "Napoleon - Andrew Roberts.md").read_text()
    assert "format: physical" in note


def test_convert_writes_rating_as_stars(tmp_path):
    out = tmp_path / "Obsidian"
    gr.convert(write_csv(tmp_path), out)  # Napoleon has My Rating 5
    note = (out / "Books" / "Napoleon - Andrew Roberts.md").read_text()
    assert "rating: ⭐⭐⭐⭐⭐" in note


def test_merge_preserves_existing_ebook_format(tmp_path):
    out = tmp_path / "Obsidian"
    book_dir = out / "Books"
    book_dir.mkdir(parents=True)
    note = book_dir / "Napoleon_ A Life.md"
    # Pre-existing note (e.g. from Calibre) already marked as an ebook.
    note.write_text(
        '---\ntype: book\ntitle: "Napoleon: A Life"\nisbn: "9780141032016"\n'
        'format: ebook\n---\n\nBody.\n',
        encoding="utf-8",
    )
    gr.convert(write_csv(tmp_path), out)  # Goodreads says Paperback -> physical
    assert "format: ebook" in note.read_text()      # not overwritten
    assert "format: physical" not in note.read_text()


def test_convert_shelf_all_imports_everything(tmp_path):
    out = tmp_path / "Obsidian"
    stats = gr.convert(write_csv(tmp_path), out, shelf="all")
    assert stats["created"] == 3


def test_convert_writes_goodreads_url(tmp_path):
    out = tmp_path / "Obsidian"
    gr.convert(write_csv(tmp_path), out)  # Napoleon is Book Id 1
    note = (out / "Books" / "Napoleon - Andrew Roberts.md").read_text()
    assert 'goodreads: "https://www.goodreads.com/book/show/1"' in note


def test_convert_fills_goodreads_url_on_calibre_note(tmp_path):
    out = tmp_path / "Obsidian"
    book_dir = out / "Books"
    book_dir.mkdir(parents=True)
    note = book_dir / "Napoleon_ A Life.md"
    # Pre-existing note (e.g. from Calibre) with a blank goodreads placeholder.
    note.write_text(
        '---\ntype: book\ntitle: "Napoleon: A Life"\nisbn: "9780141032016"\n'
        'goodreads:\n---\n\nBody.\n',
        encoding="utf-8",
    )
    gr.convert(write_csv(tmp_path), out, shelf="read")
    assert 'goodreads: "https://www.goodreads.com/book/show/1"' in note.read_text()


def test_goodreads_url_not_clobbered_on_merge(tmp_path):
    out = tmp_path / "Obsidian"
    book_dir = out / "Books"
    book_dir.mkdir(parents=True)
    note = book_dir / "Napoleon_ A Life.md"
    note.write_text(
        '---\ntype: book\ntitle: "Napoleon: A Life"\nisbn: "9780141032016"\n'
        'goodreads: "https://www.goodreads.com/book/show/999"\n---\n\nBody.\n',
        encoding="utf-8",
    )
    gr.convert(write_csv(tmp_path), out, shelf="read")
    assert "book/show/999" in note.read_text()      # existing value preserved
    assert "book/show/1" not in note.read_text()


def test_shelf_excluded_book_enriches_existing_note(tmp_path):
    out = tmp_path / "Obsidian"
    book_dir = out / "Books"
    book_dir.mkdir(parents=True)
    # An existing note for the to-read "Cold War" book (Book Id 2), blank fields.
    note = book_dir / "The Cold War.md"
    note.write_text(
        '---\ntype: book\ntitle: "The Cold War: A New History"\n'
        'isbn: "9780143038276"\nstatus:\ngoodreads:\n---\n\nBody.\n',
        encoding="utf-8",
    )
    # Default shelf filter excludes to-read; the note must still be enriched.
    stats = gr.convert(write_csv(tmp_path), out)
    updated = note.read_text()
    assert 'goodreads: "https://www.goodreads.com/book/show/2"' in updated
    assert "status: to-read" in updated       # blank field filled by full merge
    assert stats["created"] == 2              # only read/currently-reading created


def test_shelf_excluded_book_without_note_is_not_created(tmp_path):
    out = tmp_path / "Obsidian"
    # No pre-existing note for the to-read "Cold War"; default shelf filter.
    stats = gr.convert(write_csv(tmp_path), out)
    assert not (out / "Books" / "The Cold War - John Lewis Gaddis.md").exists()
    assert stats["created"] == 2 and stats["skipped"] == 1


def test_convert_writes_review_section(tmp_path):
    out = tmp_path / "Obsidian"
    gr.convert(write_csv(tmp_path), out)
    # No separate Review.md leaf files any more.
    assert list(out.rglob("Review.md")) == []
    note = out / "Books" / "Napoleon - Andrew Roberts.md"
    note_text = note.read_text()
    # The review is a write-once '## Review' section inside the book note.
    assert "## Review" in note_text
    assert "Great book." in note_text and "Loved it." in note_text
    assert "source: goodreads" in note_text       # book note stamped


def test_convert_review_section_not_clobbered_on_rerun(tmp_path):
    out = tmp_path / "Obsidian"
    csv = write_csv(tmp_path)
    gr.convert(csv, out)
    note = out / "Books" / "Napoleon - Andrew Roberts.md"
    edited = note.read_text().replace("Great book.", "Great book. (my edit)")
    note.write_text(edited, encoding="utf-8")

    gr.convert(csv, out)  # re-run must not clobber the edited review
    assert "(my edit)" in note.read_text()


def test_convert_merges_into_existing_note_by_isbn(tmp_path):
    out = tmp_path / "Obsidian"
    # Pre-create a note as if from Calibre: has title, empty status/pages.
    book_dir = out / "Books"
    book_dir.mkdir(parents=True)
    note = book_dir / "Napoleon_ A Life.md"
    note.write_text(
        '---\ntype: book\ntitle: "Napoleon: A Life"\nisbn: "9780141032016"\n'
        'status:\npages:\nrating: 4\n---\n\nMy body.\n',
        encoding="utf-8",
    )
    stats = gr.convert(write_csv(tmp_path), out, shelf="read")
    assert stats["merged"] == 1 and stats["created"] == 0
    updated = note.read_text()
    assert "status: read" in updated       # blank filled
    assert "pages: 976" in updated         # blank filled
    assert "rating: 4" in updated          # existing value NOT overwritten (was 4, GR is 5)
    assert "My body." in updated           # body preserved


def test_convert_merges_by_strict_title_author(tmp_path):
    out = tmp_path / "Obsidian"
    book_dir = out / "Books"
    book_dir.mkdir(parents=True)
    note = book_dir / "Napoleon A Life.md"
    # No ISBN -> must match on normalized title + author.
    note.write_text(
        '---\ntype: book\ntitle: "Napoleon - A Life"\n'
        'authors: ["[[Andrew Roberts]]"]\nstatus:\n---\n\nBody.\n',
        encoding="utf-8",
    )
    stats = gr.convert(write_csv(tmp_path), out, shelf="read")
    assert stats["merged"] == 1 and stats["created"] == 0
    assert "status: read" in note.read_text()


def test_convert_idempotent(tmp_path):
    out = tmp_path / "Obsidian"
    gr.convert(write_csv(tmp_path), out)
    before = {p: p.read_text() for p in out.rglob("*.md")}
    gr.convert(write_csv(tmp_path), out)  # second run
    after = {p: p.read_text() for p in out.rglob("*.md")}
    assert before == after


def _minimal_goodreads_csv(path):
    path.write_text(
        "Title,Author,ISBN,ISBN13,My Rating,Average Rating,Number of Pages,"
        "Original Publication Year,Date Read,Date Added,Bookshelves,"
        "Exclusive Shelf,My Review\n"
        '"The Deluge","Adam Tooze",,,,,,,,,,read,\n',
        encoding="utf-8")


def test_goodreads_defaults_csv_to_imports_newest(monkeypatch, tmp_path):
    import typer
    from typer.testing import CliRunner
    from books import goodreads_obsidian as gr, config

    vault = tmp_path / "Vault"
    folder = vault / ".imports" / "goodreads"
    folder.mkdir(parents=True)
    _minimal_goodreads_csv(folder / "export.csv")
    monkeypatch.setattr(config, "resolve_vault", lambda output=None: vault)
    monkeypatch.setattr(config, "resolve_imports",
                        lambda name, output=None: vault / ".imports" / name)

    app = typer.Typer()
    gr.register(app)
    result = CliRunner().invoke(app, [])

    assert result.exit_code == 0, result.output
    assert (vault / "Books" / "The Deluge - Adam Tooze.md").exists()


def test_goodreads_folder_arg_picks_newest(monkeypatch, tmp_path):
    import os
    import typer
    from typer.testing import CliRunner
    from books import goodreads_obsidian as gr, config

    vault = tmp_path / "Vault"
    folder = tmp_path / "exports"
    folder.mkdir()
    old = folder / "old.csv"
    old.write_text("Title,Author,Exclusive Shelf\n", encoding="utf-8")
    _minimal_goodreads_csv(folder / "new.csv")
    os.utime(old, (1000, 1000))
    os.utime(folder / "new.csv", (2000, 2000))
    monkeypatch.setattr(config, "resolve_vault", lambda output=None: vault)

    app = typer.Typer()
    gr.register(app)
    result = CliRunner().invoke(app, ["--csv", str(folder), "--output", str(vault)])

    assert result.exit_code == 0, result.output
    assert (vault / "Books" / "The Deluge - Adam Tooze.md").exists()


def test_goodreads_updates_emit_flag_defaults():
    book = gr.GoodreadsBook(title="Test Book", authors=["Test Author"])
    u = gr._goodreads_updates(book)
    assert u["highlighted"] == "false"
    assert u["reviewed"] == "false"


def test_goodreads_sets_reviewed_true_when_review_written(tmp_path):
    out = tmp_path / "Obsidian"
    gr.convert(write_csv(tmp_path), out)
    # Napoleon has a review; should have both the Review section and reviewed: true.
    note = out / "Books" / "Napoleon - Andrew Roberts.md"
    note_text = note.read_text()
    assert "## Review" in note_text
    assert "reviewed: true" in note_text
    # Stalin has no review; should keep reviewed: false.
    stalin = out / "Books" / "Stalin - Stephen Kotkin.md"
    stalin_text = stalin.read_text()
    assert "## Review" not in stalin_text
    assert "reviewed: false" in stalin_text
