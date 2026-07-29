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
