"""Audible cloud adapter: auth, library, annotations, chapters, download.

Wraps the maintained `audible` + `audible-cli` packages (imported lazily so the rest
of the CLI never needs them) rather than reimplementing auth, the license/voucher
flow, download, or annotations. Exposes the small interface `run()` consumes:
`library()`, `annotations(asin)`, `chapters(asin)`, `download(asin, dest_dir)`.

Download flow: use `audible_cli.models.LibraryItem.get_aaxc_url(quality)` to obtain
the AAXC download URL + voucher (which yields the key/iv), download the AAXC, and
hand the key/iv to ffmpeg (`-audible_key`/`-audible_iv`) at cut time — no separate
whole-file decrypt. `cryptography` (optional) accelerates the voucher decryption.
Chapters come from `LibraryItem.get_content_metadata(quality, chapter_type=...)`.
Bookmarks/clips come from the CDE sidecar endpoint (no audible-cli helper exists, so
this one call is made directly and parsed by `annotations_from_sidecar`).

The networked methods require a live Audible account and are verified manually; the
pure parsers below are unit-tested.
"""

from __future__ import annotations

from pathlib import Path
from urllib.request import urlopen

from books.commands.audible.models import (
    Annotation,
    Chapter,
    DownloadedAudio,
    LibraryBook,
)
from books.core import config

_MISSING = (
    "Audible support needs the `audible` package. Install the extra with:\n"
    "  uv tool install '.[audible]'    (or: pip install 'books[audible]')"
)

SIDECAR_URL = ("https://cde-ta-g7g.amazon.com/FionaCDEServiceEngine/"
               "sidecar?type=AUDI&key={asin}")

# Response groups requested when fetching the library. This mirrors the set
# audible-cli's own `library` command asks for, and it must stay broad because
# `LibraryItem`'s predicates read fields lazily: `is_published()` needs
# `publication_datetime` (from `product_attrs`) and `is_downloadable()` needs
# `customer_rights`. Omitting either makes those return None, and audible-cli's
# `get_aaxc_url()` then raises `ItemNotPublished(asin, None)` -> a
# `strptime(None)` crash (or a spurious "not downloadable"). Keeping the full
# set matches the real client and guards against other predicates too.
LIBRARY_RESPONSE_GROUPS = (
    "contributors, customer_rights, media, price, product_attrs, "
    "product_desc, product_extended_attrs, product_plan_details, "
    "product_plans, rating, sample, sku, series, reviews, ws4v, "
    "origin, relationships, review_attrs, categories, "
    "badge_types, category_ladders, claim_code_url, in_wishlist, "
    "is_archived, is_downloaded, is_finished, is_playable, "
    "is_removable, is_returnable, is_visible, listening_status, "
    "order_details, origin_asin, pdf_url, percent_complete, "
    "periodicals, provided_review, product_details"
)


def default_auth_path() -> Path:
    """Where the cached Audible auth file lives (beside the CLI config)."""
    return config.config_path().parent / "audible-auth.json"


def _to_ms(value) -> int:
    """Parse a position that Audible may send as int or numeric string."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def chapters_from_metadata(meta: dict) -> list[Chapter]:
    """Parse content-metadata JSON into ordered Chapters (end = start + length)."""
    raw = (((meta or {}).get("content_metadata") or {})
           .get("chapter_info") or {}).get("chapters") or []
    chapters: list[Chapter] = []
    for i, ch in enumerate(raw, start=1):
        start = _to_ms(ch.get("start_offset_ms"))
        length = _to_ms(ch.get("length_ms"))
        chapters.append(Chapter(
            index=i,
            title=(ch.get("title") or f"Chapter {i}").strip(),
            start_ms=start,
            end_ms=start + length,
        ))
    return chapters


def annotations_from_sidecar(payload: dict) -> list[Annotation]:
    """Parse the CDE sidecar payload into Annotations (clips + bookmarks + notes).

    A record with an endPosition is a clip (has duration); one without is a point
    bookmark. `text` carries the user's typed note when present.
    """
    records = ((payload or {}).get("payload") or {}).get("records") or []
    out: list[Annotation] = []
    for rec in records:
        ann_id = rec.get("annotationId") or rec.get("id")
        if not ann_id or rec.get("startPosition") is None:
            continue
        end = rec.get("endPosition")
        out.append(Annotation(
            id=str(ann_id),
            start_ms=_to_ms(rec.get("startPosition")),
            end_ms=None if end is None else _to_ms(end),
            note=(rec.get("text") or "").strip() or None,
            date=(rec.get("creationTime") or "").strip() or None,
        ))
    return out


def voucher_key_iv(license_response: dict) -> tuple[str, str]:
    """Return the AAXC ``(key, iv)`` from a ``get_aaxc_url`` license response.

    audible-cli's ``get_license()`` already decrypts the voucher in place,
    storing the decrypted ``{key, iv, ...}`` dict at
    ``license_response["content_license"]["license_response"]`` -- so it is read
    here, not decrypted again (decrypting the already-decrypted dict raises
    "argument should be a bytes-like object ... not dict"). Raises RuntimeError
    when the voucher (or its key/iv) is absent -- e.g. upstream decryption
    failed and left the encrypted string in place.
    """
    voucher = (((license_response or {}).get("content_license") or {})
               .get("license_response"))
    key = voucher.get("key") if isinstance(voucher, dict) else None
    iv = voucher.get("iv") if isinstance(voucher, dict) else None
    if not key or not iv:
        raise RuntimeError(
            "Could not recover the AAXC key/iv from the license response "
            "(voucher missing or not decrypted).")
    return key, iv


class AudibleClient:
    """Thin wrapper over the `audible` package (integration seam)."""

    #: Audiobook download quality tier used for chapters + AAXC download. Only
    #: affects download size/speed — clips are transcribed to text, so the
    #: lowest tier ("normal") is plenty. Override via `--quality`.
    QUALITY_CHOICES = ("normal", "high", "best")

    def __init__(self, auth, client=None, quality: str = "normal") -> None:
        self._auth = auth
        self._client = client
        self.quality = quality
        # Raw `library` API response, cached loop-independently. LibraryItem
        # objects bind to the AsyncClient they were built with, so they can't
        # be reused across event loops; the raw dict can, and items are cheaply
        # re-wrapped against the live client on each call (one HTTP fetch total).
        self._catalog = None

    # ---- construction -----------------------------------------------------

    @classmethod
    def load_or_login(cls, auth_path: Path, marketplace: str = "us",
                      quality: str = "normal"):
        """Load a cached auth file, or run the interactive login and cache it."""
        try:
            import audible
        except ImportError as exc:
            raise RuntimeError(_MISSING) from exc
        if auth_path.is_file():
            auth = audible.Authenticator.from_file(str(auth_path))
        else:
            # Importing readline replaces the terminal's canonical-mode line
            # editor (which caps input at ~1KB and silently freezes on a long
            # paste) with GNU readline, so the long post-login redirect URL can
            # be pasted. Best-effort: not present on every platform.
            try:
                import readline  # noqa: F401
            except ImportError:
                pass
            typer_prompt = __import__("typer")
            country = typer_prompt.prompt(
                "Audible marketplace (us, uk, de, ...)", default=marketplace)
            typer_prompt.secho(
                "\nOpen the URL below in your browser and sign in to Amazon "
                "(this is where any email/SMS verification 'CVF' code and "
                "CAPTCHA will appear, exactly like the website). After you "
                "finish signing in you'll land on a page that fails to load "
                "('Page not found' is expected) — copy that page's full URL "
                "from the address bar and paste it back here.\n",
                fg="yellow",
            )
            auth = audible.Authenticator.from_login_external(
                locale=country)
            auth_path.parent.mkdir(parents=True, exist_ok=True)
            auth.to_file(str(auth_path))
            auth_path.chmod(0o600)
        return cls(auth, None, quality=quality)

    # ---- async plumbing ---------------------------------------------------

    def _run(self, op):
        """Drive an async operation to completion on a fresh event loop.

        `audible-cli` (>=0.4) exposes async models backed by an
        `audible.AsyncClient`. httpx's async client binds to the running loop,
        so the client is created and closed inside the same `asyncio.run` call
        that awaits `op(client)` — never kept across calls.
        """
        import asyncio

        import audible

        async def _driver():
            async with audible.AsyncClient(self._auth) as client:
                return await op(client)

        return asyncio.run(_driver())

    async def _fetch_items(self, client):
        """Return audible-cli LibraryItem models (keyed by asin), fetched once.

        The `library` endpoint is hit over HTTP only on the first call; the raw
        response is cached on the instance and subsequent calls re-wrap it
        against the current live client (no network), avoiding a full-library
        refetch per book for `chapters()`/`download()`.
        """
        from audible_cli.models import Library
        if self._catalog is None:
            from audible.client import convert_response_content
            from audible_cli.utils import full_response_callback
            resp = await client.get(
                "library",
                response_callback=full_response_callback,
                response_groups=LIBRARY_RESPONSE_GROUPS)
            self._catalog = convert_response_content(resp)
        library = Library(self._catalog, api_client=client)
        return {item.asin: item for item in library}

    # ---- reads ------------------------------------------------------------

    def library(self) -> list[LibraryBook]:
        async def op(client):
            out: list[LibraryBook] = []
            items = await self._fetch_items(client)
            for asin, item in items.items():
                authors = [a.get("name", "").strip()
                           for a in (getattr(item, "authors", None) or [])
                           if a.get("name")]
                out.append(LibraryBook(
                    asin=asin,
                    title=(getattr(item, "title", "") or "").strip(),
                    authors=authors,
                ))
            return out

        return self._run(op)

    def chapters(self, asin: str) -> list[Chapter]:
        async def op(client):
            item = (await self._fetch_items(client))[asin]
            meta = await item.get_content_metadata(quality=self.quality)
            return chapters_from_metadata(meta)

        return self._run(op)

    def annotations(self, asin: str) -> list[Annotation]:
        """Fetch bookmarks/clips from the CDE sidecar (no audible-cli helper).

        `audible.Authenticator` is an `httpx.Auth` flow, so it signs the bare GET
        when passed as `auth=` (the old `sign_request(method=…)` API is gone). A
        book with no bookmarks/clips has no sidecar and answers 404, which is
        treated as "no annotations" rather than a fatal error.
        """
        import httpx
        url = SIDECAR_URL.format(asin=asin)
        with httpx.Client(timeout=30) as hx:
            resp = hx.get(url, auth=self._auth)
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            payload = resp.json()
        return annotations_from_sidecar(payload)

    def download(self, asin: str, dest_dir: Path) -> DownloadedAudio:
        """Download the AAXC via audible-cli and return it plus its key/iv.

        `get_aaxc_url` returns (url, codec, license_response). audible-cli's
        `get_license` has already decrypted the AAXC voucher into
        `license_response["content_license"]["license_response"]`, so the key/iv
        are read from there (see `voucher_key_iv`) — decrypting it again would
        fail. `url` is an `httpx.URL`, stringified for `urlopen` (the offline
        URL is presigned — no auth).
        """
        async def op(client):
            item = (await self._fetch_items(client))[asin]
            url, codec, license_response = await item.get_aaxc_url(self.quality)
            key, iv = voucher_key_iv(license_response)
            dest = Path(dest_dir) / f"{asin}.aaxc"
            with urlopen(str(url)) as resp, open(dest, "wb") as fh:
                fh.write(resp.read())
            return DownloadedAudio(path=dest, key=key, iv=iv)

        return self._run(op)
