#!/usr/bin/env python3
"""Convert Apollo Group TV M3U VOD playlists into .strm files for a media server.

Reads playlist URLs from tv_vod_urls.txt and movie_vod_urls.txt (one per line,
lines starting with # ignored) and mirrors their contents into TV/ and Movies/
as .strm files:

    TV/<category>/<name>.strm
    Movies/<name>/<name>.strm

Sync behavior:
  - .strm files are only rewritten when their stream URL changed.
  - .strm files no longer present in the playlists are deleted, but only if
    every playlist for that section was fetched and parsed successfully.
    A playlist that is unreachable or empty disables deletion for the whole
    section, so a provider outage never wipes the library.
  - Only .strm files are ever deleted; NFO files, artwork and any other
    media-server metadata are left alone. Empty directories are pruned.
"""

import argparse
import logging
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

import requests
from m3u_parser import M3uParser
from pathvalidate import sanitize_filename

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/86.0.4240.75 Safari/537.36"
)
CONNECT_TIMEOUT = 10
READ_TIMEOUT = 120

log = logging.getLogger("getstreams")


def redact(url):
    """Strip credentials from a playlist URL so it is safe to log."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.hostname}/..."


def collapse_duplicate_years(name):
    """'Show (2020) (2020)' -> 'Show (2020)'."""
    return re.sub(r"(\(\d{4}\))(\s+\1)+", r"\1", name)


def read_url_file(path):
    urls = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            urls.append(line)
    return urls


def fetch_playlist(url, workdir):
    """Download a playlist to a temp file and parse it.

    Returns a list of stream dicts, or None if the fetch/parse failed.
    Downloading ourselves (instead of letting M3uParser fetch) gives us
    explicit timeouts and status handling, and avoids fetching twice.
    """
    try:
        response = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
        )
    except requests.exceptions.RequestException as exc:
        log.warning("%s: fetch failed: %s", redact(url), type(exc).__name__)
        return None
    if response.status_code != 200:
        log.warning("%s: HTTP %s", redact(url), response.status_code)
        return None

    with tempfile.NamedTemporaryFile(
        mode="wb", suffix=".m3u", dir=workdir, delete=False
    ) as tmp:
        tmp.write(response.content)
        tmp_path = Path(tmp.name)
    try:
        parser = M3uParser(timeout=CONNECT_TIMEOUT, useragent=USER_AGENT)
        # check_live would issue a request per stream entry; never do that.
        parser.parse_m3u(str(tmp_path), check_live=False)
        streams = parser.get_list()
    except Exception as exc:
        log.warning("%s: parse failed: %s", redact(url), exc)
        return None
    finally:
        tmp_path.unlink(missing_ok=True)

    if not streams:
        log.warning("%s: playlist parsed but contained no streams", redact(url))
        return None
    return streams


def strm_path(dest, item, movie_layout):
    """Target .strm path for a stream dict, or None if it can't be built."""
    name = item.get("name")
    url = item.get("url")
    if not name or not url:
        return None
    name = sanitize_filename(collapse_duplicate_years(name))
    if not name:
        return None
    if movie_layout:
        return dest / name / f"{name}.strm"
    category = item.get("category") or "Uncategorized"
    category = sanitize_filename(collapse_duplicate_years(category)) or "Uncategorized"
    return dest / category / f"{name}.strm"


def sync_section(label, url_file, dest, movie_layout, allow_delete):
    """Mirror the playlists in url_file into dest. Returns True on full success."""
    urls = read_url_file(url_file)
    if not urls:
        log.error("%s: no URLs in %s", label, url_file.name)
        return False

    complete = True
    expected = {}  # resolved Path -> stream url
    written = skipped = collisions = 0

    for url in urls:
        streams = fetch_playlist(url, dest)
        if streams is None:
            complete = False
            continue
        log.info("%s: %s -> %d entries", label, redact(url), len(streams))
        for item in streams:
            target = strm_path(dest, item, movie_layout)
            if target is None:
                continue
            target = target.resolve()
            if target in expected:
                if expected[target] != item["url"]:
                    collisions += 1
                continue  # first entry wins
            expected[target] = item["url"]

    for target, stream_url in expected.items():
        if target.exists() and target.read_text() == stream_url:
            skipped += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(stream_url)
        written += 1

    if collisions:
        log.warning("%s: %d name collisions (kept first occurrence)", label, collisions)
    log.info("%s: %d written, %d unchanged", label, written, skipped)

    if not (allow_delete and complete):
        if allow_delete and not complete:
            log.warning("%s: a playlist failed; skipping deletion pass", label)
        return complete

    deleted = 0
    for strm in dest.rglob("*.strm"):
        if strm.resolve() not in expected:
            strm.unlink()
            deleted += 1
    for folder in sorted(dest.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
    log.info("%s: %d stale .strm deleted", label, deleted)
    return True


def main():
    argp = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    argp.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="directory containing the url files and TV/Movies folders",
    )
    argp.add_argument(
        "--no-delete",
        action="store_true",
        help="never delete stale .strm files, only write/update",
    )
    args = argp.parse_args()
    logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)

    sections = [
        ("TV", args.root / "tv_vod_urls.txt", args.root / "TV", False),
        ("Movies", args.root / "movie_vod_urls.txt", args.root / "Movies", True),
    ]

    ok = True
    for label, url_file, dest, movie_layout in sections:
        if not url_file.is_file():
            log.error("%s: %s not found", label, url_file)
            ok = False
            continue
        if not dest.is_dir():
            log.error("%s: folder %s not found", label, dest)
            ok = False
            continue
        ok = sync_section(label, url_file, dest, movie_layout, not args.no_delete) and ok

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
