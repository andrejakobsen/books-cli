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

import json
from pathlib import Path
from urllib.request import urlopen

from books import config
from books.audible_obsidian import Annotation, Chapter, DownloadedAudio, LibraryBook

_MISSING = (
    "Audible support needs the `audible` package. Install the extra with:\n"
    "  uv tool install '.[audible]'    (or: pip install 'books[audible]')"
)

SIDECAR_URL = ("https://cde-ta-g7g.amazon.com/FionaCDEServiceEngine/"
               "sidecar?type=AUDI&key={asin}")


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


class AudibleClient:
    """Thin wrapper over the `audible` package (integration seam)."""

    def __init__(self, auth, client) -> None:
        self._auth = auth
        self._client = client

    # ---- construction -----------------------------------------------------

    @classmethod
    def load_or_login(cls, auth_path: Path, marketplace: str = "us"):
        """Load a cached auth file, or run the interactive login and cache it."""
        try:
            import audible
        except ImportError as exc:
            raise RuntimeError(_MISSING) from exc
        if auth_path.is_file():
            auth = audible.Authenticator.from_file(str(auth_path))
        else:
            typer_prompt = __import__("typer")
            username = typer_prompt.prompt("Audible email")
            password = typer_prompt.prompt("Audible password", hide_input=True)
            country = typer_prompt.prompt(
                "Audible marketplace (us, uk, de, ...)", default=marketplace)
            auth = audible.Authenticator.from_login(
                username, password, locale=country,
                with_username=False)
            auth_path.parent.mkdir(parents=True, exist_ok=True)
            auth.to_file(str(auth_path))
            auth_path.chmod(0o600)
        return cls(auth, audible.Client(auth))

    # ---- reads ------------------------------------------------------------

    def _library_items(self):
        """Fetch the library as audible-cli LibraryItem models (keyed by asin)."""
        from audible_cli.models import Library
        library = Library.from_api(
            self._client,
            response_groups="product_desc,contributors,relationships")
        return {item.asin: item for item in library}

    def library(self) -> list[LibraryBook]:
        out: list[LibraryBook] = []
        for asin, item in self._library_items().items():
            authors = [a.get("name", "").strip()
                       for a in (getattr(item, "authors", None) or [])
                       if a.get("name")]
            out.append(LibraryBook(
                asin=asin,
                title=(getattr(item, "title", "") or "").strip(),
                authors=authors,
            ))
        return out

    def chapters(self, asin: str) -> list[Chapter]:
        item = self._library_items()[asin]
        meta = item.get_content_metadata(quality="High")
        return chapters_from_metadata(meta)

    def annotations(self, asin: str) -> list[Annotation]:
        """Fetch bookmarks/clips from the CDE sidecar (no audible-cli helper)."""
        with urlopen(self._signed(SIDECAR_URL.format(asin=asin))) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return annotations_from_sidecar(payload)

    def _signed(self, url: str):
        """Build a urllib Request signed with the Audible auth."""
        from urllib.request import Request
        req = Request(url)
        # The Authenticator produces the Authorization headers for a bare GET.
        headers = self._auth.sign_request(method="GET", path=url, body=b"")
        for key, value in headers.items():
            req.add_header(key, value)
        return req

    def download(self, asin: str, dest_dir: Path) -> DownloadedAudio:
        """Download the AAXC via audible-cli and return it plus its key/iv."""
        item = self._library_items()[asin]
        url, codec, voucher = item.get_aaxc_url("High")
        dest = Path(dest_dir) / f"{asin}.aaxc"
        with urlopen(url) as resp, open(dest, "wb") as fh:
            fh.write(resp.read())
        return DownloadedAudio(path=dest, key=voucher["key"], iv=voucher["iv"])
