"""Dump raw Audible API responses for inspection — especially clips & notes.

Reuses the cached auth (``~/.config/books/audible-auth.json``) via the existing
``AudibleClient``, then prints the raw JSON so you can see exactly what Audible
sends before it's parsed into ``Annotation``/``LibraryBook`` objects.

Usage (from repo root):

    uv run python scripts/dump_audible.py                 # list library (asin + title)
    uv run python scripts/dump_audible.py <ASIN>          # raw sidecar (clips/notes) for one book
    uv run python scripts/dump_audible.py <ASIN> --all    # sidecar + chapters + parsed annotations
    uv run python scripts/dump_audible.py --search deluge # find a book's ASIN by title substring

The sidecar endpoint (``SIDECAR_URL``) is where clips, bookmarks and notes live;
its ``payload.records`` array is what ``annotations_from_sidecar`` parses.
"""

from __future__ import annotations

import json
import sys

import httpx

from books.commands.audible.client import (
    SIDECAR_URL,
    AudibleClient,
    annotations_from_sidecar,
    chapters_from_metadata,
    default_auth_path,
)


def _pp(label: str, obj) -> None:
    print(f"\n===== {label} =====")
    print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


def _client() -> AudibleClient:
    auth_path = default_auth_path()
    if not auth_path.is_file():
        sys.exit(f"No cached auth at {auth_path}. Run `books audible` once to log in first.")
    return AudibleClient.load_or_login(auth_path)


def raw_sidecar(client: AudibleClient, asin: str) -> dict:
    """Fetch the untouched sidecar JSON for one ASIN (clips + bookmarks + notes)."""
    url = SIDECAR_URL.format(asin=asin)
    with httpx.Client(timeout=30) as hx:
        resp = hx.get(url, auth=client._auth)
        if resp.status_code == 404:
            return {"_note": "404 — no sidecar (book has no clips/bookmarks/notes)"}
        resp.raise_for_status()
        return resp.json()


def raw_chapters(client: AudibleClient, asin: str) -> dict:
    """Fetch the untouched content-metadata JSON (chapters live here)."""

    async def driver(inner_client):
        item = (await client._fetch_items(inner_client))[asin]
        return await item.get_content_metadata(quality=client.quality)

    return client._run(driver)


def main(argv: list[str]) -> None:
    args = [a for a in argv if not a.startswith("--")]
    flags = {a for a in argv if a.startswith("--")}

    client = _client()

    # --search <substr>: print matching ASINs and exit.
    if "--search" in flags:
        needle = args[0].lower() if args else ""
        for b in client.library():
            if needle in b.title.lower():
                print(f"{b.asin}  {b.title}  —  {', '.join(b.authors)}")
        return

    # No ASIN: list the whole library.
    if not args:
        for b in client.library():
            print(f"{b.asin}  {b.title}")
        return

    asin = args[0]

    sidecar = raw_sidecar(client, asin)
    _pp(f"RAW SIDECAR (clips/bookmarks/notes) — {asin}", sidecar)

    if "--all" in flags:
        parsed = annotations_from_sidecar(sidecar)
        _pp("PARSED ANNOTATIONS", [vars(a) for a in parsed])

        meta = raw_chapters(client, asin)
        _pp("RAW CONTENT METADATA (chapters)", meta)
        _pp("PARSED CHAPTERS", [vars(c) for c in chapters_from_metadata(meta)])


if __name__ == "__main__":
    main(sys.argv[1:])
