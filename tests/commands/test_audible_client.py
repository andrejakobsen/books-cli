"""Tests for the Audible cloud adapter's pure helpers."""

import json
from pathlib import Path

from books.commands.audible import client as ac

FIXTURES = Path(__file__).parent / "fixtures"


def _load_sidecar(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_default_auth_path_is_in_config_dir(monkeypatch, tmp_path):
    from books.core import config

    monkeypatch.setattr(config, "config_path", lambda: tmp_path / "books" / "config.toml")
    assert ac.default_auth_path() == tmp_path / "books" / "audible-auth.json"


def test_chapters_from_metadata_parses_ranges():
    meta = {
        "content_metadata": {
            "chapter_info": {
                "chapters": [
                    {"title": "Intro", "start_offset_ms": 0, "length_ms": 60_000},
                    {"title": "Rise", "start_offset_ms": 60_000, "length_ms": 90_000},
                ]
            }
        }
    }
    chapters = ac.chapters_from_metadata(meta)
    assert [c.index for c in chapters] == [1, 2]
    assert chapters[0].title == "Intro"
    assert chapters[0].start_ms == 0 and chapters[0].end_ms == 60_000
    assert chapters[1].start_ms == 60_000 and chapters[1].end_ms == 150_000


def test_voucher_key_iv_reads_decrypted_voucher():
    # audible-cli's get_license() decrypts the voucher in place, so the license
    # response carries the {key, iv} dict -- read it, don't decrypt again.
    lr = {"content_license": {"license_response": {"key": "K", "iv": "V"}}}
    assert ac.voucher_key_iv(lr) == ("K", "V")


def test_voucher_key_iv_raises_when_not_decrypted():
    import pytest

    # Upstream decryption failed: still the raw encrypted string.
    with pytest.raises(RuntimeError):
        ac.voucher_key_iv({"content_license": {"license_response": "ENCSTR"}})
    with pytest.raises(RuntimeError):
        ac.voucher_key_iv({})


def test_annotations_returns_empty_on_404(monkeypatch):
    # A book with no bookmarks/clips returns 404 from the sidecar endpoint;
    # that must be treated as "no annotations", not a fatal error.
    import pytest

    httpx = pytest.importorskip("httpx")  # optional [audible] dependency

    class FakeResp:
        status_code = 404

        def raise_for_status(self):
            raise AssertionError("must not raise on 404")

        def json(self):
            raise AssertionError("must not read body on 404")

    class FakeClientCtx:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, auth=None):
            return FakeResp()

    monkeypatch.setattr(httpx, "Client", FakeClientCtx)
    client = ac.AudibleClient(auth=object())
    assert client.annotations("B0MISSING") == []


def test_annotations_from_sidecar_maps_clip_and_standalone_note():
    # A clip carries its title and note under a nested `metadata` object; a
    # standalone note (no clip at its position) uses a top-level `text` field and
    # is kept as a text-only annotation. Bookmarks are auto-created noise and are
    # always dropped.
    payload = {
        "payload": {
            "records": [
                {
                    "annotationId": "c1",
                    "type": "audible.clip",
                    "startPosition": "10000",
                    "endPosition": "20000",
                    "creationTime": "2026-07-01",
                    "metadata": {"title": "My clip", "note": "my note"},
                },
                {
                    "annotationId": "n1",
                    "type": "audible.note",
                    "startPosition": "25000",
                    "endPosition": "25000",
                    "creationTime": "2026-07-03",
                    "text": "standalone note",
                },
                {
                    "annotationId": "b1",
                    "type": "audible.bookmark",
                    "startPosition": "30000",
                    "creationTime": "2026-07-02",
                },
            ]
        }
    }
    anns = ac.annotations_from_sidecar(payload)
    ids = [a.id for a in anns]
    assert ids == ["c1", "n1"]  # bookmark b1 dropped entirely
    assert anns[0].end_ms == 20000  # clip has duration
    assert anns[0].title == "My clip" and anns[0].note == "my note"
    # A standalone note is text-only: no audio range (end == start) so run() won't
    # transcribe it, and its text lands in `note`.
    assert anns[1].note == "standalone note" and anns[1].title is None
    assert anns[1].end_ms == anns[1].start_ms == 25000


def test_annotations_from_sidecar_drops_twin_bookmarks_and_duplicate_notes():
    # Real sidecar data (extracted from Audible): every clip has an auto-created
    # twin bookmark at the same position, and a note comes as BOTH the clip's
    # metadata.note AND a separate audible.note record with the same text. The
    # parser must collapse each position to a single clip annotation — no twin
    # bookmarks, no duplicate note records, no lone bookmarks.
    payload = _load_sidecar("audible_sidecar_sample.json")
    anns = ac.annotations_from_sidecar(payload)

    ids = [a.id for a in anns]
    # Exactly the five clips, in record order; every bookmark + note id gone.
    assert ids == [
        "a2C45KLXAFKCAC",
        "a1CFNDRSEH005Q",
        "a1M9448UCP12PO",
        "a24KW62IU3IU7U",
        "a3O1Z3YFAN0SNA",
    ]
    # No duplicates.
    assert len(ids) == len(set(ids))
    # Every kept annotation is a real clip with a duration (text will transcribe).
    assert all(a.end_ms is not None and a.end_ms > a.start_ms for a in anns)

    by_id = {a.id: a for a in anns}
    # The note text rides along on its clip (metadata.note), not as its own record.
    assert by_id["a1M9448UCP12PO"].title == "Their plan for modernization"
    assert by_id["a1M9448UCP12PO"].note == "@modernization @geopolitics"
    assert by_id["a3O1Z3YFAN0SNA"].title == "@causality"
    assert by_id["a3O1Z3YFAN0SNA"].note.startswith("Interesting way to look")


def test_annotations_from_sidecar_borrows_note_text_when_clip_lacks_it():
    # Defensive: if a clip has no metadata.note but a separate note record sits at
    # the same position, the clip should adopt that note's text (still one
    # annotation, no duplicate).
    payload = {
        "payload": {
            "records": [
                {
                    "annotationId": "c1",
                    "type": "audible.clip",
                    "startPosition": "5000",
                    "endPosition": "9000",
                    "metadata": {"title": "A clip"},
                },
                {
                    "annotationId": "n1",
                    "type": "audible.note",
                    "startPosition": "5000",
                    "endPosition": "5000",
                    "text": "my thought",
                },
            ]
        }
    }
    anns = ac.annotations_from_sidecar(payload)
    assert [a.id for a in anns] == ["c1"]
    assert anns[0].title == "A clip"
    assert anns[0].note == "my thought"
