"""HTTP fetching (retry/backoff) and image-bytes validation for covers."""

from __future__ import annotations

import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

MIN_IMAGE_BYTES = 1000
MIN_IMAGE_DIM = 100  # px; anything smaller is a placeholder/thumbnail, not a cover

_JPEG_SOF_MARKERS = frozenset(range(0xC0, 0xD0)) - {
    0xC4,
    0xC8,
    0xCC,
}  # SOF0..SOF15 except DHT/JPG/DAC


def _jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    """Scan JPEG segments for a Start-Of-Frame marker and read its size."""
    i, n = 2, len(data)
    while i + 9 < n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in _JPEG_SOF_MARKERS:
            height = int.from_bytes(data[i + 5 : i + 7], "big")
            width = int.from_bytes(data[i + 7 : i + 9], "big")
            return (width, height)
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            i += 2  # standalone markers carry no length
            continue
        seg_len = int.from_bytes(data[i + 2 : i + 4], "big")
        if seg_len < 2:
            break
        i += 2 + seg_len
    return None


def image_dimensions(data: bytes) -> tuple[int, int] | None:
    """Return (width, height) parsed from a PNG/GIF/JPEG header, else None.

    Header-only parsing (stdlib, no image library); returns None when the bytes
    are not a recognizable image so callers can fall back to a size heuristic.
    """
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        return (int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big"))
    if data[:6] in (b"GIF87a", b"GIF89a") and len(data) >= 10:
        return (int.from_bytes(data[6:8], "little"), int.from_bytes(data[8:10], "little"))
    if data[:2] == b"\xff\xd8":
        return _jpeg_dimensions(data)
    return None


def is_valid_image(data: bytes, content_type: str | None) -> bool:
    """True if *data* looks like a real cover image.

    Requires an image content-type. When the dimensions are parseable, both must
    be at least MIN_IMAGE_DIM (rejects 1x1 placeholders); when they are not
    parseable, falls back to the byte-size heuristic.
    """
    if not content_type or not content_type.lower().startswith("image/"):
        return False
    dims = image_dimensions(data)
    if dims is not None:
        width, height = dims
        return width >= MIN_IMAGE_DIM and height >= MIN_IMAGE_DIM
    return len(data) >= MIN_IMAGE_BYTES


USER_AGENT = "books-covers/1.0 (+https://github.com/)"
HTTP_TIMEOUT = 15
HTTP_RETRIES = 10  # attempt cap; the time budget below usually binds first
HTTP_BACKOFF = 1.0  # base seconds; doubles each attempt (1s, 2s, 4s, …)
HTTP_MAX_SECONDS = 60.0  # per-source time budget: stop retrying and move on after ~1 min

# Transient HTTP statuses worth retrying: rate limiting + server errors.
# 403 is included because the iTunes Search API (Apple Books) returns Forbidden
# when it throttles, rather than the standard 429.
RETRYABLE_STATUS = frozenset({403, 429, 500, 502, 503, 504})


def fetch_with_retry(
    do_fetch,
    *,
    retries=HTTP_RETRIES,
    backoff=HTTP_BACKOFF,
    max_seconds=HTTP_MAX_SECONDS,
    sleep=time.sleep,
    clock=time.monotonic,
):
    """Call *do_fetch* (a zero-arg fetcher), retrying transient failures.

    Retries on retryable HTTP statuses (403/429/5xx — 403 covers iTunes
    throttling) and connection errors with exponential backoff, then re-raises the
    last error. Retrying stops — and the caller moves on to the next source — once
    either *retries* attempts are made or *max_seconds* of wall-clock time has
    elapsed (a persistently throttled source is abandoned after ~1 minute rather
    than blocking the whole run). Non-retryable errors (e.g. 404) are re-raised
    immediately.
    """
    start = clock()
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            return do_fetch()
        except HTTPError as exc:
            if exc.code not in RETRYABLE_STATUS:
                raise
            last_exc = exc
        except URLError as exc:
            last_exc = exc
        if attempt == retries - 1:
            break
        delay = backoff * (2**attempt)
        # Stop if the next backoff would push us past the per-source time budget.
        if (clock() - start) + delay >= max_seconds:
            break
        sleep(delay)
    assert last_exc is not None  # loop only exits here after a caught error
    raise last_exc


def default_fetch_json(url: str) -> dict:
    """GET *url* and parse JSON, retrying transient failures."""

    def do():
        req = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))

    return fetch_with_retry(do)


def default_fetch_bytes(url: str) -> tuple[bytes, str | None]:
    """GET *url* returning (body, content_type), retrying transient failures."""

    def do():
        req = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            return resp.read(), resp.headers.get("Content-Type")

    return fetch_with_retry(do)
