"""VideoDownloader — polished tkinter front-end.

Workflow (unchanged from the original app):
    1. Paste a URL.
    2. Pick a save location.
    3. Press Download.
    4. Watch real progress.
    5. See a clear success / failure status.

All downloading intelligence lives in :mod:`downloader`; this file is UI only.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, ttk

import requests
import yt_dlp

from downloader import (
    build_ytdlp_options,
    clean_ansi,
    default_download_dir,
    direct_mp4_filename,
    extract_pinterest_video_deep,
    friendly_error,
    get_real_pinterest_url,
    is_valid_url,
    looks_like_ssl_error,
    resource_path,
    verify_ffmpeg,
)

log = logging.getLogger(__name__)

APP_NAME = "DropClip"
APP_TAGLINE = "Paste a link, hit download — that's it."


def _app_version() -> str:
    """Resolve the display version.

    Precedence:
    1. ``assets/version.txt`` — stamped at build time by CI/local build
       (bundled into the EXE via ``--add-data assets``), so the in-app
       version always matches the release tag.
    2. ``APP_VERSION`` environment variable (handy when running from source).
    3. ``"dev"`` fallback.
    """
    try:
        stamped = resource_path(os.path.join("assets", "version.txt"))
        text = Path(stamped).read_text(encoding="utf-8").strip()
        if text:
            return text.lstrip("v")
    except OSError:
        pass
    return os.environ.get("APP_VERSION", "dev").strip().lstrip("v") or "dev"


APP_VERSION = _app_version()

URL_PLACEHOLDER = "Paste video link here  (pin.it, pinterest.com, YouTube, …)"

# --- Restrained dark palette -------------------------------------------------
BG = "#141416"          # window
PANEL = "#1C1D22"       # header / progress card
INPUT_BG = "#202227"    # text fields
BORDER = "#2F3136"      # subtle borders
ACCENT = "#E60023"      # single tasteful accent (download actions)
ACCENT_DARK = "#B8001C"  # accent pressed
ACCENT_HOVER = "#F6123C"  # accent hover
TEXT = "#FFFFFF"
TEXT_DIM = "#DCDDDE"
MUTED = "#8E9297"
SUCCESS = "#57F287"
ERROR = "#ED4245"
WARN = "#FEE75C"

FONT_UI = "Segoe UI"
FONT_MONO = "Consolas"


class Cancelled(Exception):
    """Raised when the user cancels an in-flight download."""


class VideoDownloaderApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME}")
        self.geometry("600x660")
        self.minsize(520, 600)
        self.resizable(True, True)
        self.configure(bg=BG)

        self.is_downloading = False
        self._cancel_event = threading.Event()
        self._status_job = None  # for transient status reset
        self._has_placeholder = True

        try:  # window icon when running from source or bundled exe
            icon = resource_path(os.path.join("assets", "icon.ico"))
            if Path(icon).is_file():
                self.icon_bitmap(str(icon))
        except Exception:
            pass

        self._init_styles()
        self._build_ui()

    # ------------------------------------------------------------------ style
    def _init_styles(self):
        self.style = ttk.Style(self)
        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass
        self.style.configure(
            "Accent.Horizontal.TProgressbar",
            troughcolor="#252730",
            background=ACCENT,
            bordercolor=BG,
            lightcolor=ACCENT,
            darkcolor=ACCENT,
            thickness=8,
        )

    # --------------------------------------------------------------------- ui
    def _build_ui(self):
        self._build_header()
        self._build_form()
        self._build_progress()
        self._build_footer()

    def _build_header(self):
        header = tk.Frame(self, bg=PANEL, padx=20, pady=14)
        header.pack(fill="x")

        title_row = tk.Frame(header, bg=PANEL)
        title_row.pack(fill="x")

        if not self._try_logo(title_row):
            brand = tk.Frame(title_row, bg=PANEL)
            brand.pack(side="left")
            tk.Label(
                brand,
                text="Drop",
                font=(FONT_UI, 15, "bold"),
                fg="#1689FF",
                bg=PANEL,
            ).pack(side="left")
            tk.Label(
                brand,
                text="Clip",
                font=(FONT_UI, 15, "bold"),
                fg="#20C9E8",
                bg=PANEL,
            ).pack(side="left")

        tk.Label(
            title_row,
            text=f"v{APP_VERSION}" if APP_VERSION != "dev" else "dev",
            font=(FONT_UI, 8),
            fg=MUTED,
            bg=PANEL,
        ).pack(side="right", pady=(4, 0))

        tk.Label(
            header,
            text=APP_TAGLINE,
            font=(FONT_UI, 9),
            fg=MUTED,
            bg=PANEL,
        ).pack(anchor="w", pady=(2, 0))

    def _try_logo(self, parent) -> bool:
        """Show ``assets/logo.png`` in the header if present.

        Returns True when the logo was displayed, False to let the caller
        fall back to the text title. Any failure (missing file, bad image)
        is silent — branding must never break startup.
        """
        try:
            logo_path = resource_path(os.path.join("assets", "logo.png"))
            if not Path(logo_path).is_file():
                return False
            image = tk.PhotoImage(file=str(logo_path))
            if image.height() > 48:  # shrink tall artwork to header height
                scale = max(1, (image.height() + 43) // 44)
                image = image.subsample(scale, scale)
            if image.width() > 460:  # guard against ultra-wide artwork
                scale = max(1, (image.width() + 459) // 460)
                image = image.subsample(scale, scale)
            label = tk.Label(parent, image=image, bg=PANEL, bd=0,
                             highlightthickness=0)
            label.pack(side="left")
            self._logo_image = image  # keep a reference or Tk frees it
            return True
        except Exception:
            return False

    def _build_form(self):
        form = tk.Frame(self, bg=BG, padx=24, pady=16)
        form.pack(fill="x")

        # -- URL label + helpers -------------------------------------------
        url_head = tk.Frame(form, bg=BG)
        url_head.pack(fill="x", pady=(0, 6))
        tk.Label(
            url_head, text="Video URL",
            font=(FONT_UI, 9, "bold"), fg=TEXT_DIM, bg=BG,
        ).pack(side="left")
        helpers = tk.Frame(url_head, bg=BG)
        helpers.pack(side="right")
        self._mini_button(helpers, "Paste", self._paste_url).pack(side="left", padx=(0, 6))
        self._mini_button(helpers, "Clear", self._clear_url).pack(side="left")

        self.url_entry = tk.Entry(
            form, bg=INPUT_BG, fg=MUTED, insertbackground=TEXT,
            relief="flat", font=(FONT_UI, 10),
            highlightthickness=1, highlightbackground=BORDER,
            highlightcolor=ACCENT,
        )
        self.url_entry.pack(fill="x", ipady=8)
        self.url_entry.insert(0, URL_PLACEHOLDER)
        self.url_entry.bind("<FocusIn>", self._on_url_focus_in)
        self.url_entry.bind("<FocusOut>", self._on_url_focus_out)
        self.url_entry.bind("<Return>", lambda _e: self._start_download())
        self.url_entry.bind("<KeyRelease>", lambda _e: self._hide_url_error())

        self.url_error = tk.Label(
            form, text="", font=(FONT_UI, 8),
            fg=ERROR, bg=BG, anchor="w",
        )
        self.url_error.pack(fill="x", pady=(4, 10))

        # -- Save location --------------------------------------------------
        tk.Label(
            form, text="Save location",
            font=(FONT_UI, 9, "bold"), fg=TEXT_DIM, bg=BG,
        ).pack(anchor="w", pady=(0, 6))

        path_row = tk.Frame(form, bg=BG)
        path_row.pack(fill="x", pady=(0, 14))
        self.path_entry = tk.Entry(
            path_row, bg=INPUT_BG, fg=TEXT, insertbackground=TEXT,
            relief="flat", font=(FONT_UI, 9),
            highlightthickness=1, highlightbackground=BORDER,
            highlightcolor=ACCENT,
        )
        self.path_entry.pack(side="left", fill="x", expand=True, ipady=7)
        self.path_entry.insert(0, str(default_download_dir()))
        browse = tk.Button(
            path_row, text="Browse", command=self._browse_folder,
            bg="#2B2D31", fg=TEXT_DIM, activebackground="#35373C",
            activeforeground=TEXT, relief="flat", padx=14,
            cursor="hand2", font=(FONT_UI, 9),
        )
        browse.pack(side="right", padx=(8, 0), ipady=3)
        self._add_hover(browse, "#2B2D31", "#35373C")

        # -- Actions ---------------------------------------------------------
        actions = tk.Frame(form, bg=BG)
        actions.pack(fill="x")

        self.action_btn = tk.Button(
            actions, text="⬇   Download", command=self._start_download,
            bg=ACCENT, fg=TEXT, activebackground=ACCENT_DARK,
            activeforeground=TEXT, font=(FONT_UI, 10, "bold"),
            relief="flat", cursor="hand2",
        )
        self.action_btn.pack(side="left", fill="x", expand=True, ipady=9)
        self._add_hover(self.action_btn, ACCENT, ACCENT_HOVER, ACCENT_DARK)

        self.cancel_btn = tk.Button(
            actions, text="Cancel", command=self._cancel_download,
            bg="#2B2D31", fg=MUTED, activebackground="#35373C",
            activeforeground=TEXT, relief="flat", padx=18,
            cursor="hand2", font=(FONT_UI, 9), state="disabled",
        )
        self.cancel_btn.pack(side="right", padx=(8, 0), ipady=7)
        self._add_hover(self.cancel_btn, "#2B2D31", "#35373C")

    def _build_progress(self):
        tk.Frame(self, bg="#27272A", height=1).pack(fill="x", padx=24, pady=(2, 12))

        status = tk.Frame(self, bg=BG, padx=24)
        status.pack(fill="both", expand=True)

        tk.Label(
            status, text="DOWNLOAD PROGRESS",
            font=(FONT_UI, 9, "bold"), fg=MUTED, bg=BG,
        ).pack(anchor="w", pady=(0, 8))

        card = tk.Frame(status, bg=PANEL, padx=14, pady=12,
                        highlightthickness=1, highlightbackground=BORDER)
        card.pack(fill="x")

        # Filename (real info only — hidden until a download starts)
        self.file_lbl = tk.Label(
            card, text="", font=(FONT_UI, 8),
            fg=TEXT_DIM, bg=PANEL, anchor="w",
        )
        self.file_lbl.pack(fill="x", pady=(0, 8))

        self.progress_bar = ttk.Progressbar(
            card, orient="horizontal", mode="determinate",
            style="Accent.Horizontal.TProgressbar",
        )
        self.progress_bar.pack(fill="x", pady=(0, 8))

        stats = tk.Frame(card, bg=PANEL)
        stats.pack(fill="x")
        self.size_speed_lbl = tk.Label(
            stats, text="—", font=(FONT_MONO, 8),
            fg=MUTED, bg=PANEL,
        )
        self.size_speed_lbl.pack(side="left")
        self.percent_lbl = tk.Label(
            stats, text="0%", font=(FONT_MONO, 9, "bold"),
            fg=TEXT, bg=PANEL,
        )
        self.percent_lbl.pack(side="right")

        self.status_lbl = tk.Label(
            status, text="●  Ready",
            font=(FONT_UI, 9), fg=MUTED, bg=BG,
            anchor="w", wraplength=540, justify="left",
        )
        self.status_lbl.pack(fill="x", pady=(10, 0))

        self.detail_lbl = tk.Label(
            status, text="", font=(FONT_UI, 8),
            fg=MUTED, bg=BG, anchor="w",
            wraplength=540, justify="left",
        )
        self.detail_lbl.pack(fill="x", pady=(2, 0))

    def _build_footer(self):
        footer = tk.Frame(self, bg=BG, padx=24, pady=12)
        footer.pack(fill="x", side="bottom")

        tk.Label(
            footer,
            text="Only download content you have the right to save.",
            font=(FONT_UI, 8), fg=MUTED, bg=BG,
        ).pack(side="left")

        self.open_folder_btn = tk.Button(
            footer, text="📁  Open folder", command=self._open_save_folder,
            bg=BG, fg=MUTED, activebackground=PANEL,
            activeforeground=TEXT, relief="flat", cursor="hand2",
            font=(FONT_UI, 8), state="disabled",
        )
        self.open_folder_btn.pack(side="right")

    # ---------------------------------------------------------------- helpers
    def _mini_button(self, parent, text, command):
        btn = tk.Button(
            parent, text=text, command=command,
            bg=BG, fg=MUTED, activebackground=PANEL,
            activeforeground=TEXT, relief="flat", cursor="hand2",
            font=(FONT_UI, 8), padx=4, pady=0,
            highlightthickness=0, bd=0,
        )
        self._add_hover(btn, BG, PANEL)
        return btn

    def _add_hover(self, widget, normal, hover, pressed=None):
        widget.bind("<Enter>", lambda _e: widget.config(bg=hover) if widget["state"] != "disabled" else None)
        widget.bind("<Leave>", lambda _e: widget.config(bg=normal))
        if pressed:
            widget.bind("<ButtonPress-1>", lambda _e: widget.config(bg=pressed) if widget["state"] != "disabled" else None)
            widget.bind("<ButtonRelease-1>", lambda _e: widget.config(bg=hover) if widget["state"] != "disabled" else None)

    # ------------------------------------------------------------- url field
    def _current_url(self) -> str:
        value = self.url_entry.get().strip()
        if self._has_placeholder or value == URL_PLACEHOLDER:
            return ""
        return value

    def _on_url_focus_in(self, _event):
        if self._has_placeholder:
            self.url_entry.delete(0, tk.END)
            self.url_entry.config(fg=TEXT)
            self._has_placeholder = False

    def _on_url_focus_out(self, _event):
        if not self.url_entry.get().strip():
            self.url_entry.insert(0, URL_PLACEHOLDER)
            self.url_entry.config(fg=MUTED)
            self._has_placeholder = True

    def _paste_url(self):
        try:
            text = self.clipboard_get().strip()
        except tk.TclError:
            return
        if text:
            self.url_entry.delete(0, tk.END)
            self.url_entry.insert(0, text)
            self.url_entry.config(fg=TEXT)
            self._has_placeholder = False
            self._hide_url_error()

    def _clear_url(self):
        self.url_entry.delete(0, tk.END)
        self.url_entry.config(fg=MUTED)
        self.url_entry.insert(0, URL_PLACEHOLDER)
        self._has_placeholder = True
        self._hide_url_error()

    def _show_url_error(self, message: str):
        self.url_error.config(text="⚠  " + message)
        self.url_entry.config(highlightbackground=ERROR)

    def _hide_url_error(self):
        self.url_error.config(text="")
        self.url_entry.config(highlightbackground=BORDER)

    # ------------------------------------------------------------------ misc
    def _browse_folder(self):
        folder = filedialog.askdirectory(initialdir=self.path_entry.get().strip() or str(default_download_dir()))
        if folder:
            self.path_entry.delete(0, tk.END)
            self.path_entry.insert(0, folder)

    def _open_save_folder(self):
        folder = self.path_entry.get().strip() or str(default_download_dir())
        try:
            if sys.platform.startswith("win"):
                os.startfile(folder)  # noqa: S606 — local folder chosen by the user
            elif sys.platform == "darwin":
                subprocess.run(["open", folder], check=False)
            else:
                subprocess.run(["xdg-open", folder], check=False)
        except Exception as exc:
            log.debug("open folder failed: %s", exc)

    def _set_status(self, text: str, kind: str = "idle"):
        colors = {"idle": MUTED, "busy": ACCENT, "working": WARN,
                  "ok": SUCCESS, "err": ERROR}
        self.status_lbl.config(text="●  " + text, fg=colors.get(kind, MUTED))

    # -------------------------------------------------------------- download
    def _start_download(self):
        if self.is_downloading:
            return  # accidental double-click guard

        url = self._current_url()
        folder = self.path_entry.get().strip() or str(default_download_dir())

        if not url:
            self._show_url_error("Please paste a video link first.")
            self.url_entry.focus_set()
            return
        if not is_valid_url(url):
            self._show_url_error("That doesn't look like a valid http(s) URL.")
            self.url_entry.focus_set()
            return
        self._hide_url_error()

        try:
            Path(folder).mkdir(parents=True, exist_ok=True)
        except OSError:
            self._set_status("Could not create that save folder.", "err")
            return

        self.is_downloading = True
        self._cancel_event.clear()
        self.action_btn.config(state="disabled", text="⏳  Downloading…", bg="#3A3B41")
        self.cancel_btn.config(state="normal", fg=TEXT_DIM)
        self.open_folder_btn.config(state="disabled")
        self.progress_bar["value"] = 0
        self.percent_lbl.config(text="0%")
        self.size_speed_lbl.config(text="—")
        self.file_lbl.config(text="")
        self.detail_lbl.config(text="")
        self._set_status("Connecting…", "busy")

        threading.Thread(
            target=self._run_download_thread,
            args=(url, folder),
            daemon=True,
        ).start()

    def _cancel_download(self):
        if self.is_downloading:
            self._cancel_event.set()
            self._set_status("Cancelling…", "working")

    def _check_cancelled(self):
        if self._cancel_event.is_set():
            raise Cancelled()

    # -- progress callbacks (called off the UI thread) -----------------------
    def _progress_hook(self, d):
        self._check_cancelled()
        if d.get("status") == "downloading":
            downloaded = d.get("downloaded_bytes", 0) or 0
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            percent = (downloaded / total * 100) if total > 0 else 0.0
            speed = clean_ansi(d.get("_speed_str", "") or "")
            filename = Path(d.get("filename") or d.get("info_dict", {}).get("_filename") or "").name
            self.after(0, self._update_progress, percent, downloaded, total, speed, filename)
        elif d.get("status") == "finished":
            filename = Path(d.get("filename") or "").name
            self.after(0, self._on_finishing, filename)

    def _update_progress(self, percent, downloaded, total, speed, filename=""):
        self.progress_bar["value"] = max(0.0, min(100.0, percent))
        self.percent_lbl.config(text=f"{int(self.progress_bar['value'])}%")
        dl_mb, tot_mb = downloaded / (1024 * 1024), total / (1024 * 1024)
        size = f"{dl_mb:.1f} / {tot_mb:.1f} MB" if total > 0 else f"{dl_mb:.1f} MB"
        self.size_speed_lbl.config(text=f"{size}   •   {speed}" if speed else size)
        if filename:
            short = filename if len(filename) <= 60 else filename[:57] + "…"
            self.file_lbl.config(text=f"📄  {short}")
        self._set_status("Downloading…", "busy")

    def _on_finishing(self, filename=""):
        self.progress_bar["value"] = 100
        self.percent_lbl.config(text="100%")
        if filename:
            short = filename if len(filename) <= 60 else filename[:57] + "…"
            self.file_lbl.config(text=f"📄  {short}")
        self._set_status("Saving video file…", "working")

    # -- worker ---------------------------------------------------------------
    def _download_direct_mp4(self, direct_url: str, output_folder: str, title=None):
        filename = direct_mp4_filename(direct_url, title)
        self.after(0, lambda: self.file_lbl.config(text=f"📄  {filename}"))
        file_path = Path(output_folder) / filename

        headers = {**requests.utils.default_headers()}
        headers["User-Agent"] = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        headers["Referer"] = "https://www.pinterest.com/"

        with requests.get(direct_url, headers=headers, stream=True, timeout=30) as res:
            res.raise_for_status()
            total = int(res.headers.get("content-length", 0) or 0)
            downloaded = 0
            with open(file_path, "wb") as fh:
                for chunk in res.iter_content(chunk_size=1024 * 1024):
                    self._check_cancelled()
                    if not chunk:
                        continue
                    fh.write(chunk)
                    downloaded += len(chunk)
                    pct = (downloaded / total * 100) if total > 0 else 0.0
                    self.after(0, self._update_progress,
                               pct, downloaded, total, "direct", filename)
        return file_path

    def _run_download_thread(self, url, output_folder):
        try:
            Path(output_folder).mkdir(parents=True, exist_ok=True)
            self.after(0, lambda: self._set_status("Resolving link…", "busy"))

            real_url = get_real_pinterest_url(url)

            # Fast path: Pinterest direct MP4 stream.
            if "pinterest.com" in real_url or "pin.it" in url:
                self.after(0, lambda: self._set_status("Finding video stream…", "busy"))
                direct_video, pin_title = extract_pinterest_video_deep(real_url)
                if direct_video:
                    try:
                        self._download_direct_mp4(direct_video, output_folder, pin_title)
                    except Cancelled:
                        raise
                    except Exception as exc:
                        log.debug("direct stream failed, falling back to yt-dlp: %s", exc)
                    else:
                        self.after(0, self._on_complete, True, "Download completed.", "")
                        return

            # General path: yt-dlp (needs the bundled FFmpeg for merging).
            ffmpeg_ok, ffmpeg_problem = verify_ffmpeg()
            if not ffmpeg_ok:
                self.after(0, self._on_complete, False, ffmpeg_problem, "")
                return
            try:
                with yt_dlp.YoutubeDL(build_ytdlp_options(output_folder, self._progress_hook)) as ydl:
                    ydl.download([real_url])
            except Exception as first_err:
                # Targeted fallback: a genuine TLS failure gets ONE retry with
                # certificate verification relaxed (and the user is told).
                # Everything else goes straight to the friendly error mapping.
                if not looks_like_ssl_error(first_err):
                    raise
                log.warning("TLS failure, single retry with nocheckcertificate: %s", first_err)
                self.after(0, lambda: self._set_status(
                    "Secure connection issue — retrying once…", "working"))
                retry_opts = build_ytdlp_options(
                    output_folder, self._progress_hook, nocheckcertificate=True)
                with yt_dlp.YoutubeDL(retry_opts) as ydl:
                    ydl.download([real_url])
            self.after(0, self._on_complete, True, "Download completed.", "")

        except Cancelled:
            self.after(0, self._on_complete, False, "Download cancelled.", "")
        except Exception as exc:
            log.exception("download failed")
            self.after(0, self._on_complete, False, friendly_error(str(exc)), "")

    def _on_complete(self, success: bool, message: str, _detail: str):
        self.is_downloading = False
        self.action_btn.config(state="normal", text="⬇   Download", bg=ACCENT)
        self.cancel_btn.config(state="disabled", fg=MUTED)
        if success:
            self.progress_bar["value"] = 100
            self.percent_lbl.config(text="100%")
            self._set_status(message, "ok")
            self.open_folder_btn.config(state="normal")
            # Brief success flash on the primary button, then back to normal.
            self.action_btn.config(text="✓   Downloaded", bg="#2E7D32")
            self.after(2500, lambda: self.action_btn.config(text="⬇   Download", bg=ACCENT)
                       if not self.is_downloading else None)
        else:
            self._set_status(message, "err")


def main():
    logging.basicConfig(level=logging.WARNING)
    app = VideoDownloaderApp()
    app.mainloop()


if __name__ == "__main__":
    main()
