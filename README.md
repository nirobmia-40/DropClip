# VideoDownloader

A small, fast desktop app for downloading videos — with first-class Pinterest
support (`pin.it` short links included) and universal fallback for other sites
via yt-dlp. Paste a link, pick a folder, hit download.

Built with Python + tkinter. No browser, no Electron, no bloat.

## Features

- **Pinterest fast path** — resolves `pin.it` short links, extracts the direct
  MP4 stream (`og:video` meta, embedded page data, `v.pinimg.com` URLs) and
  downloads it directly.
- **Universal fallback** — anything the fast path can't handle goes through
  **yt-dlp** (best video + best audio, merged to MP4).
- **Real progress** — percentage, downloaded / total size, speed, and the
  actual filename. No fake progress bars.
- **Save location picker** — defaults to your `Downloads` folder; remembers
  nothing, assumes nothing, works on any Windows machine (portable paths).
- **Cancel anytime** — stops the in-flight download cleanly.
- **Open folder** — one click to open the save location after a download.
- **Human-friendly errors** — invalid URLs, network failures, private/deleted
  links and timeouts are explained in plain language instead of tracebacks.
- **Lightweight** — tkinter UI, three pip dependencies, fast startup.

## Screenshots

> Screenshots coming soon. If you'd like to contribute one, place it in
> `screenshots/` and reference it here.

| Main window | Downloading |
|---|---|
| `screenshots/main.png` | `screenshots/downloading.png` |

## Download

### Windows

**[⬇️ Download VideoDownloader.exe](https://github.com/nirobmia-40/DropClip/releases/tag/v1.0.0)**

No Python required.  
No separate FFmpeg installation required.  
Download → Run → Start downloading.

[View all releases](https://github.com/nirobmia-40/DropClip/releases/tag/v1.0.0)

> The button above pulls `VideoDownloader.exe` straight from the latest
> GitHub Release. If you renamed the release asset, keep it exactly
> `VideoDownloader.exe` or this link will break.

## Run From Source

Requires Python 3.10+ on Windows.

```powershell
# 1. Clone the repository
git clone https://github.com/nirobmia-40/DropClip.git
cd DropClip

# 2. Create and activate a virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the app
python app.py
```

## Build

To produce `dist\VideoDownloader.exe` locally (no console window, icon,
assets and FFmpeg bundled):

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install pyinstaller

# 1. Fetch the pinned FFmpeg Windows binaries into assets/ffmpeg
#    (needed once; ~310 MB, gitignored, never committed)
python tools/fetch_ffmpeg.py

# 2. Build (the whole assets/ folder, including FFmpeg, is bundled)
pyinstaller --noconfirm --clean --onefile --windowed `
  --name VideoDownloader `
  --icon assets/icon.ico `
  --add-data "assets;assets" `
  app.py
```

The executable runs without Python or FFmpeg installed and works outside the
development folder. Official builds are produced by the
[`build-windows.yml`](.github/workflows/build-windows.yml) GitHub Actions
workflow on a `windows-latest` runner (which fetches the same pinned FFmpeg
build — the runner has no FFmpeg preinstalled); the `.exe` is distributed
through **GitHub Releases**, not committed to this repository.

## FFmpeg (bundled)

Merging separate video/audio streams into one MP4 requires FFmpeg, so the
Windows EXE ships its own — users install nothing and nothing is added to
PATH. Details, provenance and redistribution terms live in
[`assets/ffmpeg/README.md`](assets/ffmpeg/README.md):

- Binaries: legitimate [BtbN FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds/releases)
  (FFmpeg n8.1.x, win64, static), fetched reproducibly via
  `python tools/fetch_ffmpeg.py`.
- License: the FFmpeg binaries are **GPLv3** (`assets/ffmpeg/UPSTREAM-LICENSE.txt`,
  also bundled inside the EXE). Keep these notices intact in every release;
  source pointers are in the ffmpeg README. The VideoDownloader app code
  itself stays MIT.

## Project Structure

```
video-downloader/
├── app.py                 # tkinter UI (polished front-end, no download logic)
├── downloader.py          # core engine: Pinterest extraction, yt-dlp options,
│                          #   portable paths, friendly error mapping
├── requirements.txt       # requests, beautifulsoup4, yt-dlp
├── assets/
│   ├── icon.ico           # window + executable icon
│   ├── icon.png           # raster icon
│   ├── icon.svg           # vector source
│   └── ffmpeg/
│       ├── README.md            # provenance + GPL redistribution notes (committed)
│       ├── UPSTREAM-LICENSE.txt # FFmpeg GPL text (committed, also bundled in EXE)
│       ├── ffmpeg.exe           # fetched via tools/fetch_ffmpeg.py (gitignored)
│       └── ffprobe.exe          # fetched via tools/fetch_ffmpeg.py (gitignored)
├── tools/
│   └── fetch_ffmpeg.py    # reproducibly downloads the pinned FFmpeg build
├── .github/
│   └── workflows/
│       └── build-windows.yml   # CI: builds VideoDownloader.exe on Windows
├── LICENSE                # MIT
└── README.md
```

## Responsible Use

VideoDownloader is a tool. You are responsible for complying with applicable
copyright laws, platform Terms of Service, and content permissions when
downloading anything. Only download content you own, that is freely licensed,
or that you have explicit permission to save.

## License

[MIT](LICENSE) — Copyright (c) 2026 Nirob Mia.
# DropClip
