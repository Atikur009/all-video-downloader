# All Video Downloader

Paste a video link, pick a format (1080p HD, 720p, 480p, Audio MP3, …) and
download in one click. Powered by [yt-dlp](https://github.com/yt-dlp/yt-dlp)
(open source), so it supports YouTube, Facebook, TikTok, Instagram and
hundreds of other sites — as far as the engine supports them.

Free and open source (MIT). No API keys, no paid services, no card needed.

## How it works

- `POST /api/formats` with `{"url": "..."}` returns the video title,
  thumbnail, duration and a format list (combined formats + video-only HD
  formats + an Audio MP3 option).
- `GET /api/download?url=...&format_id=...` downloads the chosen format.
  Combined formats redirect straight to the media URL (nothing is stored
  on the server). Video-only HD formats are merged with ffmpeg
  (bundled via `imageio-ffmpeg`, no system install needed) and streamed
  back; temp files are deleted afterwards.
- One service serves both the page and the API — no separate frontend
  host needed.

## Run locally

```bash
pip install -r requirements.txt
python app.py
# open http://localhost:5000
```

## Deploy on Render (free, ~2 minutes)

1. Push this repo to GitHub (it is already public-ready).
2. On [Render](https://render.com), click **New → Web Service** and
   connect this repository.
3. Render reads `render.yaml` automatically: environment **Python**,
   plan **Free**, build `pip install -r requirements.txt`, start
   `gunicorn app:app --bind 0.0.0.0:$PORT --timeout 600`.
4. Click **Create Web Service**. Your tool is live at
   `https://all-video-downloader.onrender.com` (or the name you chose).

Note: Render's free tier sleeps after inactivity, so the first load after
a while takes ~50 seconds. That is normal, not a bug.

## Honest limits

- Only **public** videos work. Private, login-only, age-restricted or
  removed videos will fail — that is a platform restriction, not a bug.
- Some platforms (especially Instagram and Facebook) change their pages
  often; if a site stops working, updating `yt-dlp` usually fixes it:
  `pip install -U yt-dlp`.
- HD merges (video-only 1080p + audio) take longer than combined formats
  and use more server memory; on the free tier, very long videos may time
  out.
- Download only videos you have the right to save. Do not re-upload
  other people's content.
