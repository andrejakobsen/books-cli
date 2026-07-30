from books.core.naming import next_free_stem, stem_for, strip_subtitle


def test_strip_subtitle_drops_colon_subtitle():
    assert strip_subtitle("The Deluge: The Great War") == "The Deluge"


def test_strip_subtitle_drops_trailing_comma_date_range():
    # A comma-delimited date range is a subtitle in history titles.
    assert strip_subtitle("The Romanovs, 1613-1917") == "The Romanovs"


def test_strip_subtitle_drops_trailing_comma_single_year():
    assert strip_subtitle("Berlin, 1945") == "Berlin"


def test_strip_subtitle_keeps_non_date_comma():
    # A comma with no trailing year is a real title, not a subtitle.
    assert strip_subtitle("Berlin, Alexanderplatz") == "Berlin, Alexanderplatz"


def test_stem_for_joins_title_and_author():
    assert stem_for("The Deluge", "Adam Tooze") == "The Deluge - Adam Tooze"


def test_stem_for_sanitizes_illegal_chars():
    # A colon is illegal in a path segment -> replaced by safe_filename.
    assert stem_for("Stalin: Vol I", "Kotkin") == "Stalin_ Vol I - Kotkin"


def test_stem_for_without_author_is_title_only():
    assert stem_for("Beowulf", "") == "Beowulf"


def test_next_free_stem_uses_stem_for_clean_then_full():
    # First call: clean stem (subtitle dropped). Second (collision): subtitle
    # restored with ':' -> ','.
    used: set[str] = set()
    first = next_free_stem("Stalin: Paradoxes", "Kotkin", used)
    assert first == "Stalin - Kotkin"
    used.add(first.lower())
    second = next_free_stem("Stalin: Waiting for Hitler", "Kotkin", used)
    assert second == "Stalin, Waiting for Hitler - Kotkin"
