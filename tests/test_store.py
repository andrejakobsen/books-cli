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
