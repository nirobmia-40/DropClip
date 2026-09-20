"""Fetch the pinned FFmpeg Windows build for bundling.

Downloads the legitimate upstream FFmpeg binaries (BtbN FFmpeg-Builds,
stable n8.1 branch, GPL static build) and extracts only what the app needs::

    assets/ffmpeg/ffmpeg.exe
    assets/ffmpeg/ffprobe.exe
    assets/ffmpeg/UPSTREAM-LICENSE.txt

The binaries are intentionally NOT committed to git (see .gitignore) --
run this script before building the EXE, locally or in CI::

    python tools/fetch_ffmpeg.py

Stdlib only. If the pinned URL ever rots, update FFMPEG_URL below to a
newer asset from https://github.com/BtbN/FFmpeg-Builds/releases.
"""

from __future__ import annotations

import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

# Pinned, verified build (FFmpeg n8.1.x, win64, static, GPL).
FFMPEG_URL = (
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/"
    "autobuild-2026-09-19-13-11/"
    "ffmpeg-n8.1.2-54-gc573a95381-win64-gpl-8.1.zip"
)
FFMPEG_ZIP_PREFIX = "ffmpeg-n8.1.2-54-gc573a95381-win64-gpl-8.1/"

WANTED = {
    FFMPEG_ZIP_PREFIX + "bin/ffmpeg.exe": "ffmpeg.exe",
    FFMPEG_ZIP_PREFIX + "bin/ffprobe.exe": "ffprobe.exe",
    FFMPEG_ZIP_PREFIX + "LICENSE.txt": "UPSTREAM-LICENSE.txt",
}

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEST_DIR = PROJECT_ROOT / "assets" / "ffmpeg"


def main() -> int:
    DEST_DIR.mkdir(parents=True, exist_ok=True)

    already = all((DEST_DIR / name).is_file() for name in WANTED.values())
    if already and "--force" not in sys.argv:
        print(f"FFmpeg already present in {DEST_DIR}, skipping download.")
        return 0

    print(f"Downloading FFmpeg build:\n  {FFMPEG_URL}")
    with tempfile.TemporaryDirectory(prefix="videodownloader-ffmpeg-") as tmp:
        zip_path = Path(tmp) / "ffmpeg.zip"
        urllib.request.urlretrieve(FFMPEG_URL, zip_path)
        print(f"Downloaded {zip_path.stat().st_size / 1e6:.1f} MB, extracting...")
        with zipfile.ZipFile(zip_path) as archive:
            members = set(archive.namelist())
            for member, out_name in WANTED.items():
                if member not in members:
                    print(f"ERROR: expected member missing from zip: {member}")
                    return 1
                with archive.open(member) as src, open(DEST_DIR / out_name, "wb") as dst:
                    dst.write(src.read())
                print(f"  wrote {DEST_DIR / out_name}")

    print("FFmpeg ready. See assets/ffmpeg/README.md for licensing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
