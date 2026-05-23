# Shreddit

Shreddit — Fully automated Reddit-to-YouTube Shorts pipeline. Fetches viral Reddit stories, converts them to speech, renders vertical videos with captions and background gameplay footage, and uploads directly to YouTube. Built in Python with a terminal UI, batch scheduling, multi-channel support, and Discord notifications.

**Pipeline:** Reddit post → TTS audio → 1080×1920 MP4 (background gameplay + captions + Reddit card) → YouTube upload

---

## What It Does

1. **Fetches** the top Reddit post of the week from drama subreddits (or generates a story with Claude AI)
2. **Converts** it to speech using edge-tts (free) or ElevenLabs (premium)
3. **Renders** a vertical 1080×1920 MP4 with:
   - Looping gameplay background (Minecraft, Subway Surfers, etc.)
   - Reddit-style header card showing the post title
   - Karaoke-style captions — 3 words at a time, current word highlighted in yellow
   - Background music mixed at low volume (optional)
4. **Uploads** directly to YouTube with title, tags, description, and scheduled publishing support

---

## Requirements

- **Python 3.8+**
- **ffmpeg** — [download here](https://ffmpeg.org/download.html); add the `/bin` folder to your PATH
- A `videos/` folder with at least one background clip (MP4, MOV, or AVI)
- A `music/` folder with MP3s for background music (optional — pipeline skips it if absent)

---

## Installation

```bash
pip install -r requirements.txt
```

---

## Configuration

Open **`config.py`** — it's the only file you need to edit. All settings are documented inline.

| Setting | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | `""` | Enables AI story generation (`--ai`) and auto-extension of short stories |
| `ELEVENLABS_API_KEY` | `""` | Enables premium TTS. Leave blank to use free edge-tts |
| `MUSIC_VOLUME` | `0.10` | Background music volume (0.0 = off, 1.0 = full) |
| `MIN_WORDS` / `MAX_WORDS` | `150` / `450` | Story length target (≈ 1–3 min at 150 wpm) |
| `EDGE_TTS_VOICE` | Christopher Neural | Free Microsoft TTS voice |
| `CAPTION_Y_POSITION` | `0.72` | Vertical position of captions (0 = top, 1 = bottom) |
| `DEFAULT_SUBREDDITS` | see config | Subreddits available in the picker menu |

---

## YouTube Setup (one-time)

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a project → Enable **YouTube Data API v3**
3. Go to **OAuth consent screen** → set User Type to **External** → fill in the required fields (app name, your email) → Save
4. Under **Test users** → click **Add users** → add your Google account email (required while the app is in Testing mode)
5. Go to **Credentials** → **Create Credentials** → **OAuth 2.0 Client ID** → Desktop App
6. Download the JSON file → rename it `client_secrets.json` → place it in this folder
7. On first upload a browser window will open for you to log in — your token is cached after that in `youtube_token.pkl`

---

## Usage

### Full pipeline (recommended)

```bash
python master.py
```

Walks you through every step interactively: pick a subreddit, watch the video render, confirm the upload, and optionally clean up raw files.

### Run steps individually

```bash
# Step 1 — fetch a story and generate TTS audio
python story_tts.py
python story_tts.py --subreddit tifu
python story_tts.py --ai

# Step 2 — assemble the video
python video_assembly.py --audio output/story_XYZ.mp3 --meta output/story_XYZ.json

# Step 3 — upload to YouTube
python youtube_upload.py
```

---

## Folder Structure

```
automation/
├── config.py              ← edit this to configure everything
├── master.py              ← run this for the full pipeline
├── story_tts.py           ← fetches Reddit story + generates TTS audio
├── video_assembly.py      ← renders the final MP4
├── youtube_upload.py      ← uploads to YouTube
├── requirements.txt
├── client_secrets.json    ← YouTube OAuth credentials (you provide this)
├── youtube_token.pkl      ← cached auth token (auto-created on first login)
│
├── videos/                ← put your background gameplay clips here
│   ├── minecraft.mp4
│   └── subway_surfers.mp4
│
├── music/                 ← optional background music MP3s
│   └── lofi-track.mp3
│
└── output/                ← all generated files land here
    ├── story_XYZ.mp3
    ├── story_XYZ.json
    ├── story_XYZ.txt
    ├── video_story_XYZ.mp4
    └── upload_log.json    ← record of every upload
```

---

## Stats Tracker

`discord_stats.py` pulls the current view count, like count, and comment count for every video in `output/upload_log.json` via the YouTube Data API and posts a formatted embed to a Discord channel.

### Setup

In `config.py`, set one or both webhook URLs:

```python
DISCORD_WEBHOOK_URL   = "https://discord.com/api/webhooks/..."   # post-upload ping
STATS_CHANNEL_WEBHOOK = "https://discord.com/api/webhooks/..."   # stats report (can be the same)
```

### Run manually

```bash
python discord_stats.py
# or via the pipeline entry point:
python master.py --stats
```

### Schedule daily with Windows Task Scheduler

1. Open **Task Scheduler** → **Create Basic Task**
2. Name it (e.g. `YouTube Stats Daily`)
3. Trigger: **Daily** at your preferred time
4. Action: **Start a program**
   - Program: `C:\Path\To\python.exe`
   - Arguments: `C:\Path\To\automation\discord_stats.py`
   - Start in: `C:\Path\To\automation`
5. Finish — the report will arrive in Discord every day automatically

---

## Tips

- **Background videos** — longer clips (5+ minutes) avoid the looping seam. Minecraft parkour and Subway Surfers work well.
- **Music** — tracks are randomly picked per video. Aim for instrumental lo-fi or ambient; anything with lyrics will compete with the narration.
- **Whisper speed** — caption transcription uses the `base` model, which takes ~30 seconds on CPU. Change `"base"` to `"tiny"` in `video_assembly.py` if you want it faster at a slight accuracy cost.
- **Upload log** — `output/upload_log.json` keeps a record of every video ID and URL you've uploaded.
