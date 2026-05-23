"""
config.py
---------
Single source of truth for all project settings.
Edit this file to configure the pipeline — no other files need to be touched.

DO NOT commit real API keys — fill these in after cloning.
"""

# ── PATHS ──────────────────────────────────────────────────────────────────────

OUTPUT_DIR   = "./output"   # where rendered videos and story files are saved
BG_VIDEO_DIR = "./videos"   # put your Minecraft / Subway Surfers clips here
MUSIC_DIR    = "./music"    # put background music MP3s here (optional)

# ── API KEYS ───────────────────────────────────────────────────────────────────
# Leave blank to use free alternatives (edge-tts for voice, no AI story extension)

ANTHROPIC_API_KEY   = ""                        # enables AI story generation + auto-extension
ELEVENLABS_API_KEY  = ""                        # enables premium TTS; blank = free edge-tts
ELEVENLABS_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"   # default ElevenLabs voice (Rachel)
DISCORD_WEBHOOK_URL  = ""   # post-upload notification; blank = disabled
STATS_CHANNEL_WEBHOOK = ""  # daily stats report destination; can be the same URL as above

# ── YOUTUBE AUTH ───────────────────────────────────────────────────────────────

CLIENT_SECRETS_FILE = "client_secrets.json"   # OAuth credentials downloaded from Google Cloud
TOKEN_FILE          = "youtube_token.pkl"     # cached auth token — auto-created on first login

# ── TEXT-TO-SPEECH ─────────────────────────────────────────────────────────────

EDGE_TTS_VOICE  = "en-US-ChristopherNeural"   # free Microsoft voice used when no ElevenLabs key
TTS_RATE        = "+1%"   # speech speed: +10% faster, -10% slower, +0% default
ANTHROPIC_MODEL = "claude-sonnet-4-6"         # Claude model used for story generation/extension

# ── STORY LENGTH ───────────────────────────────────────────────────────────────
# ~150 words per minute speaking speed → these targets = 1–3 minutes of narration

MIN_WORDS = 150   # stories shorter than this get extended via Claude (requires ANTHROPIC_API_KEY)
MAX_WORDS = 450   # stories longer than this get trimmed at a sentence boundary

# ── HOOK INTRO ─────────────────────────────────────────────────────────────────
# Shown as a full-screen text card before the Reddit card appears.
# One line is chosen at random per video. Set to a single string to always use the same one.

HOOK_DURATION = 2.5   # seconds the hook card is displayed
HOOK_LINES = [
    "Wait till you hear this...",
    "This actually happened...",
    "You won't believe this story...",
    "I can't make this up...",
    "Story time. This is wild.",
]

# ── VIDEO ──────────────────────────────────────────────────────────────────────

VIDEO_W   = 1080   # vertical 9:16 for TikTok / YouTube Shorts
VIDEO_H   = 1920
VIDEO_FPS = 30

# ── BACKGROUND MUSIC ───────────────────────────────────────────────────────────

MUSIC_VOLUME = 0.10   # 0.0 = silent, 1.0 = full volume; 0.10 sits quietly under narration

# ── CAPTIONS ───────────────────────────────────────────────────────────────────
# CAPTION_STYLE options:
#   "classic"  — white text with black stroke outline, yellow highlight word
#   "pill"     — white rounded-rect behind each word, yellow pill for highlight
#   "allcaps"  — same as classic but every word is uppercased

CAPTION_STYLE        = "classic"
CAPTION_FONT_SIZE    = 72
CAPTION_COLOR        = (255, 255, 255)   # white — default word colour
CAPTION_HIGHLIGHT    = (255, 220, 0)     # yellow — currently spoken word
CAPTION_STROKE_COLOR = (0, 0, 0)         # black outline so text is readable on any background
CAPTION_STROKE_WIDTH = 4
CAPTION_Y_POSITION   = 0.72             # vertical position as a fraction (0 = top, 1 = bottom)
WORDS_PER_CAPTION    = 3                # how many words appear on screen at once

# ── REDDIT CARD STYLE ──────────────────────────────────────────────────────────

CARD_BG_COLOR     = (26, 26, 27)     # dark Reddit-style background
CARD_ACCENT_COLOR = (255, 69, 0)     # Reddit orange for the logo circle
CARD_TEXT_COLOR   = (215, 218, 220)  # light grey for secondary text
CARD_TITLE_COLOR  = (255, 255, 255)  # white for the post title

# ── REDDIT ─────────────────────────────────────────────────────────────────────

MIN_UPVOTES = 100     # ignore posts below this score (filters out low-engagement content)
MAX_UPVOTES = 10000   # ignore posts above this score (viral posts often have short bodies)

# ── SUBREDDITS ─────────────────────────────────────────────────────────────────
# Organized by category for the master.py browser menu.
# DEFAULT_SUBREDDITS is derived automatically and used by story_tts.py for random picks.

SUBREDDIT_CATEGORIES = {
    "Drama": [
        "AmItheAsshole",
        "AITAH",
        "TrueOffMyChest",
        "offmychest",
        "confessions",
        "relationship_advice",
        "relationships",
        "tifu",
        "pettyrevenge",
        "prorevenge",
        "nuclearrevenge",
        "MaliciousCompliance",
    ],
    "Creepy": [
        "nosleep",
        "LetsNotMeet",
        "creepyencounters",
        "Paranormal",
        "Glitch_in_the_Matrix",
        "shortscarystories",
    ],
    "Funny": [
        "entitledparents",
        "ChoosingBeggars",
        "facepalm",
        "therewasanattempt",
        "PublicFreakout",
        "IdiotsInCars",
    ],
    "Emotional": [
        "confession",
        "self",
        "DecidingToBeBetter",
        "raisedbynarcissists",
        "insaneparents",
    ],
    "Work": [
        "TalesFromRetail",
        "TalesFromYourServer",
        "antiwork",
        "Teachers",
        "college",
    ],
    "Crazy": [
        "legaladvice",
        "bestofredditorupdates",
        "BestofRedditorUpdates",
        "RBI",
        "UnresolvedMysteries",
    ],
}

# Flat list used by story_tts.py for random auto-selection
DEFAULT_SUBREDDITS = [s for subs in SUBREDDIT_CATEGORIES.values() for s in subs]

# ── CHANNELS ───────────────────────────────────────────────────────────────────
# Managed via Settings > Manage Channels. Live data is stored in channels.json.
# This block shows the expected format. Add real channels through the menu.

CHANNELS = {
    "Drama Channel": {
        "token_file":     "tokens/drama_channel_token.pkl",
        "client_secrets": "client_secrets.json",
    },
    "Creepy Channel": {
        "token_file":     "tokens/creepy_channel_token.pkl",
        "client_secrets": "client_secrets.json",
    },
}
DEFAULT_CHANNEL = ""   # set via Settings > Manage Channels > Set Default

# ── AUTO SCHEDULER ─────────────────────────────────────────────────────────────

DEFAULT_UPLOAD_TIME  = "14:00"   # default upload time pre-filled in the Auto Scheduler (HH:MM)
DEFAULT_BATCH_SIZE   = 1         # default number of videos generated per batch run
UPLOAD_INTERVAL_DAYS = 1         # days between each scheduled video upload
DEFAULT_YT_CATEGORY  = "24"      # YouTube category ID applied to every scheduled upload
