# Jellyfin compatibility audit — upstream getstreams.py

Audit of the original bruor/Apollo_m3u_to_strm script (`main@9b46b5f`) against
current Jellyfin (10.11.x stable, May 2026; 12.0 at RC). Items 1–5 are defects;
6–7 are limitations of the .strm approach worth knowing.

## 1. TV layout is explicitly unsupported

Upstream writes `TV/<group-title>/<episode>.strm` — episodes directly in the
series folder. Jellyfin's docs require `Series (Year)/Season NN/Series SxxEyy.ext`
and state that episodes in the show root without season folders are **not
supported**. It half-works through SxxEyy filename parsing, but produces
misgrouped seasons, broken specials (no `Season 00`), and unreliable episode
matching. Fix: derive `Season NN` folders by parsing SxxEyy from the entry name.

## 2. mtime-based deletion destroys watch state

The 48h cleanup deletes .strm files whenever a playlist URL fails or runs are
>48h apart. Jellyfin's next scan removes those items; when the files return,
Jellyfin creates *new* item IDs — watched status, resume points, playlist and
collection membership are gone permanently. Current Jellyfin also has a
folder-blacklisting quirk (jellyfin#15518) where a folder seen empty for long
may not be rescanned at all. Deletion must be playlist-driven, never mtime-driven.

## 3. Rewriting every file every run churns the scanner

Upstream truncates and rewrites all ~127k .strm files each run purely to bump
mtimes (its deletion marker). With real-time monitoring this floods the file
watcher; scheduled scans see 127k "changed" files each run. Library scan is
already 10.11's weak spot (ffprobe memory issues jellyfin#16048/#16549; the
folder-library performance work only lands in 12.0). Files should only be
written when the URL actually changed.

## 4. Cleanup deletes Jellyfin's own metadata

The sweep removes *any* file older than 48h, not just `.strm`. With "save
metadata in media folders" (NFO saver) or local artwork enabled, Jellyfin's
NFOs/images are wiped every run: permanent re-scrape loop, provider hammering,
and "date added" resets. Deletion must be restricted to `*.strm`.

## 5. Duplicate-year bug corrupts name parsing

`remove_duplicate_year()` returns after the first fix, so `Show (2020) (2020)
(2020)` keeps a duplicate. Jellyfin parses `Name (Year)` from folder/file names;
a leftover `(2020)` lands in the title and wrecks TMDB matching. IPTV naming is
messy to begin with — collapsing all repeats (and ideally emitting
`[tmdbid-...]`-style provider tags when derivable) is required for clean matches.

## 6. Movie collisions can't express versions

`Movies/<name>/<name>.strm` matches the documented movie layout (file name ==
folder name). But upstream silently overwrites on name collisions, so HD/SD or
re-release variants vanish. Jellyfin only shows alternate editions when files
are named `Name (Year) - Label.strm`; anything else becomes a duplicate movie.

## 7. .strm limitations in current Jellyfin (informational)

Jellyfin treats .strm as shortcuts and never probes them during scans: items
show no codec/resolution/duration until first playback (community plugin
JellySTRMprobe exists to pre-probe). Playback ffprobes the target URL on
demand, so dead Apollo URLs surface as playback failures, not scan errors.
No script change fixes this; it's inherent to .strm.

## Status in this fork

Items 2–5 were fixed on `main` in the 2026-07-15 rewrite (playlist-driven
deletion, strm-only cleanup, write-on-change, global year collapse, collision
detection). This branch (`jellyfin-compat`) is for item 1 (Season folders) and
item 6 (version labels on collisions).

Sources: jellyfin.org docs (shows/movies naming), jellyfin#15518, #16048,
#16149, #16549, JellySTRMprobe README, State of the Fin 2026-05-24.
