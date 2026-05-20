"""
discord_stats.py
----------------
Fetches view counts, likes, and comments for every video in output/upload_log.json
using the YouTube Data API, then posts a formatted embed to STATS_CHANNEL_WEBHOOK.

Usage:
  python discord_stats.py
  python master.py --stats
"""

import datetime
import json
import os
import sys

import requests

from config import OUTPUT_DIR, STATS_CHANNEL_WEBHOOK
from youtube_upload import get_authenticated_service

UPLOAD_LOG = os.path.join(OUTPUT_DIR, "upload_log.json")


# ── DATA ───────────────────────────────────────────────────────────────────────

def load_log():
    if not os.path.exists(UPLOAD_LOG):
        return []
    with open(UPLOAD_LOG, encoding="utf-8") as f:
        return json.load(f)


def fetch_stats(youtube, video_ids):
    """Return {video_id: {title, views, likes, comments}} for all given IDs."""
    results = {}
    for i in range(0, len(video_ids), 50):   # API allows max 50 IDs per call
        chunk    = video_ids[i : i + 50]
        response = youtube.videos().list(
            part="snippet,statistics",
            id=",".join(chunk),
        ).execute()

        for item in response.get("items", []):
            vid_id = item["id"]
            stats  = item.get("statistics", {})
            results[vid_id] = {
                "title":    item.get("snippet", {}).get("title", ""),
                "views":    int(stats.get("viewCount",    0)),
                "likes":    int(stats.get("likeCount",    0)) if "likeCount"    in stats else None,
                "comments": int(stats.get("commentCount", 0)) if "commentCount" in stats else None,
            }
    return results


# ── FORMATTING ─────────────────────────────────────────────────────────────────

def _fmt(n):
    """Format an integer with commas, or return '—' for None (hidden by YouTube)."""
    return f"{n:,}" if n is not None else "—"


def build_fields(log, stats):
    """Convert log entries + stats into a list of Discord embed field dicts."""
    fields = []
    for entry in log:
        vid_id = entry.get("video_id")
        if not vid_id:
            continue

        data  = stats.get(vid_id, {})
        title = (data.get("title") or entry.get("title") or "(unknown)")[:256]
        url   = entry.get("url", f"https://www.youtube.com/watch?v={vid_id}")
        date  = entry.get("uploaded_at", "")[:10]   # YYYY-MM-DD portion

        views    = _fmt(data.get("views"))
        likes    = _fmt(data.get("likes"))
        comments = _fmt(data.get("comments"))

        value = (
            f"👁 **{views}** views  •  👍 **{likes}** likes  •  💬 **{comments}** comments"
        )
        if date:
            value += f"  •  📅 {date}"
        value += f"\n🔗 {url}"

        if vid_id not in stats:
            value = "⚠️ Could not retrieve stats (video may have been removed)\n🔗 " + url

        fields.append({"name": title, "value": value, "inline": False})

    return fields


# ── SENDING ────────────────────────────────────────────────────────────────────

def send_to_discord(fields, total):
    """Send one or more webhook messages, splitting at Discord's 25-field limit."""
    now_str = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    chunks  = [fields[i : i + 25] for i in range(0, len(fields), 25)]

    for idx, chunk in enumerate(chunks):
        part_label = f" (part {idx + 1}/{len(chunks)})" if len(chunks) > 1 else ""
        payload = {
            "embeds": [{
                "title":       f"📊 YouTube Stats Report{part_label}",
                "description": f"**{total}** video{'s' if total != 1 else ''} tracked",
                "color":       0xFF0000,
                "fields":      chunk,
                "footer":      {"text": f"Updated {now_str}"},
            }]
        }
        resp = requests.post(STATS_CHANNEL_WEBHOOK, json=payload, timeout=10)
        if resp.status_code not in (200, 204):
            print(f"  [!] Discord returned {resp.status_code}: {resp.text}")
            return

    print(f"  [OK] Stats report sent — {total} video{'s' if total != 1 else ''}")


# ── ENTRY POINT ────────────────────────────────────────────────────────────────

def run_stats_report():
    if not STATS_CHANNEL_WEBHOOK:
        print("  [!] STATS_CHANNEL_WEBHOOK is not set in config.py — skipping.")
        return

    log = load_log()
    if not log:
        print(f"  [!] {UPLOAD_LOG} is empty or missing — nothing to report.")
        return

    video_ids = [e["video_id"] for e in log if e.get("video_id")]
    print(f"  [~] Fetching YouTube stats for {len(video_ids)} video(s)...")

    youtube = get_authenticated_service()
    stats   = fetch_stats(youtube, video_ids)
    fields  = build_fields(log, stats)

    if not fields:
        print("  [!] No valid entries to report.")
        return

    send_to_discord(fields, total=len(fields))


if __name__ == "__main__":
    run_stats_report()
