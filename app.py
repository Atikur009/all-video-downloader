"""All Video Downloader - Flask backend powered by yt-dlp.

Paste a video link -> list formats (HD / 720p / 480p / audio) -> download.
Combined formats redirect straight to the media URL (no server storage).
Video-only HD formats are merged with ffmpeg (imageio-ffmpeg binary) and
streamed back, with temp files cleaned up afterwards.

No secrets, no API keys, no paid services. Free-tier friendly.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

from flask import Flask, after_this_request, jsonify, redirect, request, send_file

app = Flask(__name__, static_folder=".", static_url_path="")

# yt-dlp format ids look like "18", "22", "137", "bestaudio", "137+bestaudio".
FORMAT_ID_RE = re.compile(r"^[A-Za-z0-9_+/\-]+$")
MAX_URL_LEN = 2048
YTDLP_TIMEOUT = 120


def ffmpeg_path():
    """Path to the ffmpeg binary bundled by imageio-ffmpeg (no apt needed)."""
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def run_ytdlp(args, timeout=YTDLP_TIMEOUT, player_client=None, retries=2):
    """Run yt-dlp and return (returncode, stdout, stderr). Never uses a shell.

    Uses `sys.executable -m yt_dlp` so it works regardless of PATH — the
    pip-installed console script is not always on PATH (e.g. under gunicorn).
    `player_client` selects a YouTube player client (e.g. "android") used
    when YouTube's web player bot-blocks datacenter IPs.
    """
    cmd = [sys.executable, "-m", "yt_dlp", "--no-playlist", "--no-warnings",
           "--socket-timeout", "30", "--retries", str(retries)]
    if player_client:
        cmd += ["--extractor-args", "youtube:player_client=%s" % player_client]
    cmd += args
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return 127, "", "yt-dlp is not installed"
    return proc.returncode, proc.stdout, proc.stderr


def is_youtube(url):
    return "youtube.com" in url or "youtu.be" in url


# YouTube player clients tried in order. YouTube's web player often
# bot-blocks datacenter IPs (HTTP 429 / "Sign in to confirm you're not a
# bot"); the Android clients use different player APIs that usually still
# answer. android_music is a full fallback: it returns a complete format
# list where the web and app clients are blocked.
YT_PLAYER_CLIENTS = [None, "android", "android_music"]


def get_info(url):
    """Fetch yt-dlp info JSON. Returns (info_dict_or_None, error_message).

    For YouTube, tries the player clients in YT_PLAYER_CLIENTS order until
    one answers; other sites get a single default-client attempt.
    """
    last_err = ""
    for client in (YT_PLAYER_CLIENTS if is_youtube(url) else [None]):
        try:
            rc, out, err = run_ytdlp(["-J", url], player_client=client)
        except subprocess.TimeoutExpired:
            return None, "Timed out while reading that link. Try again."
        if rc == 0 and out.strip():
            try:
                info = json.loads(out)
            except json.JSONDecodeError:
                return None, "Could not parse video info."
            if info.get("formats"):
                return info, ""
            last_err = "No downloadable formats found for this video."
        else:
            last_err = (err.strip().splitlines() or
                        ["Could not read this video."])[-1]
    if len(last_err) > 300:
        last_err = last_err[:300]
    return None, last_err


def quality_label(res, combined):
    # res = display resolution ("p" number). Landscape 1920x1080 -> 1080p,
    # portrait 1080x1920 (vertical phone video) -> 1080p, not 1920p.
    if res is None:
        return "Audio MP3" if not combined else "Unknown quality"
    label = "%dp" % res
    if res >= 720:
        label += " HD"
    if not combined:
        label += " (video only, merged with audio)"
    return label


def pick_formats(info):
    """Build a clean, de-duplicated format list from yt-dlp info JSON."""
    formats = info.get("formats") or []
    combined = {}    # display res -> best combined format
    video_only = {}  # display res -> best video-only format
    audio_size = None

    for f in formats:
        vcodec = f.get("vcodec") or "none"
        acodec = f.get("acodec") or "none"
        height = f.get("height")
        width = f.get("width")
        size = f.get("filesize") or f.get("filesize_approx")
        if vcodec == "none" and acodec != "none":
            if audio_size is None or (size and size > audio_size):
                audio_size = size
            continue
        if vcodec == "none":
            continue
        res = min(width, height) if (width and height) else height
        entry = {
            "id": str(f.get("format_id")),
            "ext": f.get("ext") or "mp4",
            "filesize": size,
        }
        target = combined if acodec != "none" else video_only
        prev = target.get(res)
        if prev is None or (size and (prev.get("filesize") or 0) < size):
            target[res] = entry

    out = []
    ress = sorted({r for r in list(combined) + list(video_only) if r},
                  reverse=True)
    for r in ress:
        if r in combined:
            e = combined[r]
            out.append({
                "id": e["id"], "label": quality_label(r, True),
                "ext": e["ext"], "filesize": e["filesize"], "combined": True,
            })
        elif r in video_only:
            e = video_only[r]
            out.append({
                "id": e["id"], "label": quality_label(r, False),
                "ext": "mp4", "filesize": e["filesize"], "combined": False,
            })
    # Audio option first-class: best audio converted to MP3 on download.
    out.append({
        "id": "bestaudio", "label": "Audio MP3", "ext": "mp3",
        "filesize": audio_size, "combined": False, "audio_only": True,
    })
    return out


@app.route("/")
def index():
    return send_file("index.html")


@app.route("/api/formats", methods=["POST"])
def api_formats():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url or len(url) > MAX_URL_LEN or not url.startswith(("http://", "https://")):
        return jsonify({"error": "Please paste a valid http(s) video link."}), 400
    info, err = get_info(url)
    if info is None:
        # Hide raw yt-dlp internals from users; keep the detail in server logs.
        print("formats error for %s: %s" % (url, err), flush=True)
        if err.startswith("ERROR:"):
            err = "Couldn't read this video. Please check the link and try another video."
        return jsonify({"error": err}), 422
    return jsonify({
        "title": info.get("title") or "Untitled video",
        "thumbnail": info.get("thumbnail") or "",
        "duration": info.get("duration"),
        "uploader": info.get("uploader") or "",
        "formats": pick_formats(info),
    })


@app.route("/api/download")
def api_download():
    url = (request.args.get("url") or "").strip()
    fmt = (request.args.get("format_id") or "").strip()
    if (not url or len(url) > MAX_URL_LEN
            or not url.startswith(("http://", "https://"))
            or not fmt or len(fmt) > 64 or not FORMAT_ID_RE.match(fmt)):
        return jsonify({"error": "Invalid url or format_id."}), 400

    if fmt == "bestaudio":
        # Fall back to the best combined format when a site exposes no
        # audio-only stream (e.g. YouTube's Android client for some videos);
        # --extract-audio still converts the result to MP3.
        selector, post = "bestaudio/best", True
    elif "+" in fmt:
        return jsonify({"error": "Unsupported format selection."}), 400
    else:
        # Is this format combined? Reuse the info lookup (with fallback).
        info, _ = get_info(url)
        combined = False
        for f in ((info or {}).get("formats") or []):
            if str(f.get("format_id")) == fmt:
                combined = (f.get("vcodec") not in (None, "none")
                            and f.get("acodec") not in (None, "none"))
                break
        if combined:
            media_url = ""
            for client in (YT_PLAYER_CLIENTS if is_youtube(url) else [None]):
                try:
                    rc, out, _ = run_ytdlp(["-f", fmt, "-g", url],
                                           player_client=client)
                except subprocess.TimeoutExpired:
                    return jsonify({"error": "Timed out."}), 504
                if rc == 0 and out.strip():
                    media_url = out.strip().splitlines()[0]
                    break
            if media_url.startswith("http"):
                return redirect(media_url, code=302)
            return jsonify({"error": "Could not resolve a direct download link."}), 422
        selector, post = "%s+bestaudio" % fmt, False

    # Merge / convert path: download to a temp dir, stream back, clean up.
    tmpdir = tempfile.mkdtemp(prefix="avd_")
    try:
        outtmpl = os.path.join(tmpdir, "video.%(ext)s")
        args = ["-f", selector, "--ffmpeg-location", ffmpeg_path(),
                "-o", outtmpl, url]
        if post:
            args += ["--extract-audio", "--audio-format", "mp3"]
        else:
            args += ["--merge-output-format", "mp4"]
        try:
            rc, _, err = 1, "", ""
            for client in (YT_PLAYER_CLIENTS if is_youtube(url) else [None]):
                rc, _, err = run_ytdlp(args, timeout=600, retries=5,
                                       player_client=client)
                if rc == 0:
                    break
        except subprocess.TimeoutExpired:
            shutil.rmtree(tmpdir, ignore_errors=True)
            return jsonify({"error": "Download timed out."}), 504
        files = [os.path.join(tmpdir, f) for f in os.listdir(tmpdir)
                 if not f.endswith(".part")]
        if rc != 0 or not files:
            shutil.rmtree(tmpdir, ignore_errors=True)
            # Hide raw yt-dlp internals from users; keep the detail in logs.
            raw = (err.strip().splitlines() or [""])[-1][:200]
            print("download error for %s fmt %s: %s" % (url, fmt, raw), flush=True)
            return jsonify({"error": "Couldn't download this video. Please try again or pick another quality."}), 422
        path = files[0]
        download_name = "video.mp3" if post else "video.mp4"

        @after_this_request
        def _cleanup(response):
            shutil.rmtree(tmpdir, ignore_errors=True)
            return response

        return send_file(path, as_attachment=True,
                         download_name=download_name)
    except Exception as exc:  # pragma: no cover - safety net
        shutil.rmtree(tmpdir, ignore_errors=True)
        return jsonify({"error": "Server error: %s" % str(exc)[:200]}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
