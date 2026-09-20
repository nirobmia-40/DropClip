# Bundled FFmpeg

VideoDownloader ships its own FFmpeg so normal users never have to install
it or touch their system PATH. The app locates these binaries at runtime via
`get_ffmpeg_path()` in `downloader.py` (works from source and from the
PyInstaller EXE through `sys._MEIPASS`) and passes the path to yt-dlp as
`ffmpeg_location`.

## Provenance (do not replace with an unknown binary)

- **Source:** [BtbN FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds/releases)
  (reputable automated builds of official FFmpeg sources from
  [ffmpeg.org](https://ffmpeg.org)).
- **Pinned build:** `ffmpeg-n8.1.2-54-gc573a95381-win64-gpl-8.1.zip`
  (FFmpeg n8.1.x stable branch, Windows 64-bit, static, GPL).
- **Files used:** `bin/ffmpeg.exe`, `bin/ffprobe.exe`, `LICENSE.txt`
  (saved here as `UPSTREAM-LICENSE.txt`).
- **Fetch:** `python tools/fetch_ffmpeg.py` (run before building).

## Licensing / redistribution

These binaries are **GPL-licensed** (see `UPSTREAM-LICENSE.txt`, GPLv3).
That means every copy of `VideoDownloader.exe` distributed (e.g. via GitHub
Releases) must keep this notice chain intact:

1. This README (provenance + where to get the sources).
2. `UPSTREAM-LICENSE.txt` (the GPL text shipped upstream; also bundled
   inside the EXE via PyInstaller's `assets` data).
3. A pointer to the corresponding source code: official FFmpeg sources at
   https://ffmpeg.org/download.html and the build scripts/config at
   https://github.com/BtbN/FFmpeg-Builds (the binary's `-version` output
   also records the exact configuration).

The VideoDownloader application code itself remains MIT-licensed; the FFmpeg
binaries are an aggregate (separate programs invoked at runtime, not linked
libraries). Do not strip these notice files from releases.

## Repository policy

`ffmpeg.exe` / `ffprobe.exe` (~155 MB each) are **not committed to git**
(see `.gitignore`). CI downloads the pinned build at build time, so every
build is reproducible without bloating the repository.
