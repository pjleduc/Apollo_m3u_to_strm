# Apollo M3U to STRM

Converts Apollo Group TV (apollogroup.tv) M3U VOD playlists into `.strm` files
for Jellyfin, Emby or Plex.

Fork of [bruor/Apollo_m3u_to_strm](https://github.com/bruor/Apollo_m3u_to_strm)
with the sync logic reworked for safety and robustness:

- **Deletion is playlist-driven, not mtime-driven.** A `.strm` file is removed
  only when every playlist in its section was fetched and parsed successfully
  and the entry is genuinely gone. A provider outage, a 404 on one URL, or a
  long gap between runs can no longer wipe your library.
- **Only `.strm` files are ever deleted.** NFO files, artwork and other
  media-server metadata in the library tree are left alone. Empty folders are
  pruned.
- **Unchanged files are not rewritten**, so file modification times stay stable
  and your media server doesn't rescan 100k+ items every run.
- Playlists are downloaded once (not twice) with proper timeouts; a dead URL is
  logged and skipped instead of aborting the run.
- Credentials embedded in playlist URLs are redacted from all log output.
- Duplicate-year titles (`Show (2020) (2020)`) are collapsed, and name
  collisions are detected and logged instead of silently overwriting.
- No more `os.chdir` or hardcoded relative paths: run it from anywhere with
  `--root`, exit code 1 on any failure (cron-friendly), `--no-delete` for a
  write-only mode.
- Dropped the numpy dependency.

## Setup

```
pip install -r requirements.txt
```

In your library root (or any folder passed as `--root`):

1. Create `TV` and `Movies` subfolders.
2. Create `movie_vod_urls.txt`:
   ```
   https://tvnow.best/api/list/YOUR_USERNAME/YOUR_PASSWORD/m3u8/movies
   ```
3. Create `tv_vod_urls.txt` with one TV playlist URL per line
   (`.../m3u8/tvshows/1` through `/30`). Lines starting with `#` are ignored,
   so you can stage future URLs commented out.

Note: these files contain your Apollo credentials — keep them out of version
control (this repo's `.gitignore` already excludes them) and off shared drives.

## Run

```
python3 getstreams.py [--root /path/to/library] [--no-delete]
```

Output layout:

```
TV/<show>/<episode>.strm
Movies/<title>/<title>.strm
```

Start with the movies URL and one TV URL, let your media server finish
scanning, then uncomment a few more TV URLs per run. Apollo's full VOD catalog
is ~12k movies and ~115k episodes; the first full library scan takes hours.

Schedule it (cron, launchd, systemd timer) as often as you like — runs are
idempotent and a failed playlist just defers cleanup to the next healthy run.
