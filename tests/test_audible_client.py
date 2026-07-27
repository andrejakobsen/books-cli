"""Tests for the Audible cloud adapter's pure helpers."""

from books import audible_client as ac


def test_default_auth_path_is_in_config_dir(monkeypatch, tmp_path):
    from books import config
    monkeypatch.setattr(config, "config_path",
                        lambda: tmp_path / "books" / "config.toml")
    assert ac.default_auth_path() == tmp_path / "books" / "audible-auth.json"


def test_chapters_from_metadata_parses_ranges():
    meta = {"content_metadata": {"chapter_info": {"chapters": [
        {"title": "Intro", "start_offset_ms": 0, "length_ms": 60_000},
        {"title": "Rise", "start_offset_ms": 60_000, "length_ms": 90_000},
    ]}}}
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
    import httpx

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


def test_annotations_from_sidecar_maps_clips_and_bookmarks():
    payload = {"payload": {"records": [
        {"annotationId": "c1", "type": "audible.Clip",
         "startPosition": "10000", "endPosition": "20000",
         "creationTime": "2026-07-01", "text": "my note"},
        {"annotationId": "b1", "type": "audible.Bookmark",
         "startPosition": "30000", "creationTime": "2026-07-02"},
    ]}}
    anns = ac.annotations_from_sidecar(payload)
    assert anns[0].id == "c1" and anns[0].start_ms == 10000
    assert anns[0].end_ms == 20000 and anns[0].note == "my note"
    assert anns[1].id == "b1" and anns[1].start_ms == 30000
    assert anns[1].end_ms is None            # bookmark has no duration
