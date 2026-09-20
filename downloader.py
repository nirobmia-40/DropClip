"""Core downloading logic for VideoDownloader.

This module contains the networking / extraction / download routines that
were previously embedded in ``app.py``. Behaviour is intentionally
preserved: Pinterest fast-path first (direct MP4 stream), yt-dlp fallback
for everything else.

The UI layer (app.py) imports from here and stays thin.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

ANSI_REGEX = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}

URL_RE = re.compile(r"^https?://[^\s/$.?#].[^\s]*$", re.IGNORECASE)


def clean_ansi(text: str) -> str:
    """Strip ANSI colour codes from yt-dlp helper strings."""
    return ANSI_REGEX.sub("", text or "").strip()


def is_valid_url(url: str) -> bool:
    """Lightweight URL sanity check (scheme + no spaces)."""
    return bool(url and URL_RE.match(url.strip()))


def default_download_dir() -> Path:
    """Portable default download folder (~/Downloads, with fallback)."""
    downloads = Path.home() / "Downloads"
    try:
        downloads.mkdir(parents=True, exist_ok=True)
        return downloads
    except OSError:
        fallback = Path.cwd()
        return fallback


def resource_path(relative: str) -> Path:
    """Resolve bundled resource paths for both source runs and PyInstaller.

    PyInstaller extracts ``--add-data`` files to ``sys._MEIPASS``; fall back
    to the project directory when running from source.
    """
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / relative


# --- Bundled FFmpeg ----------------------------------------------------------
# yt-dlp needs FFmpeg to merge separate video+audio streams into one MP4.
# We ship our own binaries (assets/ffmpeg/) and point yt-dlp at them
# explicitly, so the app never depends on the user's PATH.
FFMPEG_SUBDIR = os.path.join("assets", "ffmpeg")
FFMPEG_EXE_NAME = "ffmpeg.exe"
FFPROBE_EXE_NAME = "ffprobe.exe"

FFMPEG_MISSING_MESSAGE = (
    "FFmpeg is missing from this installation. "
    "Please reinstall the latest version of VideoDownloader."
)


def ffmpeg_dir() -> Path:
    """Absolute directory holding the bundled FFmpeg binaries.

    Source mode  -> ``<project>/assets/ffmpeg``.
    PyInstaller  -> ``<sys._MEIPASS>/assets/ffmpeg``.
    """
    return resource_path(FFMPEG_SUBDIR)


def ffmpeg_exe() -> Path:
    """Absolute path to the bundled ``ffmpeg.exe`` (may not exist)."""
    return ffmpeg_dir() / FFMPEG_EXE_NAME


def ffprobe_exe() -> Path:
    """Absolute path to the bundled ``ffprobe.exe`` (may not exist)."""
    return ffmpeg_dir() / FFPROBE_EXE_NAME


def get_ffmpeg_path() -> str | None:
    """Absolute path to the bundled ``ffmpeg.exe``, or ``None`` if missing.

    Returns the full executable path (yt-dlp also accepts a directory, but
    an explicit file path leaves no room for PATH lookups).
    """
    exe = ffmpeg_exe()
    return str(exe) if exe.is_file() else None


def verify_ffmpeg() -> tuple[bool, str]:
    """Check that both bundled binaries exist.

    Returns ``(True, "")`` when usable, otherwise ``(False, message)``
    with a user-friendly message (no tracebacks, no jargon).
    """
    missing = [
        name
        for name, path in (
            (FFMPEG_EXE_NAME, ffmpeg_exe()),
            (FFPROBE_EXE_NAME, ffprobe_exe()),
        )
        if not path.is_file()
    ]
    if missing:
        log.warning("bundled FFmpeg binaries missing in %s: %s", ffmpeg_dir(), missing)
        return False, FFMPEG_MISSING_MESSAGE
    return True, ""


def get_real_pinterest_url(short_url: str) -> str:
    """Follow redirects (e.g. pin.it) to the canonical page URL."""
    session = requests.Session()
    headers = {
        **BROWSER_HEADERS,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    try:
        response = session.get(short_url, headers=headers, allow_redirects=True, timeout=15)
        return response.url
    except Exception as exc:
        log.debug("redirect resolve failed: %s", exc)
        return short_url


def extract_pinterest_video_deep(page_url: str) -> str | None:
    """Extract the best direct MP4 URL from a Pinterest page.

    Strategy (in order):
    1. ``og:video`` / ``og:video:secure_url`` meta tag ending in .mp4.
    2. Embedded ``__PWS_DATA__`` JSON tree scanned for an .mp4 URL.
    3. ``v.pinimg.com/videos/...mp4`` regex matches (last match wins,
       as it is usually the highest resolution).
    """
    session = requests.Session()
    headers = {
        **BROWSER_HEADERS,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Referer": "https://www.google.com/",
    }

    try:
        resp = session.get(page_url, headers=headers, timeout=20)
        html = resp.text

        # 1. OpenGraph meta tag.
        soup = BeautifulSoup(html, "html.parser")
        og_video = soup.find("meta", property="og:video") or soup.find(
            "meta", property="og:video:secure_url"
        )
        if og_video and og_video.get("content"):
            url = og_video["content"]
            if url.endswith(".mp4"):
                return url

        # 2. Embedded JSON state.
        script_data = soup.find("script", id="__PWS_DATA__")
        if script_data and script_data.string:
            try:
                data = json.loads(script_data.string)

                def search_json(node):
                    if isinstance(node, dict):
                        if "url" in node and isinstance(node["url"], str) and ".mp4" in node["url"]:
                            return node["url"]
                        for value in node.values():
                            found = search_json(value)
                            if found:
                                return found
                    elif isinstance(node, list):
                        for item in node:
                            found = search_json(item)
                            if found:
                                return found
                    return None

                best_url = search_json(data)
                if best_url:
                    return best_url
            except Exception as exc:
                log.debug("PWS JSON parse failed: %s", exc)

        # 3. Direct v.pinimg.com MP4 pattern.
        direct_matches = re.findall(r'https://v\.pinimg\.com/videos/[^\s"\'\\]+\.mp4', html)
        if direct_matches:
            return direct_matches[-1]

    except Exception as exc:
        log.debug("pinterest deep extract failed: %s", exc)

    return None


def direct_mp4_filename(direct_url: str) -> str:
    """Deterministic filename for direct-stream downloads (legacy scheme)."""
    file_id = re.sub(r"[^a-zA-Z0-9]", "", direct_url)[-12:] or "video"
    return f"pinterest_video_{file_id}.mp4"


def friendly_error(message: str) -> str:
    """Map technical/yt-dlp errors to human-friendly one-liners."""
    low = (message or "").lower()
    if not low:
        return "Download failed for an unknown reason."
    if "name resolution" in low or "failed to resolve" in low or "max retries" in low:
        return "Network error. Check your internet connection and try again."
    if "404" in low or "not found" in low:
        return "This link was not found. It may be private, deleted, or incorrect."
    if "403" in low or "forbidden" in low or "login required" in low or "sign in" in low:
        return "Access denied. This content may require login or is private."
    if "unsupported url" in low:
        return "This URL is not supported."
    if "timed out" in low or "timeout" in low:
        return "The connection timed out. Try again."
    if "certificate" in low or "ssl" in low:
        return "Secure connection failed. Check your network / VPN and try again."
    if "no video formats" in low or "no formats" in low:
        return "No downloadable video found at this URL."
    if "ffmpeg" in low and ("not found" in low or "merging" in low):
        return "Downloaded streams could not be merged (ffmpeg missing in this build)."
    # Fallback: first line only, truncated — never a raw traceback.
    first_line = (message or "").strip().splitlines()[0]
    return first_line[:220] if len(first_line) > 220 else first_line


def build_ytdlp_options(output_folder: str | os.PathLike, progress_hook):
    """yt-dlp options (unchanged behaviour: best video+audio merged to mp4).

    ``ffmpeg_location`` points at the bundled binary so merging works on
    machines without FFmpeg installed and without touching PATH.
    """
    outtmpl = str(Path(output_folder) / "%(title).40s [%(id)s].%(ext)s")
    opts = {
        "format": "bestvideo*+bestaudio/best",
        "outtmpl": outtmpl,
        "progress_hooks": [progress_hook],
        "noplaylist": True,
        "merge_output_format": "mp4",
        "nocheckcertificate": True,
        "socket_timeout": 20,
        "quiet": True,
        "no_warnings": True,
        "http_headers": {
            **BROWSER_HEADERS,
            "Referer": "https://www.pinterest.com/",
        },
    }
    ffmpeg = get_ffmpeg_path()
    if ffmpeg is not None:
        opts["ffmpeg_location"] = ffmpeg
    else:
        log.warning("bundled ffmpeg.exe not found; yt-dlp merging may fail")
    return opts
