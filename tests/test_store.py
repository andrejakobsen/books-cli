from pathlib import Path

from books import store


def test_bookrow_csv_roundtrip_joins_list_fields():
    row = store.BookRow(
        title="The Deluge",
        authors=["Adam Tooze"],
        shelves=["read", "history"],
        format="ebook",
        isbn="9780141032184",
    )
    d = row.to_csv_dict()
    assert d["authors"] == "Adam Tooze"
    assert d["shelves"] == "read;history"
    assert d["title"] == "The Deluge"
    back = store.BookRow.from_csv_dict(d)
    assert back.authors == ["Adam Tooze"]
    assert back.shelves == ["read", "history"]
    assert back.format == "ebook"


def test_bookrow_from_csv_dict_tolerates_missing_and_blank():
    back = store.BookRow.from_csv_dict({"title": "X"})
    assert back.title == "X"
    assert back.authors == []
    assert back.rating == ""


def test_highlightrow_csv_roundtrip():
    hl = store.HighlightRow(
        source="readwise",
        annotation_id="42",
        location="45-49",
        location_kind="page",
        text="Hello",
        tags=["war", "peace"],
        links=["Trotsky"],
    )
    d = hl.to_csv_dict()
    assert d["tags"] == "war;peace"
    assert d["links"] == "Trotsky"
    back = store.HighlightRow.from_csv_dict(d)
    assert back.tags == ["war", "peace"]
    assert back.links == ["Trotsky"]
    assert back.location_kind == "page"


def test_path_helpers(tmp_path):
    vault = tmp_path / "vault"
    assert store.data_dir(vault) == vault / "Data"
    assert store.sources_dir(vault) == vault / "Data" / "sources"
    assert store.layer_path(vault, "calibre") == vault / "Data" / "sources" / "calibre.csv"
    assert store.books_csv_path(vault) == vault / "Data" / "books.csv"
    assert store.highlights_dir(vault) == vault / "Data" / "Highlights"
    assert store.highlight_path(vault, "The Deluge - Adam Tooze") == (
        vault / "Data" / "Highlights" / "The Deluge - Adam Tooze.csv"
    )


def test_write_and_read_layer_roundtrip(tmp_path):
    vault = tmp_path / "vault"
    rows = [
        store.BookRow(title="The Deluge", authors=["Adam Tooze"], format="ebook"),
        store.BookRow(title="Stalin", authors=["Stephen Kotkin"], shelves=["read"]),
    ]
    store.write_layer(vault, "calibre", rows)
    assert store.layer_path(vault, "calibre").is_file()
    back = store.read_layer(vault, "calibre")
    assert [r.title for r in back] == ["The Deluge", "Stalin"]
    assert back[0].authors == ["Adam Tooze"]
    assert back[1].shelves == ["read"]


def test_read_layer_missing_returns_empty(tmp_path):
    assert store.read_layer(tmp_path / "vault", "goodreads") == []


def test_write_layer_overwrites_previous(tmp_path):
    vault = tmp_path / "vault"
    store.write_layer(vault, "calibre", [store.BookRow(title="A")])
    store.write_layer(vault, "calibre", [store.BookRow(title="B")])
    back = store.read_layer(vault, "calibre")
    assert [r.title for r in back] == ["B"]


def test_read_all_layers_returns_precedence_order(tmp_path):
    vault = tmp_path / "vault"
    store.write_layer(vault, "audible", [store.BookRow(title="Aud")])
    store.write_layer(vault, "calibre", [store.BookRow(title="Cal")])
    layers = store.read_all_layers(vault)
    assert list(layers.keys()) == [s for s in store.PRECEDENCE if s in layers]
    assert list(layers.keys())[0] == "calibre"  # lowest precedence first


def test_canonical_isbn_normalizes_isbn10_to_13():
    # 0141032189 (ISBN-10) == 9780141032184 (ISBN-13) for the same edition.
    assert store.canonical_isbn("0-14-103218-9") == store.canonical_isbn("9780141032184")
    assert store.canonical_isbn("") is None
    assert store.canonical_isbn(None) is None


def test_same_book_matches_on_isbn():
    a = store.BookRow(title="X", isbn="0-14-103218-9")
    b = store.BookRow(title="Totally Different", isbn="9780141032184")
    assert store.same_book(a, b) is True


def test_same_book_isbn_conflict_is_not_a_match():
    a = store.BookRow(title="X", authors=["A"], isbn="9780000000001")
    b = store.BookRow(title="X", authors=["A"], isbn="9780000000002")
    assert store.same_book(a, b) is False


def test_same_book_matches_on_amazon_when_no_isbn():
    a = store.BookRow(title="X", amazon="B00ABC")
    b = store.BookRow(title="Y", amazon="b00abc")
    assert store.same_book(a, b) is True


def test_same_book_fuzzy_title_author_fallback():
    a = store.BookRow(title="The Deluge: The Great War", authors=["Adam Tooze"])
    b = store.BookRow(title="The Deluge", authors=["Tooze, Adam"])
    assert store.same_book(a, b) is True


def test_same_book_different_titles_do_not_merge():
    a = store.BookRow(title="Stalin: Paradoxes of Power", authors=["Stephen Kotkin"])
    b = store.BookRow(title="Stalin: Waiting for Hitler", authors=["Stephen Kotkin"])
    assert store.same_book(a, b) is False
