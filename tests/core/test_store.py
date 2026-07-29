
from books.core import store
from books.core.highlights import Highlight
from books.renderers.obsidian import BookRef


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
    assert store.sources_dir(vault) == vault / "Data" / "Sources"
    assert store.layer_path(vault, "calibre") == vault / "Data" / "Sources" / "calibre.csv"
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


def test_same_book_bare_title_merges_with_subtitled_edition():
    a = store.BookRow(title="The Deluge: The Great War", authors=["Adam Tooze"])
    b = store.BookRow(title="The Deluge", authors=["Tooze, Adam"])
    assert store.same_book(a, b) is True


def test_same_book_distinct_subtitled_volumes_do_not_merge():
    a = store.BookRow(title="Stalin: Paradoxes of Power", authors=["Stephen Kotkin"])
    b = store.BookRow(title="Stalin: Waiting for Hitler", authors=["Stephen Kotkin"])
    assert store.same_book(a, b) is False


def test_same_book_bare_sequel_titles_do_not_merge():
    a = store.BookRow(title="Dune", authors=["Frank Herbert"])
    b = store.BookRow(title="Dune Messiah", authors=["Frank Herbert"])
    assert store.same_book(a, b) is False


def test_same_book_bare_title_merges_with_subtitled_same_book():
    a = store.BookRow(title="1984", authors=["George Orwell"])
    b = store.BookRow(title="1984: A Novel", authors=["George Orwell"])
    assert store.same_book(a, b) is True


def test_assign_book_id_basic_stem_drops_subtitle():
    used = set()
    bid = store.assign_book_id("The Deluge: The Great War", "Adam Tooze", used)
    assert bid == "The Deluge - Adam Tooze"


def test_assign_book_id_collision_restores_subtitle():
    used = set()
    first = store.assign_book_id("Stalin: Paradoxes of Power", "Stephen Kotkin", used)
    second = store.assign_book_id("Stalin: Waiting for Hitler, 1929-1941", "Stephen Kotkin", used)
    assert first == "Stalin - Stephen Kotkin"
    assert second == "Stalin, Waiting for Hitler, 1929-1941 - Stephen Kotkin"


def test_assign_book_id_numeric_suffix_last_resort():
    used = set()
    a = store.assign_book_id("Poems", "Anon", used)
    b = store.assign_book_id("Poems", "Anon", used)
    assert a == "Poems - Anon"
    assert b == "Poems - Anon (2)"


def test_assign_book_id_case_insensitive_collision_handling():
    """Stems differing only in case collide on case-insensitive filesystems."""
    used = set()
    first = store.assign_book_id("Poems", "Anon", used)
    # Second book with same stem but different case should get disambiguated
    second = store.assign_book_id("Poems", "anon", used)
    # The two book_ids should be different (case-insensitively)
    assert first.lower() != second.lower()
    # First gets the clean stem, second should get subtitle-restored or numeric suffix
    assert first == "Poems - Anon"
    # Since there's no subtitle, it falls to numeric suffix
    assert second == "Poems - anon (2)"


def test_coalesce_higher_precedence_wins_and_fills_blanks():
    members = [
        ("goodreads", store.BookRow(title="X", format="ebook", rating="4")),
        ("audible", store.BookRow(title="X", format="audiobook")),
    ]
    merged = store.coalesce(members)
    assert merged.format == "audiobook"   # audible > goodreads
    assert merged.rating == "4"           # only goodreads had it


def test_coalesce_is_order_independent():
    m1 = [
        ("audible", store.BookRow(title="X", format="audiobook")),
        ("goodreads", store.BookRow(title="X", format="ebook")),
    ]
    m2 = list(reversed(m1))
    assert store.coalesce(m1).format == "audiobook"
    assert store.coalesce(m2).format == "audiobook"


def test_coalesce_merges_list_fields_by_precedence():
    members = [
        ("calibre", store.BookRow(title="X", shelves=["a"])),
        ("goodreads", store.BookRow(title="X", shelves=["b", "c"])),
    ]
    # goodreads outranks calibre and has a non-empty list -> it wins wholesale
    assert store.coalesce(members).shelves == ["b", "c"]


def test_merge_clusters_across_layers_and_assigns_book_id(tmp_path):
    vault = tmp_path / "vault"
    store.write_layer(vault, "calibre", [
        store.BookRow(title="The Deluge", authors=["Adam Tooze"], format="ebook",
                      isbn="9780141032184"),
    ])
    store.write_layer(vault, "audible", [
        store.BookRow(title="The Deluge", authors=["Adam Tooze"], format="audiobook",
                      isbn="0-14-103218-9"),  # same edition, ISBN-10 form
    ])
    catalog = store.merge(vault)
    assert len(catalog) == 1
    book = catalog[0]
    assert book.book_id == "The Deluge - Adam Tooze"
    assert book.format == "audiobook"           # audible wins format
    assert store.books_csv_path(vault).is_file()


def test_merge_is_order_independent(tmp_path):
    """Clustering and coalesce are deterministic regardless of row order within layers."""
    # Multiple books, some matching (should cluster), some distinct
    books = [
        store.BookRow(title="Dune", authors=["Frank Herbert"], format="ebook", isbn="111"),
        store.BookRow(title="Dune", authors=["Herbert, Frank"], format="audiobook"),  # matches
        store.BookRow(title="1984", authors=["George Orwell"], format="ebook"),
        store.BookRow(title="Foundation", authors=["Isaac Asimov"], format="ebook", isbn="222"),
    ]
    # Write in two different orders
    vault1 = tmp_path / "v1"
    store.write_layer(vault1, "calibre", [books[0], books[2], books[3]])
    store.write_layer(vault1, "audible", [books[1]])  # matching Dune row
    cat1 = store.merge(vault1)

    vault2 = tmp_path / "v2"
    # Reverse order within calibre layer
    store.write_layer(vault2, "calibre", [books[3], books[2], books[0]])
    store.write_layer(vault2, "audible", [books[1]])
    cat2 = store.merge(vault2)

    # Same clustering: 3 books (Dune merged, 1984, Foundation separate)
    assert len(cat1) == 3
    assert len(cat2) == 3
    # Same book_ids (order may vary, so compare as sets)
    ids1 = {b.book_id for b in cat1}
    ids2 = {b.book_id for b in cat2}
    assert ids1 == ids2
    # Same coalesced values
    by_id1 = {b.book_id: b.format for b in cat1}
    by_id2 = {b.book_id: b.format for b in cat2}
    assert by_id1 == by_id2
    # audible wins format for the merged Dune (author form from audible row)
    dune_id = [bid for bid in ids1 if bid.startswith("Dune -")][0]
    assert by_id1[dune_id] == "audiobook"


def test_merge_read_books_csv_roundtrip(tmp_path):
    vault = tmp_path / "vault"
    store.write_layer(vault, "calibre",
                      [store.BookRow(title="X", authors=["A"], shelves=["read"])])
    store.merge(vault)
    rows = store.read_books_csv(vault)
    assert rows[0].book_id == "X - A"
    assert rows[0].shelves == ["read"]


def test_merge_book_id_assignment_is_stable_across_row_order(tmp_path):
    """book_id assignment must be deterministic regardless of layer row order.

    Two distinct same-clean-stem books (no ISBN/Amazon) should get the same
    book_ids in both runs, preventing highlight-file orphaning on re-export.
    """
    # Two distinct Stalin volumes, same clean stem, no ISBN/Amazon
    paradoxes = store.BookRow(
        title="Stalin: Paradoxes of Power",
        authors=["Stephen Kotkin"],
        format="ebook",
    )
    waiting = store.BookRow(
        title="Stalin: Waiting for Hitler",
        authors=["Stephen Kotkin"],
        format="ebook",
    )

    # First run: paradoxes before waiting
    vault1 = tmp_path / "v1"
    store.write_layer(vault1, "calibre", [paradoxes, waiting])
    cat1 = store.merge(vault1)
    by_title1 = {b.title: b.book_id for b in cat1}

    # Second run: waiting before paradoxes (OPPOSITE order)
    vault2 = tmp_path / "v2"
    store.write_layer(vault2, "calibre", [waiting, paradoxes])
    cat2 = store.merge(vault2)
    by_title2 = {b.title: b.book_id for b in cat2}

    # CRITICAL: same title -> same book_id in both runs
    assert by_title1["Stalin: Paradoxes of Power"] == by_title2["Stalin: Paradoxes of Power"]
    assert by_title1["Stalin: Waiting for Hitler"] == by_title2["Stalin: Waiting for Hitler"]

    # The two book_ids must be distinct (one bare stem, one disambiguated)
    assert by_title1["Stalin: Paradoxes of Power"] != by_title1["Stalin: Waiting for Hitler"]


def test_catalog_find_by_isbn_amazon_and_title_author(tmp_path):
    vault = tmp_path / "vault"
    store.write_layer(vault, "calibre", [
        store.BookRow(title="The Deluge", authors=["Adam Tooze"],
                      isbn="9780141032184", amazon="B00DELUGE"),
    ])
    store.merge(vault)
    cat = store.Catalog(vault)

    assert cat.find(BookRef(title="whatever", isbn="0-14-103218-9")) == \
        "The Deluge - Adam Tooze"
    assert cat.find(BookRef(title="whatever", amazon="b00deluge")) == \
        "The Deluge - Adam Tooze"
    assert cat.find(BookRef(title="The Deluge", authors=["Tooze, Adam"])) == \
        "The Deluge - Adam Tooze"
    assert cat.find(BookRef(title="Nonexistent", authors=["Nobody"])) is None


def test_catalog_find_fuzzy_title(tmp_path):
    vault = tmp_path / "vault"
    store.write_layer(vault, "calibre",
                      [store.BookRow(title="The Deluge: The Great War", authors=["Adam Tooze"])])
    store.merge(vault)
    cat = store.Catalog(vault)
    assert cat.find(BookRef(title="The Deluge", authors=["Adam Tooze"])) == \
        "The Deluge - Adam Tooze"


def test_highlight_to_row_percent():
    h = Highlight(text="t", progress=0.42, chapter_index=3, chapter_title="Ch",
                  tags=["war"], links=["Trotsky"], note="n", date="2020")
    row = store.highlight_to_row(h, "kobo", "a1")
    assert row.source == "kobo"
    assert row.annotation_id == "a1"
    assert row.location == "42"
    assert row.location_kind == "percent"
    assert row.chapter_index == "3"
    assert row.tags == ["war"]


def test_highlight_to_row_page_and_kindle_and_timestamp():
    page = store.highlight_to_row(Highlight(text="t", page="45-49"), "highlighted", "1")
    assert (page.location, page.location_kind) == ("45-49", "page")

    kindle = store.highlight_to_row(
        Highlight(text="t", page="1234", location_label="loc."), "readwise", "2")
    assert (kindle.location, kindle.location_kind) == ("1234", "kindle_loc")

    ts = store.highlight_to_row(
        Highlight(text="t", page="3:24:15", location_label=""), "audible", "3")
    assert (ts.location, ts.location_kind) == ("3:24:15", "timestamp")


def test_row_to_highlight_reverses_each_kind():
    for kind, loc, want in [
        ("percent", "42", ("progress", 0.42)),
        ("page", "45-49", ("page", "45-49")),
        ("kindle_loc", "1234", ("location_label", "loc.")),
        ("timestamp", "3:24:15", ("location_label", "")),
    ]:
        row = store.HighlightRow(text="t", location=loc, location_kind=kind)
        h = store.row_to_highlight(row)
        attr, value = want
        assert getattr(h, attr) == value


def test_row_to_highlight_handles_malformed_numeric_fields():
    """Non-numeric location/chapter_index fall back to None instead of crashing."""
    row = store.HighlightRow(
        text="t",
        location="not-a-number",
        location_kind="percent",
        chapter_index="also-not-a-number",
    )
    h = store.row_to_highlight(row)
    assert h.progress is None
    assert h.chapter_index is None
    assert h.text == "t"


def test_write_and_read_highlights_roundtrip(tmp_path):
    vault = tmp_path / "vault"
    bid = "The Deluge - Adam Tooze"
    rows = [
        store.HighlightRow(source="kobo", annotation_id="1", text="a",
                           location="10", location_kind="percent"),
        store.HighlightRow(source="kobo", annotation_id="2", text="b",
                           location="20", location_kind="percent"),
    ]
    store.write_highlights(vault, bid, "kobo", rows)
    back = store.read_highlights(vault, bid)
    assert [r.text for r in back] == ["a", "b"]


def test_write_highlights_replaces_only_its_own_source(tmp_path):
    vault = tmp_path / "vault"
    bid = "X - A"
    store.write_highlights(vault, bid, "kobo",
                           [store.HighlightRow(source="kobo", annotation_id="1", text="kobo1")])
    store.write_highlights(vault, bid, "readwise",
                           [store.HighlightRow(source="readwise", annotation_id="1", text="rw1")])
    # re-run kobo with new content: only kobo rows replaced, readwise preserved
    store.write_highlights(vault, bid, "kobo",
                           [store.HighlightRow(source="kobo", annotation_id="1", text="kobo2")])
    back = store.read_highlights(vault, bid)
    texts = {(r.source, r.text) for r in back}
    assert texts == {("kobo", "kobo2"), ("readwise", "rw1")}


def test_read_highlights_missing_returns_empty(tmp_path):
    assert store.read_highlights(tmp_path / "vault", "Nope - Nobody") == []


def test_row_to_highlight_sets_source():
    row = store.HighlightRow(source="readwise", text="t",
                             location="42", location_kind="percent")
    h = store.row_to_highlight(row)
    assert h.source == "readwise"
