"""
story_tts.py
------------
Fetches a Reddit story (or generates one via Claude AI) and converts it to speech.
Short stories are automatically extended; long ones are trimmed to hit the 1-3 min sweet spot.

Usage:
  python story_tts.py                      # pull top post from a random subreddit
  python story_tts.py --subreddit tifu     # pull from a specific subreddit
  python story_tts.py --ai                 # generate a story with Claude instead
"""

import argparse
import asyncio
import json
import os
import random
import re
from datetime import datetime

import edge_tts
import requests

from config import (
    ANTHROPIC_API_KEY,
    ANTHROPIC_MODEL,
    DEFAULT_SUBREDDITS,
    EDGE_TTS_VOICE,
    ELEVENLABS_API_KEY,
    ELEVENLABS_VOICE_ID,
    MAX_UPVOTES,
    MAX_WORDS,
    MIN_UPVOTES,
    MIN_WORDS,
    OUTPUT_DIR,
    REDDIT_CLIENT_ID,
    REDDIT_CLIENT_SECRET,
    REDDIT_PASSWORD,
    REDDIT_USERNAME,
    TTS_RATE,
)

_reddit_token_cache = {"token": None}

def _get_reddit_token():
    if _reddit_token_cache["token"]:
        return _reddit_token_cache["token"]
    if not (REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET):
        return None
    resp = requests.post(
        "https://www.reddit.com/api/v1/access_token",
        auth=(REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET),
        data={"grant_type": "password", "username": REDDIT_USERNAME, "password": REDDIT_PASSWORD},
        headers={"User-Agent": f"shreddit-bot/2.0 by {REDDIT_USERNAME}"},
        timeout=10,
    )
    resp.raise_for_status()
    token = resp.json().get("access_token")
    _reddit_token_cache["token"] = token
    return token

# ── TEXT UTILITIES ─────────────────────────────────────────────────────────────

def clean_text(text):
    """Strip markdown formatting and HTML entities from a Reddit post body."""
    text = re.sub(r"http\S+", "", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"~~(.+?)~~", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def word_count(text):
    return len(text.split())


def trim_to_word_limit(text, max_words=MAX_WORDS):
    """Trim to max_words, cutting at the last sentence boundary within the limit."""
    words = text.split()
    if len(words) <= max_words:
        return text
    truncated = " ".join(words[:max_words])
    last_end = max(truncated.rfind("."), truncated.rfind("!"), truncated.rfind("?"))
    # Only cut at a sentence boundary if it's in the latter 70% of the text
    if last_end > len(truncated) * 0.7:
        return truncated[:last_end + 1]
    return truncated


def extend_story(body, title, target_words=MIN_WORDS):
    """Use Claude to extend a story that's below the minimum word count."""
    if not ANTHROPIC_API_KEY:
        print("  [!] No ANTHROPIC_API_KEY in config.py — skipping extension, story may be short.")
        return body

    words_needed = target_words - word_count(body)
    print(f"  [~] Extending story by ~{words_needed} words via Claude...")

    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": ANTHROPIC_MODEL,
            "max_tokens": 1000,
            "messages": [{
                "role": "user",
                "content": (
                    f"Extend this Reddit story by about {words_needed} words. "
                    "Keep the same first-person casual tone and character names. "
                    "Output ONLY the full extended story — no title, intro, or commentary.\n\n"
                    f"Title: {title}\n\nStory:\n{body}"
                ),
            }],
        },
    )
    extended = response.json()["content"][0]["text"].strip()
    print(f"  [OK] Extended to {word_count(extended)} words")
    return extended


def normalize_story(body, title):
    """Ensure the story is within the MIN_WORDS–MAX_WORDS target range."""
    wc = word_count(body)
    print(f"  [*] Word count: {wc} (~{wc // 150}m {(wc % 150) * 60 // 150}s at 150 wpm)")

    if wc > MAX_WORDS:
        print(f"  [!] Too long ({wc} words) — trimming to {MAX_WORDS}...")
        body = trim_to_word_limit(body, MAX_WORDS)
        print(f"  [OK] Trimmed to {word_count(body)} words")
    elif wc < MIN_WORDS:
        print(f"  [!] Too short ({wc} words) — extending to {MIN_WORDS}...")
        body = extend_story(body, title, MIN_WORDS)
        body = trim_to_word_limit(body, MAX_WORDS)  # trim again in case extension overshot

    return body


# ── REDDIT ─────────────────────────────────────────────────────────────────────

_USED_POSTS_FILE = os.path.join(OUTPUT_DIR, "used_posts.json")


def _load_used_urls():
    """Return the set of post URLs already used in previous runs."""
    if not os.path.exists(_USED_POSTS_FILE):
        return set()
    with open(_USED_POSTS_FILE, "r", encoding="utf-8") as f:
        return set(json.load(f))


def _mark_url_used(url):
    """Append a URL to used_posts.json so it won't be reused."""
    used = _load_used_urls()
    used.add(url)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(_USED_POSTS_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(used), f, indent=2)


def fetch_reddit_story(subreddit_name=None):
    """Fetch a text post from the given subreddit, skipping any already used."""
    sub = subreddit_name or random.choice(DEFAULT_SUBREDDITS)
    print(f"  [~] Fetching from r/{sub}...")

    token = _get_reddit_token()
    if token:
        url = f"https://oauth.reddit.com/r/{sub}/top.json?t=week&limit=50"
        headers = {
            "User-Agent": f"shreddit-bot/2.0 by {REDDIT_USERNAME}",
            "Authorization": f"bearer {token}",
        }
    else:
        url = f"https://www.reddit.com/r/{sub}/top.json?t=week&limit=50"
        headers = {"User-Agent": "story-bot/1.0"}

    try:
        response = requests.get(url, headers=headers, timeout=15)
    except requests.exceptions.ConnectionError:
        raise ConnectionError(
            f"No internet connection — could not reach Reddit to fetch r/{sub}."
        )
    if response.status_code == 401:
        _reddit_token_cache["token"] = None
        raise ValueError(f"Reddit OAuth token expired or invalid — check your credentials in config.py")
    if response.status_code != 200:
        raise ValueError(f"Reddit API returned {response.status_code} for r/{sub}")

    used_urls = _load_used_urls()

    # Parse every unused self-post with enough body text in one pass
    all_posts = []
    for post in response.json()["data"]["children"]:
        d = post["data"]
        if not (d.get("is_self") and d.get("selftext")):
            continue
        url = f"https://reddit.com{d['permalink']}"
        if url in used_urls:
            continue
        body = clean_text(d["selftext"])
        if word_count(body) >= 50:  # accept short posts — we'll extend them if needed
            all_posts.append({
                "title":     d["title"],
                "body":      body,
                "url":       url,
                "score":     d["score"],
                "subreddit": sub,
            })

    if not all_posts:
        raise ValueError(f"No unused text posts found in r/{sub} this week.")

    # Try upvote-filtered candidates first; fall back to full list if none qualify
    candidates = [p for p in all_posts if MIN_UPVOTES <= p["score"] <= MAX_UPVOTES]

    if candidates:
        story = random.choice(candidates)
    else:
        print(
            f"  [!] No posts in r/{sub} matched the upvote filter "
            f"({MIN_UPVOTES}–{MAX_UPVOTES}) — bypassing filter, using highest scored post."
        )
        story = max(all_posts, key=lambda p: p["score"])

    _mark_url_used(story["url"])
    print(f"  [OK] Got: \"{story['title']}\"")
    story["body"] = normalize_story(story["body"], story["title"])
    return story


# ── AI STORY GENERATOR ─────────────────────────────────────────────────────────

# Topics Claude can choose from when generating a story via --ai
STORY_TOPICS = [
    "a coworker who took credit for my work and how I got revenge",
    "a nosy neighbor who went too far",
    "discovering my best friend had been lying to me for years",
    "the worst first date that somehow turned into a great story",
    "a family secret that changed everything at Thanksgiving",
    "a prank that spiraled completely out of control",
    "finding out my landlord had been scamming multiple tenants",
    "the moment I realized my boss was actually the problem",
    "when I accidentally exposed my coworker's secret at a work meeting",
    "the time my roommate's weird habit saved my life",
]


def _claude(prompt, max_tokens=1000):
    """Minimal Claude API helper — returns the text of the first content block."""
    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": ANTHROPIC_MODEL,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        },
    )
    return response.json()["content"][0]["text"].strip()


def generate_hashtags(title, subreddit):
    """Return a list of 5 hashtag strings for the story, or [] if no API key."""
    if not ANTHROPIC_API_KEY:
        return []
    print("  [~] Generating hashtags via Claude...")
    raw = _claude(
        f"Generate exactly 5 trending YouTube/TikTok hashtags for a Reddit story video.\n"
        f"Story title: {title}\n"
        f"Subreddit: r/{subreddit}\n\n"
        "Rules:\n"
        "- Output one hashtag per line, starting with #\n"
        "- Mix broad (e.g. #reddit, #storytime) and topic-specific tags\n"
        "- No explanations, no numbering — hashtags only",
        max_tokens=60,
    )
    tags = []
    for token in re.split(r"[\n,]+", raw):
        token = token.strip()
        if not token:
            continue
        if not token.startswith("#"):
            token = "#" + token
        tags.append(token)
    tags = tags[:5]
    print(f"  [OK] Hashtags: {' '.join(tags)}")
    return tags


def generate_ai_story():
    """Generate a Reddit-style story and title using Claude."""
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY is not set in config.py. Required for --ai mode.")

    topic = random.choice(STORY_TOPICS)
    print(f"  [~] Generating AI story about: {topic}...")

    body = _claude(
        f"Write a first-person Reddit-style story (r/AITA or r/TrueOffMyChest) about: {topic}.\n\n"
        "Requirements:\n"
        "- 200-250 words\n"
        "- Conversational, casual tone — like a real person venting\n"
        "- Specific fake details to make it feel real (invented names are fine)\n"
        "- No title, just the story body\n"
        "- End with a satisfying conclusion or cliffhanger\n"
        "- No hashtags, bullet points, or headers"
    )

    title = _claude(
        f"Write a short clickbait Reddit title (max 12 words) for this story. Output only the title:\n\n{body[:300]}",
        max_tokens=50,
    ).strip('"')

    print(f"  [OK] Generated: \"{title}\"")
    body = normalize_story(body, title)
    return {"title": title, "body": body, "url": "AI Generated", "subreddit": "AI"}


# ── TEXT-TO-SPEECH ─────────────────────────────────────────────────────────────

async def _tts_edge(text, output_path):
    communicate = edge_tts.Communicate(text, EDGE_TTS_VOICE, rate=TTS_RATE)
    await communicate.save(output_path)


def generate_tts(story, output_path):
    """Convert the story to an MP3 using ElevenLabs (if key set) or free edge-tts."""
    narration = f"{story['title']}. {story['body']}"
    print(f"  [*] Estimated duration: {word_count(narration) / 150:.1f} minutes")

    if ELEVENLABS_API_KEY:
        print("  [~] Generating audio with ElevenLabs...")
        response = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}",
            headers={"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json"},
            json={
                "text": narration,
                "model_id": "eleven_monolingual_v1",
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
            },
        )
        if response.status_code != 200:
            raise ValueError(f"ElevenLabs error: {response.text}")
        with open(output_path, "wb") as f:
            f.write(response.content)
    else:
        print("  [~] Generating audio with edge-tts (free)...")
        asyncio.run(_tts_edge(narration, output_path))

    print(f"  [OK] Audio saved: {output_path}")


# ── MODULE ENTRY POINT (called by master.py) ───────────────────────────────────

def run_story_tts(subreddit=None, ai_mode=False):
    """
    Generate a story + TTS audio and return (audio_path, meta_path).
    Called by master.py; subreddit and ai_mode mirror the --subreddit / --ai CLI flags.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    print("\n  === STORY + TTS ===\n")

    story = generate_ai_story() if ai_mode else fetch_reddit_story(subreddit)
    story["hashtags"] = generate_hashtags(story["title"], story.get("subreddit", "reddit"))

    story_path = os.path.join(OUTPUT_DIR, f"story_{timestamp}.txt")
    meta_path  = os.path.join(OUTPUT_DIR, f"story_{timestamp}.json")
    audio_path = os.path.join(OUTPUT_DIR, f"story_{timestamp}.mp3")

    with open(story_path, "w", encoding="utf-8") as f:
        f.write(f"Title: {story['title']}\nSource: {story.get('url', 'N/A')}\n\n{story['body']}")

    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(story, f, indent=2)

    generate_tts(story, audio_path)

    print(f"\n  Story : {story_path}")
    print(f"  Audio : {audio_path}")
    print(f"  Meta  : {meta_path}\n")

    return audio_path, meta_path


# ── MAIN ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Fetch a Reddit story and generate TTS audio.")
    parser.add_argument("--ai",        action="store_true", help="Generate a story with Claude instead of fetching from Reddit")
    parser.add_argument("--subreddit", type=str,            help="Subreddit to pull from (e.g. tifu)")
    args = parser.parse_args()

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    print("\n  === STORY + TTS ===\n")

    story = generate_ai_story() if args.ai else fetch_reddit_story(args.subreddit)
    story["hashtags"] = generate_hashtags(story["title"], story.get("subreddit", "reddit"))

    story_path = os.path.join(OUTPUT_DIR, f"story_{timestamp}.txt")
    meta_path  = os.path.join(OUTPUT_DIR, f"story_{timestamp}.json")
    audio_path = os.path.join(OUTPUT_DIR, f"story_{timestamp}.mp3")

    with open(story_path, "w", encoding="utf-8") as f:
        f.write(f"Title: {story['title']}\nSource: {story.get('url', 'N/A')}\n\n{story['body']}")

    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(story, f, indent=2)

    generate_tts(story, audio_path)

    print(f"\n  Story : {story_path}")
    print(f"  Audio : {audio_path}")
    print(f"  Meta  : {meta_path}")
    print(f"\n  Next: python video_assembly.py --audio {audio_path} --meta {meta_path}\n")


if __name__ == "__main__":
    main()
