"""Tests for the `books covers` capability (books.commands.covers)."""

from pathlib import Path

from books.commands import covers
from books.core import store


def _seed_catalog(vault, rows):
    """Write books.csv with the given BookRows (each needs a book_id)."""
    store.write_books_csv(vault, rows)


def test_books_missing_cover_selects_blank_and_no_disk_file(tmp_path):
    _seed_catalog(
        tmp_path,
        [
            store.BookRow(
                book_id="A - Ann", title="A", authors=["Ann"], isbn="111", amazon="B001", cover=""
            ),  # blank -> included
            store.BookRow(
                book_id="B - Bee", title="B", authors=["Bee"], cover="Data/Sources/_covers/x.jpg"
            ),  # has cover -> excluded
            store.BookRow(book_id="C - Cee", title="C", authors=["Cee"]),  # blank -> included
        ],
    )
    # C already has a materialized on-disk cover -> excluded despite blank field
    disk = tmp_path / "Data" / "Covers"
    disk.mkdir(parents=True)
    (disk / "C - Cee.jpg").write_bytes(b"img")

    missing = covers.books_missing_cover(tmp_path)
    ids = sorted(m.book_id for m in missing)
    assert ids == ["A - Ann"]
    a = next(m for m in missing if m.book_id == "A - Ann")
    assert a.title == "A" and a.authors == ["Ann"]
    assert a.isbn == "111" and a.amazon == "B001"


def test_books_missing_cover_no_catalog_returns_empty(tmp_path):
    assert covers.books_missing_cover(tmp_path) == []


def test_dataclasses_exist():
    mb = covers.MissingBook(
        book_id="A - Ann",
        title="A Title",
        authors=["An Author"],
        isbn="123",
        amazon="B00XYZ",
    )
    assert mb.book_id == "A - Ann"
    assert mb.title == "A Title"
    assert mb.authors == ["An Author"]

    c = covers.Candidate(
        source="google",
        label="A Title — An Author",
        image_url="https://x/y.jpg",
        fmt=None,
    )
    assert c.source == "google"
    assert c.fmt is None


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


# iTunes Search API shape: results[] with artworkUrl100 (size token = last
# path segment; ISBN, when present, is the second-to-last segment's stem).
ITUNES_RESULTS = {
    "results": [
        {
            "trackName": "The Deluge",
            "artistName": "Adam Tooze",
            "artworkUrl100": (
                "https://is1-ssl.mzstatic.com/image/thumb/Pub3/v4/57/c1/ac/"
                "abc/9780241006115.jpg/100x100bb.jpg"
            ),
        }
    ]
}

# artwork with an opaque (non-ISBN) filename stem -> no ISBN to backfill
ITUNES_RESULTS_NO_ISBN = {
    "results": [
        {
            "collectionName": "The Anatomy of Fascism",
            "artistName": "Robert O. Paxton",
            "artworkUrl100": (
                "https://is1-ssl.mzstatic.com/image/thumb/Publication/52/22/e8/"
                "mzi.mwffatop.jpg/100x100bb.jpg"
            ),
        }
    ]
}


def test_itunes_artwork_upgrades_size_token():
    art = (
        "https://is1-ssl.mzstatic.com/image/thumb/Pub3/v4/57/c1/ac/"
        "abc/9780241006115.jpg/100x100bb.jpg"
    )
    big = covers._itunes_artwork(art)
    assert big.endswith("/9780241006115.jpg/1400x1400bb.jpg")
    assert "100x100bb" not in big


def test_itunes_isbn_reads_second_to_last_segment():
    art = (
        "https://is1-ssl.mzstatic.com/image/thumb/Pub3/v4/57/c1/ac/"
        "abc/9780241006115.jpg/100x100bb.jpg"
    )
    assert covers._itunes_isbn(art) == "9780241006115"


def test_itunes_isbn_none_for_opaque_stem():
    art = (
        "https://is1-ssl.mzstatic.com/image/thumb/Publication/52/22/e8/"
        "mzi.mwffatop.jpg/100x100bb.jpg"
    )
    assert covers._itunes_isbn(art) is None


def test_itunes_isbn_reads_isbn10_with_x_check_digit():
    art = (
        "https://is1-ssl.mzstatic.com/image/thumb/Pub3/v4/57/c1/ac/abc/184737453X.jpg/100x100bb.jpg"
    )
    assert covers._itunes_isbn(art) == "184737453X"


def test_itunes_isbn_reads_isbn10_all_digits():
    art = (
        "https://is1-ssl.mzstatic.com/image/thumb/Pub3/v4/57/c1/ac/abc/0241006112.jpg/100x100bb.jpg"
    )
    assert covers._itunes_isbn(art) == "0241006112"


def test_itunes_isbn_none_for_short_url():
    assert covers._itunes_isbn("9780241006115.jpg") is None


def test_normalize_author_collapses_whitespace():
    assert covers.normalize_author("James   Barr") == "James Barr"
    assert covers.normalize_author("  Andrew  Roberts ") == "Andrew Roberts"


def test_normalize_author_strips_translator_and_coauthor_tails():
    # translator merged into the author string
    assert covers.normalize_author("Plato and Benjamin Jowett") == "Plato"
    assert covers.normalize_author("Homer, translated by Emily Wilson") == "Homer"
    assert covers.normalize_author("Tolstoy with Louise Maude") == "Tolstoy"


def test_normalize_author_leaves_simple_names():
    assert covers.normalize_author("Adam Tooze") == "Adam Tooze"
    assert covers.normalize_author("") == ""


def test_google_query_uses_normalized_author():
    book = covers.MissingBook(
        book_id="x",
        title="The  Republic",
        authors=["Plato and Benjamin Jowett"],
        isbn=None,
        amazon=None,
    )
    captured = {}

    def fake_fetch(url):
        captured["url"] = url
        return {"items": []}

    covers.google_books_candidates(book, fake_fetch)
    # translator tail dropped, whitespace collapsed
    assert "Benjamin" not in captured["url"]
    assert "inauthor:Plato" in captured["url"]
    assert "The%20Republic" in captured["url"] or "The+Republic" in captured["url"]


def test_openlibrary_query_uses_normalized_author():
    book = covers.MissingBook(
        book_id="x", title="X", authors=["James   Barr"], isbn=None, amazon=None
    )
    captured = {}

    def fake_fetch(url):
        captured.setdefault("urls", []).append(url)
        return {"docs": []}

    covers.openlibrary_candidates(book, fake_fetch)
    search_url = next(u for u in captured["urls"] if "search.json" in u)
    assert "James+Barr" in search_url or "James%20Barr" in search_url
    assert "James++" not in search_url and "James%20%20" not in search_url


def test_google_books_prefers_largest_and_upgrades_url():
    book = covers.MissingBook(
        book_id="x", title="The Deluge", authors=["Adam Tooze"], isbn=None, amazon=None
    )
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
    assert c.image_url.startswith("https://")  # http -> https
    assert "zoom=3" in c.image_url
    # title/author query when no ISBN
    assert "intitle" in captured["url"]
    assert "inauthor" in captured["url"]


def test_google_books_captures_isbn13_from_identifiers():
    data = {
        "items": [
            {
                "volumeInfo": {
                    "title": "The Deluge",
                    "authors": ["Adam Tooze"],
                    "industryIdentifiers": [
                        {"type": "ISBN_10", "identifier": "0141032189"},
                        {"type": "ISBN_13", "identifier": "9780141032184"},
                    ],
                    "imageLinks": {"thumbnail": "http://x/y?zoom=1"},
                }
            }
        ]
    }
    book = covers.MissingBook(
        book_id="x", title="The Deluge", authors=["Adam Tooze"], isbn=None, amazon=None
    )
    cands = covers.google_books_candidates(book, lambda url: data)
    assert cands[0].isbn == "9780141032184"  # ISBN_13 preferred over ISBN_10


def test_google_books_uses_isbn_query_when_present():
    book = covers.MissingBook(book_id="x", title="X", authors=[], isbn="9780141032016", amazon=None)
    captured = {}

    def fake_fetch(url):
        captured["url"] = url
        return {"items": []}

    covers.google_books_candidates(book, fake_fetch)
    assert "isbn:9780141032016" in captured["url"]


def test_google_books_strips_edge_curl_when_only_thumbnail():
    book = covers.MissingBook(book_id="x", title="X", authors=[], isbn=None, amazon=None)
    data = {
        "items": [
            {
                "volumeInfo": {
                    "title": "X",
                    "imageLinks": {"thumbnail": "http://books.google.com/x?zoom=1&edge=curl"},
                }
            }
        ]
    }
    cands = covers.google_books_candidates(book, lambda url: data)
    assert cands and "edge=curl" not in cands[0].image_url
    assert cands[0].image_url.startswith("https://")


def test_google_books_no_images_returns_empty():
    book = covers.MissingBook(book_id="x", title="X", authors=[], isbn=None, amazon=None)
    cands = covers.google_books_candidates(
        book, lambda url: {"items": [{"volumeInfo": {"title": "X"}}]}
    )
    assert cands == []


# Open Library search.json shape (title/author path): yields a work key.
OL_SEARCH = {"docs": [{"key": "/works/OL1W", "cover_i": 999}]}

# Open Library works/<id>/editions.json shape: per-edition format + covers.
OL_EDITIONS = {
    "entries": [
        {"physical_format": "Hardcover", "covers": [111]},
        {"physical_format": "Paperback", "covers": [222]},
    ]
}


def test_openlibrary_title_author_paperback_first():
    book = covers.MissingBook(
        book_id="x", title="Napoleon", authors=["Andrew Roberts"], isbn=None, amazon=None
    )
    captured = {}

    def fake_fetch(url):
        captured.setdefault("urls", []).append(url)
        if "editions.json" in url:
            return OL_EDITIONS
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
    urls = captured["urls"]
    search_url = next(u for u in urls if "search.json" in u)
    assert "title=Napoleon" in search_url
    assert "author=Andrew+Roberts" in search_url or "author=Andrew%20Roberts" in search_url
    assert any("/works/OL1W/editions.json" in u for u in urls)


def test_openlibrary_falls_back_to_search_cover_when_no_editions():
    book = covers.MissingBook(
        book_id="x", title="Napoleon", authors=["Andrew Roberts"], isbn=None, amazon=None
    )

    def fake_fetch(url):
        if "editions.json" in url:
            return {"entries": []}
        return OL_SEARCH

    cands = covers.openlibrary_candidates(book, fake_fetch)
    assert len(cands) == 1
    assert cands[0].fmt is None
    assert "999-L.jpg" in cands[0].image_url


def test_openlibrary_isbn_path_builds_isbn_cover_url():
    book = covers.MissingBook(book_id="x", title="X", authors=[], isbn="9780141032016", amazon=None)
    captured = {}

    def fake_fetch(url):
        captured["url"] = url
        return {"physical_format": "Paperback"}

    cands = covers.openlibrary_candidates(book, fake_fetch)
    assert "/isbn/9780141032016.json" in captured["url"]
    assert cands and "isbn/9780141032016-L.jpg" in cands[0].image_url
    assert cands[0].fmt == "paperback"


def test_openlibrary_no_cover_returns_empty():
    book = covers.MissingBook(book_id="x", title="X", authors=[], isbn=None, amazon=None)
    cands = covers.openlibrary_candidates(book, lambda url: {"docs": []})
    assert cands == []


def test_amazon_candidate_from_asin():
    book = covers.MissingBook(book_id="x", title="X", authors=["Y"], isbn=None, amazon="B00ABCDEFG")
    cands = covers.amazon_candidates(book)
    assert len(cands) == 1
    assert cands[0].source == "amazon"
    assert "B00ABCDEFG" in cands[0].image_url


def test_amazon_no_asin_returns_empty():
    book = covers.MissingBook(book_id="x", title="X", authors=[], isbn=None, amazon=None)
    assert covers.amazon_candidates(book) == []


def _http_error(code):
    from urllib.error import HTTPError

    return HTTPError("http://x", code, "err", {}, None)


def test_fetch_with_retry_retries_on_429_then_succeeds():
    calls = {"n": 0}
    slept = []

    def do():
        calls["n"] += 1
        if calls["n"] < 3:
            raise _http_error(429)
        return {"ok": True}

    out = covers.fetch_with_retry(do, retries=3, backoff=0.1, sleep=slept.append)
    assert out == {"ok": True}
    assert calls["n"] == 3
    assert len(slept) == 2  # two backoff sleeps before the successful third call


def test_fetch_with_retry_retries_on_403_itunes_throttle():
    # iTunes returns 403 (not 429) when it throttles, so 403 must be retryable.
    calls = {"n": 0}
    slept = []

    def do():
        calls["n"] += 1
        if calls["n"] < 3:
            raise _http_error(403)
        return {"ok": True}

    out = covers.fetch_with_retry(do, retries=3, backoff=0.1, sleep=slept.append)
    assert out == {"ok": True}
    assert calls["n"] == 3
    assert len(slept) == 2


def test_fetch_with_retry_gives_up_after_time_budget():
    # A source that keeps throttling is abandoned once the next backoff would push
    # past the per-source time budget, so the run moves on to the next source.
    calls = {"n": 0}
    now = {"t": 0.0}

    def clock():
        return now["t"]

    def sleep(seconds):
        now["t"] += seconds  # simulate wall-clock passing during backoff

    def do():
        calls["n"] += 1
        raise _http_error(429)

    from urllib.error import HTTPError

    import pytest

    with pytest.raises(HTTPError):
        covers.fetch_with_retry(
            do, retries=100, backoff=1.0, max_seconds=60, sleep=sleep, clock=clock
        )

    # Backoffs 1,2,4,8,16,32 accumulate to 31s of sleeps over 6 attempts; the next
    # (32s) delay would reach 63s >= 60, so it stops at 6 attempts.
    assert calls["n"] == 6
    assert now["t"] == 31.0


def test_fetch_with_retry_does_not_retry_on_404():
    calls = {"n": 0}

    def do():
        calls["n"] += 1
        raise _http_error(404)

    from urllib.error import HTTPError

    import pytest

    with pytest.raises(HTTPError):
        covers.fetch_with_retry(do, retries=3, backoff=0.1, sleep=lambda s: None)
    assert calls["n"] == 1  # 404 is not retryable


def test_fetch_with_retry_exhausts_and_raises():
    from urllib.error import HTTPError

    calls = {"n": 0}

    def do():
        calls["n"] += 1
        raise _http_error(503)

    import pytest

    with pytest.raises(HTTPError):
        covers.fetch_with_retry(do, retries=2, backoff=0.1, sleep=lambda s: None)
    assert calls["n"] == 2  # tried exactly `retries` times


def test_gather_with_errors_reports_failing_source():
    book = covers.MissingBook(book_id="x", title="X", authors=["Y"], isbn=None, amazon="B00ABCDEFG")

    def fetch_json(url):
        if "googleapis" in url:
            raise _http_error(429)  # google source fails entirely
        return {"docs": []}  # openlibrary finds nothing (not an error)

    cands, errored = covers.gather_with_errors(book, fetch_json)
    assert "google" in errored
    assert "openlibrary" not in errored
    # amazon still contributes despite google failing
    assert any(c.source == "amazon" for c in cands)


def test_gather_candidates_source_order():
    book = covers.MissingBook(
        book_id="x", title="Napoleon", authors=["Andrew Roberts"], isbn=None, amazon="B00ABCDEFG"
    )

    def fake_fetch(url):
        if "googleapis" in url:
            return GOOGLE_VOLUME
        if "editions.json" in url:
            return OL_EDITIONS
        return OL_SEARCH

    cands = covers.gather_candidates(book, fake_fetch)
    sources = [c.source for c in cands]
    assert sources[0] == "google"
    assert "openlibrary" in sources
    assert sources[-1] == "amazon"
    # google before every openlibrary before amazon
    assert sources.index("google") < sources.index("openlibrary") < sources.index("amazon")


def _png(width: int, height: int) -> bytes:
    """A byte string with a valid PNG signature + IHDR width/height."""
    return (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + b"\x08\x06\x00\x00\x00"
        + b"x" * 2000
    )


def _gif(width: int, height: int) -> bytes:
    return b"GIF89a" + width.to_bytes(2, "little") + height.to_bytes(2, "little") + b"x" * 2000


def test_image_dimensions_png_gif_and_unknown():
    assert covers.image_dimensions(_png(200, 300)) == (200, 300)
    assert covers.image_dimensions(_gif(120, 160)) == (120, 160)
    assert covers.image_dimensions(b"x" * 5000) is None  # not a recognizable image


def test_is_valid_image():
    assert covers.is_valid_image(b"x" * 5000, "image/jpeg") is True
    assert covers.is_valid_image(b"x" * 5000, "text/html") is False  # wrong type
    assert covers.is_valid_image(b"x" * 10, "image/gif") is False  # too small
    assert covers.is_valid_image(b"x" * 5000, None) is False  # unknown type


def test_is_valid_image_rejects_tiny_dimensions():
    # a real but tiny placeholder image is rejected even though it is large enough in bytes
    assert covers.is_valid_image(_png(1, 1), "image/png") is False
    # a properly sized image passes
    assert covers.is_valid_image(_png(200, 300), "image/png") is True
    # a big-enough GIF passes; a 10x10 one does not
    assert covers.is_valid_image(_gif(300, 400), "image/gif") is True
    assert covers.is_valid_image(_gif(10, 10), "image/gif") is False


def _cand(source):
    return covers.Candidate(source=source, label="L", image_url=f"http://{source}", fmt=None)


def test_pick_cover_auto_first_valid():
    cands = [_cand("google"), _cand("openlibrary")]

    def fetch_bytes(url):
        if url.endswith("google"):
            return (b"x" * 5, "image/jpeg")  # too small -> invalid
        return (b"x" * 5000, "image/jpeg")  # valid

    picked = covers.pick_cover(cands, fetch_bytes, interactive=False, prompt=None)
    assert picked is not None
    cand, data = picked
    assert cand.source == "openlibrary"
    assert data == b"x" * 5000


def test_pick_cover_auto_none_when_all_invalid():
    cands = [_cand("google")]
    picked = covers.pick_cover(
        cands, lambda url: (b"", "text/html"), interactive=False, prompt=None
    )
    assert picked is None


def test_pick_cover_interactive_next_then_accept():
    cands = [_cand("google"), _cand("openlibrary")]
    answers = iter(["next", "accept"])

    def fetch_bytes(url):
        return (b"x" * 5000, "image/jpeg")

    picked = covers.pick_cover(cands, fetch_bytes, interactive=True, prompt=lambda c: next(answers))
    assert picked[0].source == "openlibrary"


def test_pick_cover_interactive_quit_raises():
    cands = [_cand("google")]
    import pytest

    with pytest.raises(covers.QuitRequested):
        covers.pick_cover(
            cands,
            lambda url: (b"x" * 5000, "image/jpeg"),
            interactive=True,
            prompt=lambda c: "quit",
        )


def test_terminal_prompt_maps_keys(monkeypatch):
    # Invalid input re-asks (Rich validated choice) before a valid key is given.
    answers = iter(["y", "n", "s", "?", "q"])
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))
    cand = _cand("google")
    assert covers._terminal_prompt(cand) == "accept"
    assert covers._terminal_prompt(cand) == "next"
    assert covers._terminal_prompt(cand) == "skip"
    # "?" is rejected and re-asked, then "q" -> quit
    assert covers._terminal_prompt(cand) == "quit"


def _google_volume_with_isbn(isbn):
    return {
        "items": [
            {
                "volumeInfo": {
                    "title": "T",
                    "authors": ["Ann"],
                    "industryIdentifiers": [{"type": "ISBN_13", "identifier": isbn}],
                    "imageLinks": {"thumbnail": "http://x/y?zoom=1"},
                }
            }
        ]
    }


def test_run_stages_image_and_writes_covers_layer(tmp_path):
    _seed_catalog(
        tmp_path,
        [
            store.BookRow(book_id="A - Ann", title="A", authors=["Ann"]),
        ],
    )

    def fetch_json(url):
        return GOOGLE_VOLUME if "googleapis" in url else {"docs": []}

    stats = covers.run(
        tmp_path,
        interactive=False,
        dry_run=False,
        limit=None,
        fetch_json=fetch_json,
        fetch_bytes=lambda url: (_png(200, 300), "image/jpeg"),
        prompt=None,
    )

    assert stats["missing"] == 1 and stats["fetched"] == 1
    assert stats["by_source"]["google"] == 1
    staged = tmp_path / "Data" / "Sources" / "_covers" / "covers" / "A - Ann.jpg"
    assert staged.is_file()
    rows = store.read_layer(tmp_path, "covers")
    assert len(rows) == 1
    assert rows[0].cover == "Data/Sources/_covers/covers/A - Ann.jpg"
    assert rows[0].title == "A" and rows[0].authors == ["Ann"]


def test_run_records_learned_isbn_in_layer(tmp_path):
    _seed_catalog(
        tmp_path,
        [
            store.BookRow(book_id="A - Ann", title="A", authors=["Ann"], isbn=""),
        ],
    )
    volume = _google_volume_with_isbn("9780141032184")
    covers.run(
        tmp_path,
        interactive=False,
        dry_run=False,
        limit=None,
        fetch_json=lambda url: volume if "googleapis" in url else {"docs": []},
        fetch_bytes=lambda url: (_png(200, 300), "image/jpeg"),
        prompt=None,
    )
    rows = store.read_layer(tmp_path, "covers")
    assert rows[0].isbn == "9780141032184"


def test_run_dry_run_writes_nothing(tmp_path):
    _seed_catalog(tmp_path, [store.BookRow(book_id="A - Ann", title="A", authors=["Ann"])])
    stats = covers.run(
        tmp_path,
        interactive=False,
        dry_run=True,
        limit=None,
        fetch_json=lambda url: GOOGLE_VOLUME,
        fetch_bytes=lambda url: (_png(200, 300), "image/jpeg"),
        prompt=None,
    )
    assert stats["fetched"] == 1  # would-fetch still counted
    assert not (tmp_path / "Data" / "Sources" / "_covers").exists()
    assert store.read_layer(tmp_path, "covers") == []


def test_run_limit_preserves_existing_layer_rows(tmp_path):
    _seed_catalog(
        tmp_path,
        [
            store.BookRow(book_id="A - Ann", title="A", authors=["Ann"]),
            store.BookRow(book_id="B - Bee", title="B", authors=["Bee"]),
        ],
    )
    store.write_layer(
        tmp_path,
        "covers",
        [
            store.BookRow(
                title="Z", authors=["Zed"], cover="Data/Sources/_covers/covers/Z - Zed.jpg"
            )
        ],
    )

    covers.run(
        tmp_path,
        interactive=False,
        dry_run=False,
        limit=1,
        fetch_json=lambda url: GOOGLE_VOLUME if "googleapis" in url else {"docs": []},
        fetch_bytes=lambda url: (_png(200, 300), "image/jpeg"),
        prompt=None,
    )

    stems = sorted(Path(r.cover).stem for r in store.read_layer(tmp_path, "covers"))
    assert "Z - Zed" in stems  # prior row preserved
    assert "A - Ann" in stems  # newly staged
    assert len(stems) == 2  # limit=1 processed one new book


def test_run_counts_errored_sources(tmp_path):
    _seed_catalog(
        tmp_path,
        [
            store.BookRow(book_id="X - Y", title="X", authors=["Y"], amazon="B00ABCDEFG"),
        ],
    )

    def fetch_json(url):
        if "googleapis" in url:
            raise _http_error(429)
        return {"docs": []}

    stats = covers.run(
        tmp_path,
        interactive=False,
        dry_run=True,
        limit=None,
        fetch_json=fetch_json,
        fetch_bytes=lambda url: (_png(200, 300), "image/jpeg"),
        prompt=None,
    )
    assert stats["errored"]["google"] == 1
    assert stats["fetched"] == 1  # amazon still succeeded


def test_run_single_book_only_processes_that_book(tmp_path):
    _seed_catalog(
        tmp_path,
        [
            store.BookRow(book_id="A - Ann", title="A", authors=["Ann"]),
            store.BookRow(book_id="B - Bee", title="B", authors=["Bee"]),
        ],
    )
    covers.run(
        tmp_path,
        interactive=False,
        dry_run=False,
        limit=None,
        fetch_json=lambda url: GOOGLE_VOLUME if "googleapis" in url else {"docs": []},
        fetch_bytes=lambda url: (_png(200, 300), "image/jpeg"),
        prompt=None,
        book_id="A - Ann",
    )
    stems = [Path(r.cover).stem for r in store.read_layer(tmp_path, "covers")]
    assert stems == ["A - Ann"]


def test_cli_covers_dry_run(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from books.cli import app

    _seed_catalog(tmp_path, [store.BookRow(book_id="A - Ann", title="A", authors=["Ann"])])
    monkeypatch.setattr(covers.command, "default_fetch_json", lambda url: GOOGLE_VOLUME)
    monkeypatch.setattr(
        covers.command, "default_fetch_bytes", lambda url: (_png(200, 300), "image/jpeg")
    )

    result = CliRunner().invoke(app, ["covers", "-o", str(tmp_path), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "missing" in result.output.lower()
    assert store.read_layer(tmp_path, "covers") == []


def test_cli_covers_errors_without_catalog(tmp_path):
    from typer.testing import CliRunner

    from books.cli import app

    result = CliRunner().invoke(app, ["covers", "-o", str(tmp_path)])
    assert result.exit_code != 0
    assert "books.csv" in result.output.lower()


def test_cli_covers_single_book_by_id(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from books.cli import app

    _seed_catalog(
        tmp_path,
        [
            store.BookRow(book_id="A - Ann", title="A", authors=["Ann"]),
            store.BookRow(book_id="B - Bee", title="B", authors=["Bee"]),
        ],
    )
    monkeypatch.setattr(
        covers.command,
        "default_fetch_json",
        lambda url: GOOGLE_VOLUME if "googleapis" in url else {"docs": []},
    )
    monkeypatch.setattr(
        covers.command, "default_fetch_bytes", lambda url: (_png(200, 300), "image/jpeg")
    )
    monkeypatch.setattr(covers.command, "_terminal_prompt", lambda c: "accept")

    result = CliRunner().invoke(app, ["covers", "-o", str(tmp_path), "-b", "A - Ann"])
    assert result.exit_code == 0, result.output
    stems = [Path(r.cover).stem for r in store.read_layer(tmp_path, "covers")]
    assert stems == ["A - Ann"]


def test_cli_covers_registered():
    from books.cli import app

    names = {c.name for c in app.registered_commands}
    assert "covers" in names


def test_apple_books_query_uses_title_and_author_not_isbn():
    book = covers.MissingBook(
        book_id="x", title="The  Deluge", authors=["Adam Tooze"], isbn="9781847374530", amazon=None
    )
    captured = {}

    def fake_fetch(url):
        captured["url"] = url
        return {"results": []}

    covers.apple_books_candidates(book, fake_fetch)
    url = captured["url"]
    assert "Deluge" in url and "Adam" in url and "Tooze" in url
    assert "The%20%20Deluge" not in url  # collapsed, not doubled
    assert "isbn" not in url.lower()
    assert "9781847374530" not in url
    assert "entity=ebook" in url
    assert "country=gb" in url


def test_apple_books_builds_candidate_with_hires_url_and_isbn():
    book = covers.MissingBook(
        book_id="x", title="The Deluge", authors=["Adam Tooze"], isbn=None, amazon=None
    )
    cands = covers.apple_books_candidates(book, lambda url: ITUNES_RESULTS)
    assert len(cands) == 1
    c = cands[0]
    assert c.source == "apple"
    assert c.fmt is None
    assert c.label == "The Deluge — Adam Tooze"
    assert c.image_url.endswith("/9780241006115.jpg/1400x1400bb.jpg")
    assert c.isbn == "9780241006115"


def test_apple_books_uses_collection_name_and_no_isbn_for_opaque_art():
    book = covers.MissingBook(
        book_id="x",
        title="The Anatomy of Fascism",
        authors=["Robert O. Paxton"],
        isbn=None,
        amazon=None,
    )
    cands = covers.apple_books_candidates(book, lambda url: ITUNES_RESULTS_NO_ISBN)
    assert len(cands) == 1
    assert cands[0].label == "The Anatomy of Fascism — Robert O. Paxton"
    assert cands[0].isbn is None
    assert "1400x1400bb" in cands[0].image_url


def test_apple_books_normalizes_author():
    book = covers.MissingBook(
        book_id="x",
        title="The Republic",
        authors=["Plato and Benjamin Jowett"],
        isbn=None,
        amazon=None,
    )
    captured = {}

    def fake_fetch(url):
        captured["url"] = url
        return {"results": []}

    covers.apple_books_candidates(book, fake_fetch)
    assert "Plato" in captured["url"]
    assert "Benjamin" not in captured["url"]


def test_apple_books_no_results_returns_empty():
    book = covers.MissingBook(book_id="x", title="X", authors=[], isbn=None, amazon=None)
    assert covers.apple_books_candidates(book, lambda url: {"results": []}) == []


def test_apple_books_skips_results_without_artwork():
    book = covers.MissingBook(book_id="x", title="X", authors=["Y"], isbn=None, amazon=None)
    data = {"results": [{"trackName": "X", "artistName": "Y"}]}
    assert covers.apple_books_candidates(book, lambda url: data) == []


def test_gather_candidates_apple_first():
    book = covers.MissingBook(
        book_id="x", title="The Deluge", authors=["Adam Tooze"], isbn=None, amazon="B00ABCDEFG"
    )

    def fake_fetch(url):
        if "itunes.apple.com" in url:
            return ITUNES_RESULTS
        if "googleapis" in url:
            return GOOGLE_VOLUME
        if "editions.json" in url:
            return OL_EDITIONS
        return OL_SEARCH

    cands = covers.gather_candidates(book, fake_fetch)
    sources = [c.source for c in cands]
    assert sources[0] == "apple"
    assert sources[-1] == "amazon"
    assert (
        sources.index("apple")
        < sources.index("google")
        < sources.index("openlibrary")
        < sources.index("amazon")
    )


def test_covers_merge_render_materializes_cover(tmp_path):
    from books.renderers.obsidian import note as render

    # a goodreads-style source layer with one cover-less book
    store.write_layer(tmp_path, "goodreads", [store.BookRow(title="A", authors=["Ann"], isbn="")])
    store.merge(tmp_path)  # -> books.csv with a book_id

    covers.run(
        tmp_path,
        interactive=False,
        dry_run=False,
        limit=None,
        fetch_json=lambda url: (
            _google_volume_with_isbn("9780141032184") if "googleapis" in url else {"docs": []}
        ),
        fetch_bytes=lambda url: (_png(200, 300), "image/jpeg"),
        prompt=None,
    )

    store.merge(tmp_path)  # fold covers layer into books.csv
    row = next(r for r in store.read_books_csv(tmp_path) if r.title == "A")
    assert row.isbn == "9780141032184"  # learned isbn folded in
    assert row.cover.endswith(".jpg")  # staged path folded in

    render.render(tmp_path)
    cover_file = tmp_path / "Data" / "Covers" / f"{row.book_id}.jpg"
    assert cover_file.is_file()  # materialized
    note = (tmp_path / "Books" / f"{row.book_id}.md").read_text()
    assert f"![[Data/Covers/{row.book_id}.jpg|150]]" in note

    first = (tmp_path / "Books" / f"{row.book_id}.md").read_bytes()
    render.render(tmp_path)
    assert (tmp_path / "Books" / f"{row.book_id}.md").read_bytes() == first
