"""
youtube_upload.py
-----------------
Uploads a video to YouTube using OAuth2.

Standalone (interactive, can upload multiple videos):
  python youtube_upload.py

Called from master.py (single-shot, no banner or looping):
  python youtube_upload.py --video output/video_XYZ.mp4 --meta output/story_XYZ.json
"""

import argparse
import datetime
import glob
import json
import os
import pickle
import sys

import requests

os.environ["PYTHONIOENCODING"] = "utf-8"

try:
    from colorama import init, Fore, Style
    init(autoreset=True)
    R, G, Y, C, W, M = Fore.RED, Fore.GREEN, Fore.YELLOW, Fore.CYAN, Fore.WHITE, Fore.MAGENTA
    DIM, B, RS = Style.DIM, Style.BRIGHT, Style.RESET_ALL
except ImportError:
    R = G = Y = C = W = M = DIM = B = RS = ""

try:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from googleapiclient.errors import HttpError
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from google.auth.exceptions import RefreshError
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False
    HttpError = None
    RefreshError = None

from config import CLIENT_SECRETS_FILE, DISCORD_WEBHOOK_URL, OUTPUT_DIR, TOKEN_FILE, CHANNELS

SCOPES = ["https://www.googleapis.com/auth/youtube"]

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

def status(msg, kind="info"):
    icons = {"info": f"{C}[*]{RS}", "ok": f"{G}[OK]{RS}", "err": f"{R}[ERR]{RS}",
             "warn": f"{Y}[!]{RS}", "load": f"{M}[..]{RS}"}
    print(f"  {icons.get(kind, '[?]')} {msg}")

def divider():
    print(f"\n{C}{'=' * 60}{RS}\n")

def prompt(label, default=None):
    hint = f" [{default}]" if default else ""
    val  = input(f"  {Y}>{RS} {label}{hint}: ").strip()
    return val if val else default

def prompt_choice(label, choices):
    print(f"\n  {label}")
    for i, c in enumerate(choices, 1):
        print(f"    {C}{i}.{RS} {c}")
    while True:
        val = input(f"  {Y}>{RS} Pick a number: ").strip()
        if val.isdigit() and 1 <= int(val) <= len(choices):
            return choices[int(val) - 1]
        print(f"  {R}Invalid choice.{RS}")

def progress_bar(percent, width=50):
    filled = int(width * percent / 100)
    bar    = f"{G}{'#' * filled}{RS}{DIM}{'.' * (width - filled)}{RS}"
    sys.stdout.write(f"\r  [{bar}] {Y}{percent:.1f}%{RS}  ")
    sys.stdout.flush()


# ── AUTH ───────────────────────────────────────────────────────────────────────

def _token_has_full_scope(creds):
    """Return True if the cached token includes the full youtube scope (not just upload-only)."""
    granted = getattr(creds, "scopes", None) or getattr(creds, "granted_scopes", None) or set()
    return "https://www.googleapis.com/auth/youtube" in granted


def get_authenticated_service(channel_cfg=None):
    """Return an authenticated YouTube API client, refreshing or creating credentials as needed.

    channel_cfg: dict with 'token_file' and 'client_secrets' keys (from CHANNELS in config or
                 channels.json). Pass None to use TOKEN_FILE / CLIENT_SECRETS_FILE defaults.
    """
    if not GOOGLE_AVAILABLE:
        status("Google API libraries not installed.", "err")
        status("Run: pip install google-auth google-auth-oauthlib google-api-python-client", "info")
        sys.exit(1)

    token_file   = (channel_cfg or {}).get("token_file",     TOKEN_FILE)
    secrets_file = (channel_cfg or {}).get("client_secrets", CLIENT_SECRETS_FILE)

    # Ensure the directory that will hold the token exists
    token_dir = os.path.dirname(token_file)
    if token_dir:
        os.makedirs(token_dir, exist_ok=True)

    creds = None
    if os.path.exists(token_file):
        with open(token_file, "rb") as f:
            creds = pickle.load(f)
        # Discard token if it was created with the old narrow youtube.upload scope
        if creds and not _token_has_full_scope(creds):
            status("Cached token has insufficient scope — re-authenticating...", "warn")
            creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            status("Refreshing credentials...", "load")
            try:
                creds.refresh(Request())
            except Exception as e:
                if RefreshError and isinstance(e, RefreshError):
                    status("Credentials are invalid or have been revoked.", "err")
                    status(f"Delete '{token_file}' and re-run to re-authenticate.", "info")
                    if os.path.exists(token_file):
                        os.remove(token_file)
                    sys.exit(1)
                raise
        else:
            if not os.path.exists(secrets_file):
                status(f"Missing {secrets_file}!", "err")
                print("\n  To get it:")
                print("  1. Go to https://console.cloud.google.com")
                print("  2. Create a project → Enable 'YouTube Data API v3'")
                print("  3. Credentials → OAuth 2.0 Client ID → Desktop App")
                print("  4. Download JSON → rename to client_secrets.json → place next to this script")
                input("\n  Press Enter once done...")
                if not os.path.exists(secrets_file):
                    status("Still missing client_secrets.json. Exiting.", "err")
                    sys.exit(1)

            status("Opening browser for Google login...", "load")
            flow  = InstalledAppFlow.from_client_secrets_file(secrets_file, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(token_file, "wb") as f:
            pickle.dump(creds, f)
        status("Credentials saved.", "ok")

    return build("youtube", "v3", credentials=creds)


# ── VIDEO SELECTION ────────────────────────────────────────────────────────────

def pick_video():
    """Interactively list recent MP4s in the output folder and let the user choose one."""
    divider()
    print(f"  {W}{B}SELECT VIDEO{RS}\n")

    videos = sorted(glob.glob(os.path.join(OUTPUT_DIR, "*.mp4")), key=os.path.getmtime, reverse=True)

    if videos:
        print(f"  Recent videos in {OUTPUT_DIR}:")
        for i, v in enumerate(videos[:8], 1):
            size_mb = os.path.getsize(v) / (1024 * 1024)
            print(f"    {C}{i}.{RS} {os.path.basename(v)} ({size_mb:.1f} MB)")
        print(f"    {C}{len(videos[:8]) + 1}.{RS} Enter path manually")

        choice = input(f"\n  {Y}>{RS} Pick a number: ").strip()
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(videos[:8]):
                return videos[idx]

    path = input(f"  {Y}>{RS} Enter full path to video: ").strip().strip('"')
    if not os.path.exists(path):
        status("File not found.", "err")
        sys.exit(1)
    return path


# ── METADATA ──────────────────────────────────────────────────────────────────

def load_meta(video_path, meta_path=None):
    """
    Load story metadata to pre-fill the title/tags/description prompts.
    Tries (in order): explicit meta_path arg → derived filename → most recent JSON in output.
    """
    def _load(path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}

    if meta_path and os.path.exists(meta_path):
        return _load(meta_path)

    # Derive: output/video_story_XYZ.mp4 → output/story_XYZ.json
    derived = os.path.splitext(video_path)[0].replace("video_story_", "story_") + ".json"
    if os.path.exists(derived):
        return _load(derived)

    # Fall back to most recently modified JSON that is a dict (skips upload_log.json which is a list)
    jsons = sorted(glob.glob(os.path.join(OUTPUT_DIR, "*.json")), key=os.path.getmtime, reverse=True)
    for path in jsons:
        data = _load(path)
        if data:
            return data

    return {}


def get_metadata(video_path, meta_path=None):
    """Prompt the user to confirm or edit the upload metadata for a video."""
    divider()
    print(f"  {W}{B}VIDEO METADATA{RS}\n")

    meta = load_meta(video_path, meta_path)
    sub  = meta.get("subreddit", "")

    title = prompt("Title", default=meta.get("title", "")) or "Reddit Story #shorts"

    desc_default = (
        f"Reddit story from r/{sub}\n\n#shorts #reddit #story #{sub.lower()}"
        if sub else "#shorts #reddit #story"
    )
    desc = prompt("Description", default=desc_default)

    tags_default = f"reddit,story,shorts,{sub.lower()}" if sub else "reddit,story,shorts"
    tags = [t.strip() for t in prompt("Tags (comma separated)", default=tags_default).split(",") if t.strip()]

    category_raw = prompt_choice("Category", [
        "22 - People & Blogs",
        "24 - Entertainment",
        "23 - Comedy",
        "25 - News & Politics",
    ])
    category_id = category_raw.split(" ")[0]

    visibility = prompt_choice("Visibility", ["public", "unlisted", "private"])

    publish_at = None
    if prompt_choice("When to publish?", ["Now", "Schedule for later"]) == "Schedule for later":
        date_str = input(f"  {Y}>{RS} Enter date/time (YYYY-MM-DD HH:MM, 24hr UTC): ").strip()
        try:
            dt         = datetime.datetime.strptime(date_str, "%Y-%m-%d %H:%M")
            publish_at = dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            visibility = "private"   # scheduled uploads must start as private
            status(f"Scheduled for {date_str} UTC", "ok")
        except ValueError:
            status("Invalid date format — publishing now instead.", "warn")

    return {
        "title":       title,
        "description": desc,
        "tags":        tags,
        "category_id": category_id,
        "visibility":  visibility,
        "publish_at":  publish_at,
    }


# ── UPLOAD ────────────────────────────────────────────────────────────────────

def upload_video(youtube, video_path, metadata):
    """Upload the video using the resumable upload API and log the result."""
    divider()
    print(f"  {W}{B}UPLOADING{RS}\n")

    raw_title = metadata.get("title") or ""

    # YouTube rejects titles containing < or > with an invalidTitle error
    title = raw_title.replace("<", "").replace(">", "").strip()
    if len(title) > 100:
        title = title[:100].rstrip()
    if not title:
        status("Title was empty after sanitization — using fallback.", "warn")
        title = "Reddit Story #shorts"

    if not title:
        raise ValueError(
            f"Title is empty after sanitization and fallback. "
            f"Raw value was: {repr(raw_title)}"
        )

    status(f"File:       {os.path.basename(video_path)}", "info")
    status(f"Title:      {title}", "info")
    status(f"Visibility: {metadata['visibility']}", "info")
    print()

    body = {
        "snippet": {
            "title":       title,
            "description": metadata["description"],
            "tags":        metadata["tags"],
            "categoryId":  metadata["category_id"],
        },
        "status": {
            "privacyStatus":          metadata["visibility"],
            "selfDeclaredMadeForKids": False,
        },
    }
    if metadata.get("publish_at"):
        body["status"]["publishAt"] = metadata["publish_at"]

    # Resumable upload — safe for large files; resumes automatically on transient errors
    media   = MediaFileUpload(video_path, chunksize=1024 * 1024, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response, last_pct = None, 0
    while response is None:
        try:
            status_obj, response = request.next_chunk()
            if status_obj:
                pct = status_obj.progress() * 100
                if pct - last_pct >= 1:
                    progress_bar(pct)
                    last_pct = pct
        except Exception as e:
            if HttpError and isinstance(e, HttpError):
                try:
                    err_content = json.loads(e.content.decode("utf-8", errors="replace"))
                    reason = err_content.get("error", {}).get("errors", [{}])[0].get("reason", "")
                except Exception:
                    reason = ""
                if reason == "quotaExceeded":
                    status("YouTube API daily quota exceeded.", "err")
                    status("Uploads reset at midnight Pacific Time. Try again tomorrow.", "info")
                    sys.exit(1)
            status(f"Upload error: {e}", "err")
            sys.exit(1)

    progress_bar(100)
    print("\n")

    video_id      = response.get("id")
    snippet       = response.get("snippet", {})
    upload_status = response.get("status", {})

    status(f"Video ID      : {video_id}", "info")
    status(f"Returned title: {snippet.get('title', '(none)')}", "info")
    status(f"Privacy status: {upload_status.get('privacyStatus', '(none)')}", "info")
    status(f"Upload status : {upload_status.get('uploadStatus', '(none)')}", "info")
    status(f"Failure reason: {upload_status.get('failureReason', 'none')}", "info")
    status(f"Rejection rsn : {upload_status.get('rejectionReason', 'none')}", "info")
    print()

    # ── CONFIRM VIDEO EXISTS VIA videos().list() ───────────────────────────────
    status("Confirming video exists on YouTube...", "load")
    try:
        confirm = youtube.videos().list(
            part="snippet,status,processingDetails",
            id=video_id,
        ).execute()

        items = confirm.get("items", [])
        if not items:
            status(f"WARNING: video_id {video_id} returned NO items from videos().list().", "warn")
            status("This usually means:", "warn")
            status("  • The account has no YouTube channel set up, or", "warn")
            status("  • The video was auto-deleted by YouTube (policy / no channel), or", "warn")
            status("  • The OAuth token belongs to a different Google account than the channel.", "warn")
            status("Fix: go to https://www.youtube.com and create a channel on this Google account first.", "info")
        else:
            v   = items[0]
            vs  = v.get("status", {})
            vpd = v.get("processingDetails", {})
            status("Video confirmed on YouTube!", "ok")
            status(f"  Title          : {v.get('snippet', {}).get('title')}", "info")
            status(f"  Privacy        : {vs.get('privacyStatus')}", "info")
            status(f"  Upload status  : {vs.get('uploadStatus')}", "info")
            status(f"  Processing     : {vpd.get('processingStatus', 'n/a')}", "info")
            status(f"  Failure reason : {vs.get('failureReason', 'none')}", "info")
    except Exception as e:
        status(f"videos().list() check failed: {e}", "err")

    status("Upload complete!", "ok")
    status(f"URL: https://www.youtube.com/watch?v={video_id}", "ok")

    # Append to the upload log so you have a record of everything that's been published
    log_path = os.path.join(OUTPUT_DIR, "upload_log.json")
    if os.path.exists(log_path):
        with open(log_path, encoding="utf-8") as f:
            log = json.load(f)
    else:
        log = []
    log.append({
        "video_id":    video_id,
        "title":       title,
        "url":         f"https://www.youtube.com/watch?v={video_id}",
        "uploaded_at": datetime.datetime.now().isoformat(),
        "file":        os.path.basename(video_path),
    })
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2)
    status(f"Logged to {log_path}", "info")

    notify_discord(title, f"https://www.youtube.com/watch?v={video_id}")

    return video_id


# ── DISCORD NOTIFICATION ──────────────────────────────────────────────────────

def notify_discord(title, video_url):
    """Send a webhook embed to Discord. Silently skips if DISCORD_WEBHOOK_URL is blank."""
    if not DISCORD_WEBHOOK_URL:
        return
    try:
        requests.post(
            DISCORD_WEBHOOK_URL,
            json={
                "embeds": [{
                    "title":       title,
                    "url":         video_url,
                    "description": "New video just uploaded to YouTube!",
                    "color":       0xFF0000,   # YouTube red
                }]
            },
            timeout=10,
        )
        status("Discord notification sent.", "ok")
    except Exception as e:
        status(f"Discord notification failed: {e}", "warn")


# ── MAIN ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Upload a video to YouTube.")
    parser.add_argument("--video", default=None, help="Video path — skips interactive selection when set")
    parser.add_argument("--meta",  default=None, help="Story JSON path — pre-fills metadata when set")
    args = parser.parse_args()

    # single_shot = True when called from master.py with --video
    # In this mode we skip the banner/intro and exit after one upload (no loop)
    single_shot = args.video is not None

    if not single_shot:
        clear()
        print(BANNER)
        print(f"{C}{'=' * 100}{RS}")
        print(f"{W}{B}  Shreddit{RS}  {DIM}| Reddit -> YouTube Shorts Pipeline{RS}")
        print(f"{C}{'=' * 100}{RS}\n")
        input(f"  Press Enter to start... ")

    status("Connecting to YouTube...", "load")
    youtube = get_authenticated_service()
    status("Connected!", "ok")

    while True:
        video_path = args.video if single_shot else pick_video()
        status(f"Video: {os.path.basename(video_path)}", "info")

        metadata = get_metadata(video_path, meta_path=args.meta if single_shot else None)

        # Show a confirmation summary before uploading
        divider()
        print(f"  {W}{B}CONFIRM UPLOAD{RS}\n")
        print(f"  {C}File:       {RS}{os.path.basename(video_path)}")
        print(f"  {C}Title:      {RS}{metadata['title']}")
        print(f"  {C}Tags:       {RS}{', '.join(metadata['tags'][:5])}")
        print(f"  {C}Visibility: {RS}{metadata['visibility']}")
        if metadata.get("publish_at"):
            print(f"  {C}Scheduled:  {RS}{metadata['publish_at']}")
        print()

        if input(f"  {Y}>{RS} Upload now? (y/n): ").strip().lower() == "y":
            upload_video(youtube, video_path, metadata)
        else:
            status("Upload cancelled.", "warn")

        # In single-shot mode (from master.py) always exit after one video
        if single_shot:
            break

        divider()
        if input(f"  {Y}>{RS} Upload another video? (y/n): ").strip().lower() != "y":
            break

    print(f"\n  {G}{B}Done! Check your YouTube Studio.{RS}\n")


if __name__ == "__main__":
    main()
