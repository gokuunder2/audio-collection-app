# Mini Audio Collection App

A tiny Flask app for collecting audio submissions (name + phone + a recording),
automatically extracting audio properties, and browsing them.

## What it does

- **Home page (`/`)** — form to enter name + phone, then either **record audio
  live in the browser** (via `MediaRecorder`) or **upload an audio file**.
  On submit, the file is analyzed and stored, and a database row is created.
- **Submissions page (`/submissions`)** — table of every submission with an
  inline `<audio>` play button and the extracted properties. Auto-refreshes
  every 10s.
- For every audio file, the backend extracts:
  - **duration** (seconds)
  - **sample rate** (Hz / kHz)
  - **bitrate** (kbps) — estimated from file size ÷ duration (works for any
    container/codec, not just PCM wav)
  - **loudness** (dBFS, average level relative to full scale)
  - **bonus: a rough noise-floor / SNR quality estimate** — see below

### How the noise/quality estimate works

There's no ground truth "noise" signal to compare against (this isn't a lab
recording), so the app estimates it heuristically:

1. Split the clip into 50ms windows and compute the loudness (dBFS) of each.
2. The quietest ~10% of windows (background between words/breaths) are used
   as a proxy for the **noise floor**.
3. The loudest ~90th percentile of windows are used as a proxy for the
   **signal level**.
4. The gap between them is treated as a rough **SNR estimate** (dB).
5. That maps to a label: `good` (SNR ≥ 30dB), `moderate` (15–30dB), or
   `poor` (< 15dB).

This is intentionally simple (no VAD, no spectral noise modeling) but gives a
useful relative signal: clean, close-mic speech with real pauses scores much
higher than a constant hiss/background-noise recording.

## Tech stack

- **Backend:** Flask + SQLite (stdlib `sqlite3`, zero external DB setup)
- **Audio analysis:** [`pydub`](https://github.com/jiaaro/pydub) (wraps
  `ffmpeg`, so it can read wav/mp3/m4a/webm/ogg/... regardless of what the
  browser or an uploaded file gives it)
- **Frontend:** plain HTML/JS, no build step, no framework

## Project layout

```
app.py                 # Flask app: routes, DB, upload handling
audio_analysis.py      # pydub-based feature extraction
templates/
  index.html            # record/upload form
  submissions.html       # listing view
uploads/                # stored audio files (created automatically)
submissions.db          # SQLite DB (created automatically on first run)
requirements.txt
```

## Run it locally

Requires Python 3.9+ and `ffmpeg` on PATH (pydub needs it to decode
non-wav formats like the webm the browser records).

```bash
# 1. Install ffmpeg if you don't have it
#    macOS:   brew install ffmpeg
#    Ubuntu:  sudo apt-get install ffmpeg
#    Windows: https://ffmpeg.org/download.html (add to PATH)

# 2. Install Python deps
pip install -r requirements.txt

# 3. Run
python app.py
```

Then open **http://localhost:5000** to submit a recording, and
**http://localhost:5000/submissions** to view them.

> Note: browsers only allow microphone access (`getUserMedia`) on
> `localhost` or `https://` — not on plain `http://` over a network IP. For
> local testing that's not an issue; for a public deploy just make sure it's
> served over HTTPS (Render/Railway do this for you automatically).

## Deploying for free

### Option A — Render
1. Push this folder to a GitHub repo.
2. On [render.com](https://render.com) → New → Web Service → connect the repo.
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn app:app`
5. Render gives you an `https://...onrender.com` URL — mic recording will
   work since it's HTTPS.

Render's free tier uses an ephemeral filesystem, so uploaded files and the
SQLite DB will reset on redeploy/restart — fine for a demo, not for
production (swap in S3 + Postgres for that).

### Option B — Railway
1. Push to GitHub, then on [railway.app](https://railway.app) → New Project →
   Deploy from repo.
2. It auto-detects Python; set the start command to `gunicorn app:app`
   (Railway reads `requirements.txt` automatically).
3. Same ephemeral-storage caveat as Render applies.

### Option C — ngrok (quickest for a demo video)
```bash
pip install -r requirements.txt
python app.py
# in another terminal:
ngrok http 5000
```
Use the `https://xxxx.ngrok-free.app` URL ngrok gives you — that's HTTPS,
so mic recording works, and you can record your demo video against it.

## Notes / assumptions

- The database schema here (`submissions` table: name, phone, filename,
  duration, sample_rate, bitrate, loudness, noise/SNR, quality label,
  timestamp) is a self-contained SQLite table for this task. If you want it
  wired into the schema/DB from an earlier "Task 1", swap the `sqlite3`
  calls in `app.py` for your existing DB connection/ORM — the analysis
  logic in `audio_analysis.py` is independent of storage and can feed
  any DB layer.
- Max upload size is capped at 50MB (`MAX_CONTENT_LENGTH`); adjust in
  `app.py` if needed.
- Bitrate is computed as `file_size_bytes * 8 / duration`, which is an
  actual/effective bitrate (correct for both constant- and variable-bitrate
  files) rather than a codec-reported nominal bitrate.
