"""
master.py
---------
Single entry point for the full automation pipeline.

Modes:
  1. Full Automation  — story → audio → video → YouTube upload
  2. Video Uploader   — pick an existing MP4 and upload it
"""

import argparse
import datetime
import glob
import importlib
import json
import os
import random
import re
import sys
import time

os.environ["PYTHONIOENCODING"] = "utf-8"

try:
    from colorama import init, Fore, Style
    init(autoreset=True)
    R, G, Y, C, W, M = Fore.RED, Fore.GREEN, Fore.YELLOW, Fore.CYAN, Fore.WHITE, Fore.MAGENTA
    DIM, B, RS = Style.DIM, Style.BRIGHT, Style.RESET_ALL
except ImportError:
    R = G = Y = C = W = M = DIM = B = RS = ""

from config import CLIENT_SECRETS_FILE, DEFAULT_SUBREDDITS, OUTPUT_DIR, SUBREDDIT_CATEGORIES

BANNER = f"""{R}{B}
#####   ##  ##  #####   ######  ####    ####    ####  ######
##      ##  ##  ##  ##  ##      ##  ##  ##  ##   ##     ##
####    ######  #####   #####   ##  ##  ##  ##   ##     ##
   ##   ##  ##  ## ##   ##      ##  ##  ##  ##   ##     ##
#####   ##  ##  ##  ##  ######  ####    ####    ####    ##
{RS}"""

# ── UI HELPERS ─────────────────────────────────────────────────────────────────

def clear():
    os.system("cls" if os.name == "nt" else "clear")

def print_banner():
    clear()
    print(BANNER)
    print(f"{C}{'=' * 80}{RS}")
    print(f"{W}{B}  Full Automation Pipeline  {RS}{DIM}| Story -> Video -> YouTube{RS}")
    print(f"{C}{'=' * 80}{RS}\n")

def status(msg, kind="info"):
    icons = {"info": f"{C}[*]{RS}", "ok": f"{G}[OK]{RS}", "err": f"{R}[ERR]{RS}",
             "warn": f"{Y}[!]{RS}", "load": f"{M}[..]{RS}"}
    print(f"  {icons.get(kind, '[?]')} {msg}")

def divider(label=""):
    if label:
        pad = (76 - len(label)) // 2
        print(f"\n{C}{'=' * pad} {W}{B}{label}{RS}{C} {'=' * pad}{RS}\n")
    else:
        print(f"\n{C}{'=' * 80}{RS}\n")

def prompt_choice(label, choices):
    print(f"\n  {W}{B}{label}{RS}")
    for i, c in enumerate(choices, 1):
        print(f"    {C}{i}.{RS} {c}")
    while True:
        val = input(f"\n  {Y}>{RS} Pick a number: ").strip().lstrip('﻿')
        if val.isdigit() and 1 <= int(val) <= len(choices):
            return int(val) - 1, choices[int(val) - 1]
        print(f"  {R}Invalid choice, try again.{RS}")


# ── PIPELINE: STORY SOURCE PICKER ──────────────────────────────────────────────

def pick_source():
    """Ask how to get the story; returns (subreddit_or_None, ai_mode_bool)."""
    divider("STEP 1 — STORY SOURCE")

    idx, _ = prompt_choice("How do you want to get the story?", [
        "Auto-pick a random subreddit",
        "Browse subreddits by category",
        "Generate an AI story (requires ANTHROPIC_API_KEY in config.py)",
    ])

    if idx == 0:
        sub = random.choice(DEFAULT_SUBREDDITS)
        status(f"Auto-picked: r/{sub}", "ok")
        return sub, False

    if idx == 1:
        categories = list(SUBREDDIT_CATEGORIES.keys())
        cat_idx, cat_choice = prompt_choice(
            "Choose a category:",
            categories + ["Type a subreddit name directly"],
        )

        if cat_idx == len(categories):
            sub = input(f"  {Y}>{RS} Subreddit name (without r/): ").strip()
        else:
            subs = SUBREDDIT_CATEGORIES[cat_choice]
            sub_idx, sub_choice = prompt_choice(
                f"{cat_choice} — pick a subreddit:",
                [f"r/{s}" for s in subs] + ["Type a subreddit name directly"],
            )
            if sub_idx == len(subs):
                sub = input(f"  {Y}>{RS} Subreddit name (without r/): ").strip()
            else:
                sub = subs[sub_idx]

        status(f"Using: r/{sub}", "ok")
        return sub, False

    status("Using AI story generator", "ok")
    return None, True


# ── PIPELINE: CLEANUP ──────────────────────────────────────────────────────────

def cleanup(audio_path, meta_path):
    """Offer to delete the raw story files (.mp3, .json, .txt), keeping only the MP4."""
    divider("CLEANUP")

    txt_path = os.path.splitext(audio_path)[0] + ".txt"
    files    = [f for f in [audio_path, meta_path, txt_path] if os.path.exists(f)]

    if not files:
        return

    print(f"  {W}Raw files from this run:{RS}")
    for f in files:
        size_kb = os.path.getsize(f) / 1024
        print(f"    {DIM}{os.path.basename(f)}  ({size_kb:.0f} KB){RS}")

    if input(f"\n  {Y}>{RS} Delete these files? (y/n): ").strip().lower() == "y":
        for f in files:
            os.remove(f)
            status(f"Deleted: {os.path.basename(f)}", "ok")
    else:
        status("Keeping raw files.", "info")


# ── MODE 1: FULL AUTOMATION ────────────────────────────────────────────────────

def mode_full_automation():
    import story_tts
    import video_assembly
    import youtube_upload

    while True:
        start_time = time.time()
        print_banner()

        # Step 1 — Story + audio
        subreddit, ai_mode = pick_source()
        divider("STEP 1 — STORY + AUDIO")
        audio_path, meta_path = story_tts.run_story_tts(subreddit=subreddit, ai_mode=ai_mode)
        status(f"Audio : {os.path.basename(audio_path)}", "info")
        status(f"Meta  : {os.path.basename(meta_path)}", "info")

        # Step 2 — Video assembly
        divider("STEP 2 — VIDEO")
        video_path = video_assembly.run_assembly(audio_path, meta_path)
        size_mb = os.path.getsize(video_path) / (1024 * 1024)
        status(f"Video : {os.path.basename(video_path)} ({size_mb:.1f} MB)", "info")

        # Step 3 — Upload
        divider("STEP 3 — YOUTUBE UPLOAD")

        if os.path.exists(meta_path):
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
            meta_title = meta.get("title", "")
            if meta_title:
                status(f"Ready to upload: {meta_title}", "info")
            else:
                status("WARNING: meta JSON exists but 'title' field is empty or missing — you will be prompted to enter one.", "warn")
        else:
            status(f"WARNING: meta file not found at {meta_path} — title/tags will not be pre-filled.", "warn")

        if input(f"\n  {Y}>{RS} Upload to YouTube now? (y/n): ").strip().lower() == "y":
            divider("UPLOADING")
            channel_name, channel_cfg = pick_channel()
            if channel_name:
                status(f"Uploading to: {channel_name}", "info")
            yt = youtube_upload.get_authenticated_service(channel_cfg)
            metadata = youtube_upload.get_metadata(video_path, meta_path=meta_path)
            youtube_upload.upload_video(yt, video_path, metadata)
        else:
            status("Skipping upload.", "warn")
            status(f"Video saved at: {video_path}", "info")

        # Cleanup
        cleanup(audio_path, meta_path)

        elapsed = time.time() - start_time
        divider("DONE")
        status(f"Total time : {int(elapsed // 60)}m {int(elapsed % 60)}s", "ok")
        status(f"Video      : {video_path}", "ok")

        if input(f"\n  {Y}>{RS} Make another video? (y/n): ").strip().lower() != "y":
            break

    print(f"\n  {G}{B}All done! Check your YouTube Studio.{RS}\n")


# ── MODE 2: VIDEO UPLOADER ONLY ────────────────────────────────────────────────

def mode_uploader_only():
    import youtube_upload

    divider("VIDEO UPLOADER")

    channel_name, channel_cfg = pick_channel()
    if channel_name:
        status(f"Channel: {channel_name}", "info")
    yt = youtube_upload.get_authenticated_service(channel_cfg)
    status("Connected to YouTube!", "ok")

    while True:
        video_path = youtube_upload.pick_video()
        metadata   = youtube_upload.get_metadata(video_path)

        divider("CONFIRM UPLOAD")
        print(f"  {C}File:       {RS}{os.path.basename(video_path)}")
        print(f"  {C}Title:      {RS}{metadata['title']}")
        print(f"  {C}Tags:       {RS}{', '.join(metadata['tags'][:5])}")
        print(f"  {C}Visibility: {RS}{metadata['visibility']}")
        if metadata.get("publish_at"):
            print(f"  {C}Scheduled:  {RS}{metadata['publish_at']}")
        print()

        if input(f"  {Y}>{RS} Upload now? (y/n): ").strip().lower() == "y":
            youtube_upload.upload_video(yt, video_path, metadata)
        else:
            status("Upload cancelled.", "warn")

        divider()
        if input(f"  {Y}>{RS} Upload another video? (y/n): ").strip().lower() != "y":
            break

    print(f"\n  {G}{B}Done! Check your YouTube Studio.{RS}\n")


# ── SETTINGS MENU ─────────────────────────────────────────────────────────────

CONFIG_PATH         = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.py")
SCHEDULED_JOBS_FILE = os.path.join(OUTPUT_DIR, "scheduled_jobs.json")
CHANNELS_FILE       = os.path.join(os.path.dirname(os.path.abspath(__file__)), "channels.json")
TOKENS_DIR          = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tokens")


def _load_jobs():
    if not os.path.exists(SCHEDULED_JOBS_FILE):
        return []
    with open(SCHEDULED_JOBS_FILE, encoding="utf-8") as f:
        return json.load(f)


def _save_jobs(jobs):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(SCHEDULED_JOBS_FILE, "w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2)


# ── CHANNEL HELPERS ────────────────────────────────────────────────────────────

def _load_channels():
    """Return {name: cfg_dict} from channels.json, or {} if no channels saved yet."""
    if not os.path.exists(CHANNELS_FILE):
        return {}
    with open(CHANNELS_FILE, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("channels", {})


def _load_channels_default():
    """Return the default channel nickname, or ''."""
    if not os.path.exists(CHANNELS_FILE):
        return ""
    with open(CHANNELS_FILE, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("default", "")


def _save_channels(channels, default=""):
    with open(CHANNELS_FILE, "w", encoding="utf-8") as f:
        json.dump({"channels": channels, "default": default}, f, indent=2)


def _channel_slug(name):
    """Convert a channel nickname to a safe token filename slug."""
    slug = re.sub(r"[^\w\s-]", "", name.lower())
    slug = re.sub(r"[\s-]+", "_", slug).strip("_")
    return slug or "channel"


def pick_channel():
    """Return (channel_name, channel_cfg) for the selected upload target.

    Auto-picks when only one channel is saved. Shows a numbered picker for
    multiple channels. Returns (None, None) when no channels are configured
    (falls back to the legacy single-account TOKEN_FILE flow).
    """
    channels = _load_channels()
    default  = _load_channels_default()

    if not channels:
        return None, None

    if len(channels) == 1:
        name = next(iter(channels))
        status(f"Channel: {name}", "info")
        return name, channels[name]

    names   = list(channels.keys())
    choices = [n + (" [default]" if n == default else "") for n in names]
    idx, _  = prompt_choice("Upload to which channel?", choices)
    name    = names[idx]
    return name, channels[name]


_EDGE_TTS_VOICES = [
    ("en-US-ChristopherNeural", "Christopher  — US Male"),
    ("en-US-GuyNeural",         "Guy          — US Male"),
    ("en-US-EricNeural",        "Eric         — US Male"),
    ("en-US-AriaNeural",        "Aria         — US Female"),
    ("en-US-JennyNeural",       "Jenny        — US Female"),
    ("en-US-MichelleNeural",    "Michelle     — US Female"),
    ("en-GB-RyanNeural",        "Ryan         — UK Male"),
    ("en-GB-SoniaNeural",       "Sonia        — UK Female"),
    ("en-AU-WilliamNeural",     "William      — AU Male"),
    ("en-AU-NatashaNeural",     "Natasha      — AU Female"),
]

_CAPTION_STYLES = [
    ("classic", "Classic  — white text, black stroke, yellow highlight word"),
    ("pill",    "Pill     — white rounded box behind each word"),
    ("allcaps", "Allcaps  — same as Classic but ALL UPPERCASE"),
]


def _reload_cfg():
    """Reload config.py from disk and return the module with fresh values."""
    import config as _c
    importlib.reload(_c)
    return _c


def _set(key, new_value):
    """
    Overwrite the value of `key` in config.py in-place, preserving trailing comments.
    Accepts str, int, and float; strings are written with surrounding quotes.
    """
    if isinstance(new_value, str):
        formatted = f'"{new_value}"'
    else:
        formatted = str(new_value)

    with open(CONFIG_PATH, encoding="utf-8") as f:
        lines = f.readlines()

    pat   = re.compile(rf'^\s*{re.escape(key)}\s*=')
    found = False
    out   = []

    for line in lines:
        if pat.match(line) and not found:
            found = True
            # Scan for a # outside of a quoted string to preserve the comment
            stripped = line.rstrip("\n")
            in_str, hash_pos = False, -1
            for i, ch in enumerate(stripped):
                if ch == '"':
                    in_str = not in_str
                elif ch == '#' and not in_str:
                    hash_pos = i
                    break
            comment = ("   " + stripped[hash_pos:]) if hash_pos >= 0 else ""
            m       = re.match(rf'^\s*{re.escape(key)}\s*=\s*', line)
            prefix  = m.group(0) if m else f"{key} = "
            out.append(f"{prefix}{formatted}{comment}\n")
        else:
            out.append(line)

    if not found:
        status(f"Setting '{key}' not found in config.py", "err")
        return False

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        f.writelines(out)

    status(f"Saved  {key} = {formatted}", "ok")
    return True


def _mask(val):
    """Masked display string for an API key or webhook URL."""
    if not val:
        return f"{R}not set{RS}"
    if len(val) > 12:
        return f"{G}{val[:6]}...{val[-4:]}{RS}"
    return f"{G}set{RS}"


# ── SETTINGS: INDIVIDUAL SCREENS ───────────────────────────────────────────────

def settings_voice():
    cfg = _reload_cfg()
    divider("TTS VOICE")
    print(f"  {DIM}Current: {cfg.EDGE_TTS_VOICE}{RS}\n")

    choices = [label for _, label in _EDGE_TTS_VOICES] + ["Keep current / cancel"]
    idx, _  = prompt_choice("Choose a voice:", choices)

    if idx < len(_EDGE_TTS_VOICES):
        _set("EDGE_TTS_VOICE", _EDGE_TTS_VOICES[idx][0])
    else:
        status("No change.", "info")


def settings_tts_rate():
    cfg = _reload_cfg()
    divider("TTS RATE")
    print(f"  {DIM}Current: {cfg.TTS_RATE}")
    print(f"  Controls speech speed relative to the voice default.")
    print(f"  Examples:  +10%  (faster)   -10%  (slower)   +0%  (normal){RS}\n")

    raw = input(f"  {Y}>{RS} New rate (e.g. +10%, -5%, +0%), or Enter to cancel: ").strip()
    if not raw:
        status("No change.", "info")
        return

    try:
        n         = int(raw.replace("%", "").strip())
        formatted = f"+{n}%" if n >= 0 else f"{n}%"
        _set("TTS_RATE", formatted)
    except ValueError:
        status("Invalid — enter a value like +15%, -10%, or +0%.", "err")


def settings_caption_style():
    cfg = _reload_cfg()
    divider("CAPTION STYLE")
    print(f"  {DIM}Current: {cfg.CAPTION_STYLE}{RS}\n")

    choices = [label for _, label in _CAPTION_STYLES] + ["Keep current / cancel"]
    idx, _  = prompt_choice("Choose a style:", choices)

    if idx < len(_CAPTION_STYLES):
        _set("CAPTION_STYLE", _CAPTION_STYLES[idx][0])
    else:
        status("No change.", "info")


def settings_music_volume():
    cfg = _reload_cfg()
    divider("MUSIC VOLUME")
    print(f"  {DIM}Current: {cfg.MUSIC_VOLUME}   (0.0 = off, 1.0 = full volume){RS}\n")

    raw = input(f"  {Y}>{RS} New volume (0.0 – 1.0), or Enter to cancel: ").strip()
    if not raw:
        status("No change.", "info")
        return
    try:
        val = float(raw)
        if not 0.0 <= val <= 1.0:
            raise ValueError
        _set("MUSIC_VOLUME", val)
    except ValueError:
        status("Invalid — enter a number between 0.0 and 1.0.", "err")


def settings_story_length():
    cfg = _reload_cfg()
    divider("STORY LENGTH")
    print(f"  {DIM}Current: MIN_WORDS={cfg.MIN_WORDS}  MAX_WORDS={cfg.MAX_WORDS}")
    print(f"  150 wpm → 150 words ≈ 1 min  |  450 words ≈ 3 min{RS}\n")

    raw_min = input(f"  {Y}>{RS} MIN_WORDS  (Enter to keep {cfg.MIN_WORDS}): ").strip()
    raw_max = input(f"  {Y}>{RS} MAX_WORDS  (Enter to keep {cfg.MAX_WORDS}): ").strip()

    new_min = int(raw_min) if raw_min.isdigit() else cfg.MIN_WORDS
    new_max = int(raw_max) if raw_max.isdigit() else cfg.MAX_WORDS

    if new_min >= new_max:
        status("MIN_WORDS must be less than MAX_WORDS — no change made.", "err")
        return

    if raw_min.isdigit():
        _set("MIN_WORDS", new_min)
    if raw_max.isdigit():
        _set("MAX_WORDS", new_max)
    if not raw_min and not raw_max:
        status("No change.", "info")


def settings_upvote_filter():
    cfg = _reload_cfg()
    divider("UPVOTE FILTER")
    print(f"  {DIM}Current: MIN_UPVOTES={cfg.MIN_UPVOTES}  MAX_UPVOTES={cfg.MAX_UPVOTES}")
    print(f"  Posts outside this score range are skipped when fetching from Reddit.{RS}\n")

    raw_min = input(f"  {Y}>{RS} MIN_UPVOTES  (Enter to keep {cfg.MIN_UPVOTES}): ").strip()
    raw_max = input(f"  {Y}>{RS} MAX_UPVOTES  (Enter to keep {cfg.MAX_UPVOTES}): ").strip()

    new_min = int(raw_min) if raw_min.isdigit() else cfg.MIN_UPVOTES
    new_max = int(raw_max) if raw_max.isdigit() else cfg.MAX_UPVOTES

    if new_min >= new_max:
        status("MIN_UPVOTES must be less than MAX_UPVOTES — no change made.", "err")
        return

    if raw_min.isdigit():
        _set("MIN_UPVOTES", new_min)
    if raw_max.isdigit():
        _set("MAX_UPVOTES", new_max)
    if not raw_min and not raw_max:
        status("No change.", "info")


def settings_api_keys():
    cfg = _reload_cfg()
    divider("API KEYS")
    print(f"  {DIM}Press Enter to keep the current value. Type 'clear' to remove a key.{RS}\n")

    for key, attr in [
        ("ANTHROPIC_API_KEY",  "ANTHROPIC_API_KEY"),
        ("ELEVENLABS_API_KEY", "ELEVENLABS_API_KEY"),
    ]:
        current = getattr(cfg, attr, "")
        print(f"  {W}{key}{RS}  [{_mask(current)}]")
        raw = input(f"  {Y}>{RS} New value: ").strip()
        if raw.lower() == "clear":
            _set(key, "")
        elif raw:
            _set(key, raw)
        print()


def settings_discord():
    cfg = _reload_cfg()
    divider("DISCORD WEBHOOKS")
    print(f"  {DIM}Press Enter to keep. Type 'clear' to remove. Both can point to the same URL.{RS}\n")

    for key, attr, label in [
        ("DISCORD_WEBHOOK_URL",   "DISCORD_WEBHOOK_URL",   "Post-upload ping"),
        ("STATS_CHANNEL_WEBHOOK", "STATS_CHANNEL_WEBHOOK", "Daily stats report"),
    ]:
        current = getattr(cfg, attr, "")
        print(f"  {W}{label}{RS}  ({key})  [{_mask(current)}]")
        raw = input(f"  {Y}>{RS} New URL: ").strip()
        if raw.lower() == "clear":
            _set(key, "")
        elif raw:
            _set(key, raw)
        print()


def settings_test_discord():
    import requests
    cfg = _reload_cfg()
    divider("TEST DISCORD WEBHOOKS")

    targets = [
        ("DISCORD_WEBHOOK_URL",   cfg.DISCORD_WEBHOOK_URL,   "Post-upload ping"),
        ("STATS_CHANNEL_WEBHOOK", cfg.STATS_CHANNEL_WEBHOOK, "Stats report channel"),
    ]

    # De-duplicate so we don't double-post when both point at the same URL
    seen = set()
    for key, url, label in targets:
        if not url:
            status(f"{key} is not set — skipping.", "warn")
            continue
        if url in seen:
            status(f"{key} points to the same webhook as above — skipping duplicate.", "info")
            continue
        seen.add(url)

        print(f"\n  {DIM}Sending test to {label} ({key})...{RS}")
        try:
            resp = requests.post(
                url,
                json={"embeds": [{
                    "title":       "✅ Test Message",
                    "description": f"Webhook `{key}` is working correctly!",
                    "color":       0x00CC44,
                }]},
                timeout=10,
            )
            if resp.status_code in (200, 204):
                status(f"{label} — OK ({resp.status_code})", "ok")
            else:
                status(f"{label} — failed: HTTP {resp.status_code}  {resp.text[:120]}", "err")
        except Exception as e:
            status(f"{label} — error: {e}", "err")

    print()
    input(f"  {Y}>{RS} Press Enter to return... ")


def settings_run_stats():
    divider("RUN STATS REPORT NOW")
    cfg = _reload_cfg()

    if not cfg.STATS_CHANNEL_WEBHOOK:
        status("STATS_CHANNEL_WEBHOOK is not set — go to Discord Webhooks to add it.", "warn")
        input(f"\n  {Y}>{RS} Press Enter to return... ")
        return

    print()
    import discord_stats
    discord_stats.run_stats_report()
    print()
    input(f"  {Y}>{RS} Press Enter to return... ")


def settings_view_all():
    cfg = _reload_cfg()
    divider("ALL CURRENT SETTINGS")

    col  = 26
    rows = [
        ("TTS Voice",             cfg.EDGE_TTS_VOICE),
        ("TTS Rate",              cfg.TTS_RATE),
        ("Caption Style",         cfg.CAPTION_STYLE),
        ("Music Volume",          cfg.MUSIC_VOLUME),
        ("Min Words",             cfg.MIN_WORDS),
        ("Max Words",             cfg.MAX_WORDS),
        ("Min Upvotes",           cfg.MIN_UPVOTES),
        ("Max Upvotes",           cfg.MAX_UPVOTES),
        ("Hook Duration (s)",     cfg.HOOK_DURATION),
        ("ANTHROPIC_API_KEY",     _mask(cfg.ANTHROPIC_API_KEY)),
        ("ELEVENLABS_API_KEY",    _mask(cfg.ELEVENLABS_API_KEY)),
        ("DISCORD_WEBHOOK_URL",   "set" if cfg.DISCORD_WEBHOOK_URL   else f"{R}not set{RS}"),
        ("STATS_CHANNEL_WEBHOOK", "set" if cfg.STATS_CHANNEL_WEBHOOK else f"{R}not set{RS}"),
        ("Default Upload Time",    getattr(cfg, "DEFAULT_UPLOAD_TIME",   "14:00")),
        ("Default Batch Size",    getattr(cfg, "DEFAULT_BATCH_SIZE",    1)),
        ("Upload Interval (days)", getattr(cfg, "UPLOAD_INTERVAL_DAYS", 1)),
        ("Default YT Category",   getattr(cfg, "DEFAULT_YT_CATEGORY",  "24")),
    ]

    print(f"  {W}{'Setting':<{col}} Value{RS}")
    print(f"  {DIM}{'-' * 55}{RS}")
    for label, val in rows:
        print(f"  {C}{label:<{col}}{RS}{val}")

    print()
    input(f"  {Y}>{RS} Press Enter to return... ")


# ── SETTINGS: MANAGE CHANNELS ─────────────────────────────────────────────────

def _channels_add():
    import youtube_upload
    divider("ADD CHANNEL")

    channels = _load_channels()
    default  = _load_channels_default()

    name = input(f"  {Y}>{RS} Channel nickname (e.g. 'Drama Channel'): ").strip()
    if not name:
        status("No nickname entered — cancelled.", "warn")
        return
    if name in channels:
        status(f"A channel named '{name}' already exists.", "err")
        return

    slug        = _channel_slug(name)
    token_file  = os.path.join("tokens", f"{slug}_token.pkl")
    channel_cfg = {"token_file": token_file, "client_secrets": CLIENT_SECRETS_FILE}

    os.makedirs(TOKENS_DIR, exist_ok=True)
    status(f"Opening browser for Google login — sign in as the '{name}' account...", "load")
    try:
        youtube_upload.get_authenticated_service(channel_cfg)
        channels[name] = channel_cfg
        if not default:
            default = name   # first channel becomes the default automatically
        _save_channels(channels, default)
        status(f"Channel '{name}' authenticated and saved.", "ok")
        status(f"Token stored at: {token_file}", "info")
    except Exception as exc:
        status(f"Authentication failed: {exc}", "err")


def _channels_remove():
    divider("REMOVE CHANNEL")
    channels = _load_channels()
    default  = _load_channels_default()

    if not channels:
        status("No channels configured yet.", "warn")
        input(f"\n  {Y}>{RS} Press Enter to go back... ")
        return

    names  = list(channels.keys())
    idx, _ = prompt_choice("Which channel to remove?", names + ["Cancel"])

    if idx == len(names):
        status("No change.", "info")
        return

    name       = names[idx]
    token_file = channels[name].get("token_file", "")

    confirm = input(f"  {Y}>{RS} Remove '{name}' and delete its token file? (y/n): ").strip().lower()
    if confirm != "y":
        status("No change.", "info")
        return

    del channels[name]
    if default == name:
        default = next(iter(channels), "")
    _save_channels(channels, default)

    if token_file and os.path.exists(token_file):
        try:
            os.remove(token_file)
            status(f"Deleted token: {token_file}", "ok")
        except Exception as exc:
            status(f"Could not delete token file: {exc}", "warn")

    status(f"Channel '{name}' removed.", "ok")


def _channels_list():
    divider("SAVED CHANNELS")
    channels = _load_channels()
    default  = _load_channels_default()

    if not channels:
        print(f"  {DIM}No channels configured yet.")
        print(f"  Use 'Add a channel' to get started.{RS}\n")
    else:
        for name, cfg in channels.items():
            token_ok = os.path.exists(cfg.get("token_file", ""))
            tag      = f" {G}[default]{RS}" if name == default else ""
            auth     = f" {G}authenticated{RS}" if token_ok else f" {R}token missing{RS}"
            print(f"  {C}{name}{RS}{tag}{auth}")
            print(f"    {DIM}token: {cfg.get('token_file', '?')}{RS}")
        print()

    input(f"  {Y}>{RS} Press Enter to go back... ")


def _channels_set_default():
    divider("SET DEFAULT CHANNEL")
    channels = _load_channels()
    default  = _load_channels_default()

    if not channels:
        status("No channels configured yet.", "warn")
        input(f"\n  {Y}>{RS} Press Enter to go back... ")
        return

    names   = list(channels.keys())
    choices = [n + (" [current default]" if n == default else "") for n in names]
    idx, _  = prompt_choice("Set as default:", choices + ["Cancel"])

    if idx == len(names):
        status("No change.", "info")
        return

    new_default = names[idx]
    _save_channels(channels, new_default)
    status(f"Default channel set to: {new_default}", "ok")


def settings_manage_channels():
    _sub = [
        ("Add a channel",       _channels_add),
        ("Remove a channel",    _channels_remove),
        ("List all channels",   _channels_list),
        ("Set default channel", _channels_set_default),
    ]
    while True:
        channels = _load_channels()
        default  = _load_channels_default()
        divider("MANAGE CHANNELS")
        if not channels:
            print(f"  {DIM}No channels configured yet. Use 'Add a channel' to get started.{RS}\n")
        else:
            print(f"  {DIM}{len(channels)} channel(s) saved. Default: {default or 'none set'}{RS}\n")

        menu_labels = [label for label, _ in _sub] + ["Back to Settings"]
        idx, _      = prompt_choice("Channel management:", menu_labels)

        if idx < len(_sub):
            _sub[idx][1]()
        else:
            break


# ── SETTINGS: SCHEDULER SUB-MENU ──────────────────────────────────────────────

def settings_scheduler_upload_time():
    cfg = _reload_cfg()
    current = getattr(cfg, "DEFAULT_UPLOAD_TIME", "14:00")
    divider("DEFAULT UPLOAD TIME")
    print(f"  {DIM}Current: {current}")
    print(f"  Pre-filled as the default when running the Auto Scheduler.{RS}\n")
    while True:
        raw = input(f"  {Y}>{RS} New default time (HH:MM, 24hr), or Enter to cancel: ").strip()
        if not raw:
            status("No change.", "info")
            return
        try:
            datetime.datetime.strptime(raw, "%H:%M")
            _set("DEFAULT_UPLOAD_TIME", raw)
            return
        except ValueError:
            print(f"  {R}  Invalid — use HH:MM format (e.g. 14:00).{RS}")


def settings_scheduler_batch_size():
    cfg = _reload_cfg()
    current = getattr(cfg, "DEFAULT_BATCH_SIZE", 1)
    divider("DEFAULT VIDEOS PER BATCH")
    print(f"  {DIM}Current: {current}")
    print(f"  How many videos the Auto Scheduler generates per run.{RS}\n")
    while True:
        raw = input(f"  {Y}>{RS} New batch size (1–10), or Enter to cancel: ").strip()
        if not raw:
            status("No change.", "info")
            return
        if raw.isdigit() and 1 <= int(raw) <= 10:
            _set("DEFAULT_BATCH_SIZE", int(raw))
            return
        print(f"  {R}  Enter a number between 1 and 10.{RS}")


def settings_scheduler_interval():
    cfg = _reload_cfg()
    current = getattr(cfg, "UPLOAD_INTERVAL_DAYS", 1)
    divider("UPLOAD INTERVAL")
    print(f"  {DIM}Current: every {current} day(s)")
    print(f"  Days between each upload in a batch.")
    print(f"  Example: 2 = video 1 today, video 2 in 2 days, video 3 in 4 days.{RS}\n")
    while True:
        raw = input(f"  {Y}>{RS} New interval in days (1–30), or Enter to cancel: ").strip()
        if not raw:
            status("No change.", "info")
            return
        if raw.isdigit() and 1 <= int(raw) <= 30:
            _set("UPLOAD_INTERVAL_DAYS", int(raw))
            return
        print(f"  {R}  Enter a number between 1 and 30.{RS}")


def settings_scheduler_view():
    divider("SCHEDULED UPLOADS")
    jobs = _load_jobs()
    if not jobs:
        print(f"  {DIM}No scheduled uploads on record.{RS}\n")
        input(f"  {Y}>{RS} Press Enter to go back... ")
        return

    pending   = [j for j in jobs if j.get("status") == "pending"]
    done      = [j for j in jobs if j.get("status") == "done"]
    failed    = [j for j in jobs if j.get("status") == "failed"]
    cancelled = [j for j in jobs if j.get("status") == "cancelled"]

    if pending:
        print(f"  {Y}Pending ({len(pending)}):{RS}")
        for j in pending:
            print(f"    {C}{j['slot']}.{RS} {j['video'][:44]:<46} {j['scheduled_at']}")
    if done:
        print(f"\n  {G}Completed ({len(done)}):{RS}")
        for j in done:
            url = j.get("url", "")
            print(f"    {C}{j['slot']}.{RS} {j['video'][:44]:<46} {url or j['scheduled_at']}")
    if failed:
        print(f"\n  {R}Failed ({len(failed)}):{RS}")
        for j in failed:
            print(f"    {C}{j['slot']}.{RS} {j['video'][:44]:<46} {j['scheduled_at']}")
    if cancelled:
        print(f"\n  {DIM}Cancelled ({len(cancelled)}):{RS}")
        for j in cancelled:
            print(f"    {C}{j['slot']}.{RS} {j['video'][:44]:<46} {j['scheduled_at']}")

    print()
    input(f"  {Y}>{RS} Press Enter to go back... ")


def settings_scheduler_cancel():
    divider("CANCEL SCHEDULED UPLOADS")
    jobs    = _load_jobs()
    pending = [j for j in jobs if j.get("status") == "pending"]
    if not pending:
        print(f"  {DIM}No pending uploads to cancel.{RS}\n")
        input(f"  {Y}>{RS} Press Enter to go back... ")
        return

    print(f"  {Y}The following {len(pending)} pending upload(s) will be cancelled:{RS}\n")
    for j in pending:
        print(f"    {C}{j['slot']}.{RS} {j['video'][:44]:<46} {j['scheduled_at']}")
    print()

    if input(f"  {Y}>{RS} Cancel all pending uploads? (y/n): ").strip().lower() == "y":
        for j in jobs:
            if j.get("status") == "pending":
                j["status"] = "cancelled"
        _save_jobs(jobs)
        status(f"Cancelled {len(pending)} pending upload(s).", "ok")
    else:
        status("No change.", "info")


def settings_scheduler():
    _sub = [
        ("Set Default Upload Time",       settings_scheduler_upload_time),
        ("Set Default Videos Per Batch",  settings_scheduler_batch_size),
        ("Set Upload Interval",           settings_scheduler_interval),
        ("View Scheduled Uploads",        settings_scheduler_view),
        ("Cancel All Scheduled Uploads",  settings_scheduler_cancel),
    ]
    while True:
        cfg      = _reload_cfg()
        time_val = getattr(cfg, "DEFAULT_UPLOAD_TIME", "14:00")
        size_val = getattr(cfg, "DEFAULT_BATCH_SIZE", 1)
        intv_val = getattr(cfg, "UPLOAD_INTERVAL_DAYS", 1)
        divider("SCHEDULER SETTINGS")
        print(
            f"  {DIM}Default time: {time_val}  |  "
            f"Batch size: {size_val}  |  "
            f"Interval: every {intv_val} day(s){RS}\n"
        )
        menu_labels = [label for label, _ in _sub] + ["Back to Settings"]
        idx, _      = prompt_choice("Scheduler settings:", menu_labels)
        if idx < len(_sub):
            _sub[idx][1]()
        else:
            break


# ── SETTINGS: MAIN LOOP ────────────────────────────────────────────────────────

def mode_settings():
    _actions = [
        ("TTS Voice",                        settings_voice),
        ("TTS Rate   (speech speed)",        settings_tts_rate),
        ("Caption Style",                    settings_caption_style),
        ("Music Volume",                     settings_music_volume),
        ("Story Length   (MIN / MAX words)", settings_story_length),
        ("Upvote Filter  (MIN / MAX score)", settings_upvote_filter),
        ("API Keys       (Anthropic, ElevenLabs)", settings_api_keys),
        ("Discord Webhooks",                 settings_discord),
        ("Test Discord Webhooks",            settings_test_discord),
        ("Run Stats Report Now",             settings_run_stats),
        ("Manage Channels",                  settings_manage_channels),
        ("Scheduler Settings",               settings_scheduler),
        ("View All Settings",                settings_view_all),
    ]

    while True:
        cfg = _reload_cfg()
        divider("SETTINGS")
        print(
            f"  {DIM}Voice: {cfg.EDGE_TTS_VOICE}  |  "
            f"Style: {cfg.CAPTION_STYLE}  |  "
            f"Volume: {cfg.MUSIC_VOLUME}  |  "
            f"Words: {cfg.MIN_WORDS}–{cfg.MAX_WORDS}{RS}\n"
        )

        menu_labels = [label for label, _ in _actions] + ["Back to Main Menu"]
        idx, _      = prompt_choice("What would you like to change?", menu_labels)

        if idx < len(_actions):
            _actions[idx][1]()
        else:
            break


# ── MODE 4: AUTO SCHEDULER ────────────────────────────────────────────────────

def mode_auto_scheduler():
    import story_tts
    import video_assembly
    import youtube_upload

    # Ensure APScheduler is available, installing it on first run if needed
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.date import DateTrigger
    except ImportError:
        status("APScheduler not installed — installing now...", "load")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "apscheduler", "-q"])
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.date import DateTrigger

    # ── Inputs ────────────────────────────────────────────────────────────────
    divider("AUTO SCHEDULER — SETUP")
    cfg = _reload_cfg()

    default_n = getattr(cfg, "DEFAULT_BATCH_SIZE", 1)
    while True:
        raw = input(f"  {Y}>{RS} How many videos to generate? (1–10) [{default_n}]: ").strip()
        if not raw:
            num_videos = default_n
            break
        if raw.isdigit() and 1 <= int(raw) <= 10:
            num_videos = int(raw)
            break
        print(f"  {R}  Enter a number between 1 and 10.{RS}")

    default_t = getattr(cfg, "DEFAULT_UPLOAD_TIME", "14:00")
    while True:
        raw = input(f"  {Y}>{RS} Upload time each day (HH:MM, 24hr) [{default_t}]: ").strip()
        if not raw:
            raw = default_t
        try:
            upload_time = datetime.datetime.strptime(raw, "%H:%M").time()
            break
        except ValueError:
            print(f"  {R}  Invalid — use HH:MM format (e.g. 14:00).{RS}")

    today = datetime.date.today()
    while True:
        raw = input(f"  {Y}>{RS} Start date (YYYY-MM-DD, 'today', or 'tomorrow'): ").strip().lower()
        if raw == "today":
            start_date = today
            break
        elif raw == "tomorrow":
            start_date = today + datetime.timedelta(days=1)
            break
        else:
            try:
                start_date = datetime.date.fromisoformat(raw)
                break
            except ValueError:
                print(f"  {R}  Invalid — use YYYY-MM-DD or 'today'/'tomorrow'.{RS}")

    # ── YouTube category picker ───────────────────────────────────────────────
    _YT_CATEGORIES = [
        ("24", "Entertainment"),
        ("22", "People & Blogs"),
        ("23", "Comedy"),
        ("25", "News & Politics"),
        ("27", "Education"),
        ("26", "Howto & Style"),
    ]
    default_cat_id = getattr(cfg, "DEFAULT_YT_CATEGORY", "24")
    default_cat_label = next(
        (label for cid, label in _YT_CATEGORIES if cid == default_cat_id),
        "Entertainment",
    )
    cat_choices = [
        f"{label} ({cid})" + (" [default]" if cid == default_cat_id else "")
        for cid, label in _YT_CATEGORIES
    ]
    cat_idx, _ = prompt_choice(f"YouTube category for all {num_videos} video(s):", cat_choices)
    selected_cat_id, selected_cat_label = _YT_CATEGORIES[cat_idx]
    if selected_cat_id != default_cat_id:
        _set("DEFAULT_YT_CATEGORY", selected_cat_id)

    # ── Channel selection ─────────────────────────────────────────────────────
    channel_name, channel_cfg = pick_channel()

    # Build timezone-aware datetimes from local input
    interval = getattr(cfg, "UPLOAD_INTERVAL_DAYS", 1)
    schedule_dts = [
        datetime.datetime.combine(
            start_date + datetime.timedelta(days=i * interval), upload_time
        ).astimezone()
        for i in range(num_videos)
    ]

    now  = datetime.datetime.now().astimezone()
    past = sum(1 for dt in schedule_dts if dt <= now)
    if past:
        status(f"{past} scheduled time(s) are already past and will upload immediately.", "warn")

    # ── Confirmation ──────────────────────────────────────────────────────────
    divider("CONFIRM SCHEDULE")
    print(f"  {W}Videos  :{RS} {num_videos}")
    if channel_name:
        print(f"  {W}Channel :{RS} {channel_name}")
    print(f"  {W}Category:{RS} {selected_cat_label} ({selected_cat_id})")
    print(f"  {W}First   :{RS} {schedule_dts[0].strftime('%Y-%m-%d %H:%M')}")
    if num_videos > 1:
        print(f"  {W}Last    :{RS} {schedule_dts[-1].strftime('%Y-%m-%d %H:%M')}")
    print()

    if input(f"  {Y}>{RS} Generate all videos now and start scheduler? (y/n): ").strip().lower() != "y":
        status("Cancelled.", "warn")
        return

    # ── Generate all videos up front ──────────────────────────────────────────
    generated = []   # (video_path, meta_path)

    for i in range(num_videos):
        divider(f"VIDEO {i + 1} OF {num_videos}")
        try:
            audio_path, meta_path = story_tts.run_story_tts()
            video_path            = video_assembly.run_assembly(audio_path, meta_path)
            generated.append((video_path, meta_path))
            status(f"Video {i + 1} ready: {os.path.basename(video_path)}", "ok")
        except Exception as exc:
            status(f"Video {i + 1} failed: {exc}", "err")
            if input(f"  {Y}>{RS} Skip and continue? (y/n): ").strip().lower() != "y":
                status("Scheduler cancelled.", "warn")
                return

    if not generated:
        status("No videos were generated — nothing to schedule.", "err")
        return

    # Drop schedule slots for any skipped videos
    pairs = list(zip(schedule_dts[: len(generated)], generated))

    # Persist job records so Settings > Scheduler Settings can display them
    _save_jobs([
        {
            "slot":         slot,
            "video":        os.path.basename(vp),
            "video_path":   vp,
            "meta_path":    mp,
            "scheduled_at": dt.strftime("%Y-%m-%d %H:%M"),
            "status":       "pending",
        }
        for slot, (dt, (vp, mp)) in enumerate(pairs, start=1)
    ])

    # Authenticate interactively before going into background mode
    status("Authenticating with YouTube (may open a browser)...", "load")
    if channel_name:
        status(f"Channel: {channel_name}", "info")
    yt = youtube_upload.get_authenticated_service(channel_cfg)
    status("YouTube authenticated.", "ok")

    # ── Define upload jobs ────────────────────────────────────────────────────
    results = []   # list.append is thread-safe via the GIL

    def _make_job(video_path, meta_path, slot):
        def _run():
            try:
                with open(meta_path, encoding="utf-8") as f:
                    story = json.load(f)

                title = (story.get("title") or "").strip() or "Reddit Story #shorts"
                sub   = story.get("subreddit", "")
                tags  = ["reddit", "story", "shorts"] + ([sub.lower()] if sub else [])
                ht    = " ".join(story.get("hashtags", [])) or "#shorts #reddit #story"
                desc  = (
                    f"Reddit story from r/{sub}\n\n{ht}" if sub
                    else f"Reddit story\n\n{ht}"
                )

                metadata = {
                    "title":       title,
                    "description": desc,
                    "tags":        tags,
                    "category_id": selected_cat_id,
                    "visibility":  "public",
                    "publish_at":  None,
                }

                video_id = youtube_upload.upload_video(yt, video_path, metadata)
                results.append({
                    "slot": slot,
                    "title": title,
                    "url":  f"https://www.youtube.com/watch?v={video_id}",
                    "ok":   True,
                })

            except Exception as exc:
                results.append({"slot": slot, "title": "?", "url": "", "ok": False, "err": str(exc)})

        return _run

    # ── Start scheduler ───────────────────────────────────────────────────────
    scheduler = BackgroundScheduler()
    for slot, (upload_dt, (video_path, meta_path)) in enumerate(pairs, start=1):
        scheduler.add_job(
            _make_job(video_path, meta_path, slot),
            trigger            = DateTrigger(run_date=upload_dt),
            id                 = f"upload_{slot}",
            misfire_grace_time = 3600,   # still fires if up to 1 hour late (e.g. after sleep)
        )
    scheduler.start()

    # ── Monitor loop ──────────────────────────────────────────────────────────
    divider("SCHEDULER RUNNING")
    print(f"  {G}[OK] {len(pairs)} video(s) queued:{RS}\n")
    for slot, (dt, (vp, _)) in enumerate(pairs, start=1):
        print(f"    {C}{slot}.{RS} {os.path.basename(vp):<52} {dt.strftime('%Y-%m-%d %H:%M')}")
    print(f"\n  {DIM}Keep this window open. Minimise it and let it run.")
    print(f"  Press Ctrl+C to abort.{RS}\n")

    try:
        while len(results) < len(pairs):
            now  = datetime.datetime.now().astimezone()
            done = {r["slot"] for r in results}

            pending = [
                (dt, slot)
                for slot, (dt, _) in enumerate(pairs, start=1)
                if slot not in done
            ]

            if pending:
                next_dt, next_slot = min(pending, key=lambda x: x[0])
                delta  = max(datetime.timedelta(0), next_dt - now)
                h, rem = divmod(int(delta.total_seconds()), 3600)
                m      = rem // 60
                line   = (
                    f"  {C}[*]{RS} Scheduler running — "
                    f"{len(done)}/{len(pairs)} uploaded — "
                    f"next upload #{next_slot} in {h}h {m:02d}m"
                )
            else:
                line = f"  {C}[*]{RS} Final upload in progress — please wait..."

            print(f"\r{line:<80}", end="", flush=True)
            time.sleep(30)

    except KeyboardInterrupt:
        print()
        status("Interrupted — shutting down scheduler.", "warn")
    finally:
        scheduler.shutdown(wait=False)

    # ── Summary ───────────────────────────────────────────────────────────────
    print()
    divider("AUTO SCHEDULER — DONE")
    for r in sorted(results, key=lambda x: x["slot"]):
        if r["ok"]:
            status(f"Video {r['slot']}: {r['title'][:55]}  ->  {r['url']}", "ok")
        else:
            status(f"Video {r['slot']}: FAILED — {r.get('err', '?')}", "err")

    # Update persisted job records with final statuses
    jobs = _load_jobs()
    result_map = {r["slot"]: r for r in results}
    for j in jobs:
        r = result_map.get(j.get("slot"))
        if r:
            j["status"] = "done" if r["ok"] else "failed"
            if r.get("url"):
                j["url"] = r["url"]
    _save_jobs(jobs)
    print()


# ── START MENU ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Reddit story automation pipeline.")
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Fetch YouTube stats for all uploaded videos and post a Discord report, then exit.",
    )
    args = parser.parse_args()

    if args.stats:
        import discord_stats
        print("\n  === DISCORD STATS REPORT ===\n")
        discord_stats.run_stats_report()
        return

    print_banner()
    print(f"  {W}Welcome to Shreddit.{RS}\n")

    idx, _ = prompt_choice("What do you want to do?", [
        "Full Automation  — generate story → build video → upload to YouTube",
        "Video Uploader   — pick an existing MP4 and upload it",
        "Settings         — change voice, captions, volume, and more",
        "Auto Scheduler   — generate videos now, upload on a schedule",
    ])

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    if idx == 0:
        mode_full_automation()
    elif idx == 1:
        mode_uploader_only()
    elif idx == 2:
        mode_settings()
    else:
        mode_auto_scheduler()


if __name__ == "__main__":
    main()
