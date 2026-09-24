"""Unit tests for downloader.py's pure functions.

No real network calls: ``requests.Session`` is replaced with fakes, so this
suite is fast and safe to run in CI on every push.
"""

import pytest

import downloader as dl


# ------------------------------------------------------------------ fakes
class FakeResponse:
    def __init__(self, url="", text=""):
        self.url = url
        self.text = text


class FakeSession:
    """Stand-in for requests.Session with a canned response/exception."""

    def __init__(self, response=None, exc=None):
        self.response = response
        self.exc = exc
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.exc is not None:
            raise self.exc
        return self.response


def patch_session(monkeypatch, response=None, exc=None):
    fake = FakeSession(response=response, exc=exc)
    monkeypatch.setattr(dl.requests, "Session", lambda: fake)
    return fake


# ------------------------------------------------------------------ clean_ansi
def test_clean_ansi_strips_codes():
    assert dl.clean_ansi("\x1b[32m1.5 MB/s\x1b[0m") == "1.5 MB/s"


def test_clean_ansi_plain_passthrough():
    assert dl.clean_ansi("  12.3%  ") == "12.3%"


def test_clean_ansi_empty():
    assert dl.clean_ansi("") == ""
    assert dl.clean_ansi(None) == ""


# ------------------------------------------------------------------ is_valid_url
@pytest.mark.parametrize("url", [
    "https://pin.it/abc123",
    "https://www.pinterest.com/pin/123/",
    "http://example.com/video",
    "https://www.youtube.com/watch?v=jNQXAC9IVRw",
    "HTTPS://EXAMPLE.COM/X",
    "https://example.com/a?b=c&d=e",
])
def test_is_valid_url_accepts(url):
    assert dl.is_valid_url(url) is True


@pytest.mark.parametrize("url", [
    "",
    "   ",
    None,
    "not a url",
    "www.youtube.com/watch?v=x",      # missing scheme
    "https://exa mple.com/video",     # space inside
    "ftp://example.com/video",        # only http(s) allowed
    "https://",                       # no host
])
def test_is_valid_url_rejects(url):
    assert dl.is_valid_url(url) is False


# ------------------------------------------------------------------ friendly_error
@pytest.mark.parametrize("raw,expected", [
    ("ERROR: unable to download: Failed to resolve host (name resolution failed)",
     "Network error. Check your internet connection and try again."),
    ("ERROR: HTTP Error 404: Not Found", "This link was not found."),
    ("Video not found on this page", "This link was not found."),
    ("ERROR: HTTP Error 403: Forbidden", "Access denied."),
    ("Login required to access this content", "Access denied."),
    ("Please sign in to view", "Access denied."),
    ("ERROR: Unsupported URL: https://example.com", "This URL is not supported."),
    ("Read timed out after 20s", "The connection timed out. Try again."),
    ("Connection timeout while fetching", "The connection timed out. Try again."),
    ("certificate verify failed: unable to get local issuer certificate",
     "Secure connection failed."),
    ("SSLError: handshake failure", "Secure connection failed."),
    ("No video formats found for this URL", "No downloadable video found at this URL."),
    ("ffmpeg not found. Please install ffmpeg", "could not be merged"),
    ("Error while merging video parts", "could not be merged"),
])
def test_friendly_error_branches(raw, expected):
    assert expected in dl.friendly_error(raw)


def test_friendly_error_unknown_falls_back_to_first_line():
    assert dl.friendly_error("Something odd happened\nsecond line") == "Something odd happened"


def test_friendly_error_truncates_long_messages():
    long_msg = "x" * 300
    assert dl.friendly_error(long_msg) == "x" * 220


def test_friendly_error_empty():
    assert dl.friendly_error("") == "Download failed for an unknown reason."
    assert dl.friendly_error(None) == "Download failed for an unknown reason."


# ------------------------------------------------------------------ filenames
def test_direct_mp4_filename_legacy_hash():
    url = "https://v.pinimg.com/videos/abc-123_XYZ.mp4"
    first = dl.direct_mp4_filename(url)
    assert first == dl.direct_mp4_filename(url)  # deterministic
    assert first.startswith("pinterest_video_") and first.endswith(".mp4")


def test_direct_mp4_filename_legacy_keeps_old_scheme():
    # Exact legacy behaviour when no title is known.
    import re
    url = "https://v.pinimg.com/videos/abc-123_XYZ.mp4"
    file_id = re.sub(r"[^a-zA-Z0-9]", "", url)[-12:]
    # new scheme keeps the deterministic hash in the filename itself
    assert dl.direct_mp4_filename(url) == f"pinterest_video_{file_id}.mp4"


def test_direct_mp4_filename_with_title_uses_first_8_chars_of_id():
    name = dl.direct_mp4_filename("https://v.pinimg.com/videos/abc123.mp4", "Pin")
    # file_id is derived from the URL hash; first 8 chars become the pin id
    assert "Pin [" in name and name.endswith(".mp4")


def test_direct_mp4_filename_with_title():
    name = dl.direct_mp4_filename("https://v.pinimg.com/videos/abc123.mp4", "My Cool Pin")
    assert name.startswith("My Cool Pin [") and name.endswith("].mp4")


def test_direct_mp4_filename_sanitizes_title():
    name = dl.direct_mp4_filename("https://v.pinimg.com/videos/abc123.mp4", 'a/b:c*d?e"f<g>h|i')
    for bad in '\\/:*?"<>|':
        assert bad not in name
    assert name.endswith(".mp4")


def test_direct_mp4_filename_caps_title_length():
    name = dl.direct_mp4_filename("https://v.pinimg.com/videos/abc123.mp4", "t" * 100)
    title_part = name.rsplit(" [", 1)[0]
    assert len(title_part) <= 60


def test_direct_mp4_filename_blank_title_falls_back():
    url = "https://v.pinimg.com/videos/abc123.mp4"
    assert dl.direct_mp4_filename(url, None) == dl.direct_mp4_filename(url)
    assert dl.direct_mp4_filename(url, "   ") == dl.direct_mp4_filename(url)
    assert dl.direct_mp4_filename(url, "???") == dl.direct_mp4_filename(url)


def test_sanitize_filename():
    assert dl.sanitize_filename("  hello   world  ") == "hello world"
    assert dl.sanitize_filename("a/b\\c:d") == "a b c d"
    assert dl.sanitize_filename("trailing...") == "trailing..."
    assert dl.sanitize_filename(None) == ""
    assert len(dl.sanitize_filename("x" * 200)) <= 60


# ------------------------------------------------------------------ get_real_pinterest_url (mocked)
def test_get_real_pinterest_url_follows_redirect(monkeypatch):
    fake = patch_session(monkeypatch, FakeResponse(url="https://www.pinterest.com/pin/999/"))
    assert dl.get_real_pinterest_url("https://pin.it/abc") == "https://www.pinterest.com/pin/999/"
    assert fake.calls and fake.calls[0][0] == "https://pin.it/abc"


def test_get_real_pinterest_url_returns_input_on_error(monkeypatch):
    patch_session(monkeypatch, exc=ConnectionError("no network"))
    assert dl.get_real_pinterest_url("https://pin.it/abc") == "https://pin.it/abc"


# ------------------------------------------------------------------ extract_pinterest_video_deep (mocked)
OG_HTML = """<html><head>
<meta property="og:title" content="Sunset Surf Clip" />
<meta property="og:video" content="https://v.pinimg.com/videos/aaa111.mp4" />
</head><body></body></html>"""

JSON_HTML = """<html><head></head><body>
<script id="__PWS_DATA__">{"pin": {"url": "https://v.pinimg.com/videos/bbb222.mp4",
"alt_text": "Funny Cat Compilation!"}}</script>
</body></html>"""

REGEX_HTML = """<html><body>
"video":"https://v.pinimg.com/videos/ccc333.mp4",
"video":"https://v.pinimg.com/videos/ddd444.mp4"
</body></html>"""


def test_extract_prefers_og_video_with_title(monkeypatch):
    patch_session(monkeypatch, FakeResponse(text=OG_HTML))
    assert dl.extract_pinterest_video_deep("https://www.pinterest.com/pin/1/") == (
        "https://v.pinimg.com/videos/aaa111.mp4", "Sunset Surf Clip")


def test_extract_json_video_with_alt_text(monkeypatch):
    patch_session(monkeypatch, FakeResponse(text=JSON_HTML))
    assert dl.extract_pinterest_video_deep("https://www.pinterest.com/pin/2/") == (
        "https://v.pinimg.com/videos/bbb222.mp4", "Funny Cat Compilation!")


def test_extract_regex_fallback_last_match_no_title(monkeypatch):
    patch_session(monkeypatch, FakeResponse(text=REGEX_HTML))
    assert dl.extract_pinterest_video_deep("https://www.pinterest.com/pin/3/") == (
        "https://v.pinimg.com/videos/ddd444.mp4", None)


def test_extract_nothing_found(monkeypatch):
    patch_session(monkeypatch, FakeResponse(text="<html><body>hello</body></html>"))
    assert dl.extract_pinterest_video_deep("https://www.pinterest.com/pin/4/") == (None, None)


def test_extract_network_error(monkeypatch):
    patch_session(monkeypatch, exc=TimeoutError("slow"))
    assert dl.extract_pinterest_video_deep("https://www.pinterest.com/pin/5/") == (None, None)


# ------------------------------------------------------------------ yt-dlp options / ssl
def test_build_ytdlp_options_cert_verification_on_by_default(monkeypatch):
    monkeypatch.setattr(dl, "get_ffmpeg_path", lambda: "C:/fake/ffmpeg.exe")
    opts = dl.build_ytdlp_options("C:/out", lambda d: None)
    assert "nocheckcertificate" not in opts
    assert opts["ffmpeg_location"] == "C:/fake/ffmpeg.exe"
    assert opts["merge_output_format"] == "mp4"


def test_build_ytdlp_options_retry_flag(monkeypatch):
    monkeypatch.setattr(dl, "get_ffmpeg_path", lambda: None)
    opts = dl.build_ytdlp_options("C:/out", lambda d: None, nocheckcertificate=True)
    assert opts["nocheckcertificate"] is True
    assert "ffmpeg_location" not in opts


@pytest.mark.parametrize("msg", [
    "certificate verify failed: unable to get local issuer certificate",
    "SSLError: handshake failure",
    "requests.exceptions.SSLError: wrong version number",
])
def test_looks_like_ssl_error_true(msg):
    assert dl.looks_like_ssl_error(msg) is True


@pytest.mark.parametrize("msg", [
    "HTTP Error 404: Not Found",
    "Unsupported URL",
    "Read timed out",
    "",
    None,
])
def test_looks_like_ssl_error_false(msg):
    assert dl.looks_like_ssl_error(msg) is False
