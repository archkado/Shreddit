"""
video_assembly.py
-----------------
Combines a background video + story audio + Reddit header card + word-by-word captions
into a finished vertical MP4 for TikTok / YouTube Shorts.

Requires ffmpeg on your PATH: https://ffmpeg.org/download.html

Usage:
  python video_assembly.py --audio output/story_XYZ.mp3 --meta output/story_XYZ.json
  python video_assembly.py --audio output/story_XYZ.mp3 --meta output/story_XYZ.json --bg videos/minecraft.mp4
"""

import argparse
import json
import os
import random
import textwrap

import moviepy.audio.fx.all as afx
import numpy as np
import whisper
from moviepy.editor import (
    AudioFileClip,
    CompositeAudioClip,
    CompositeVideoClip,
    ImageClip,
    VideoFileClip,
    concatenate_videoclips,
)
from PIL import Image, ImageDraw, ImageFont

from config import (
    BG_VIDEO_DIR,
    CAPTION_COLOR,
    CAPTION_FONT_SIZE,
    CAPTION_HIGHLIGHT,
    CAPTION_STROKE_COLOR,
    CAPTION_STROKE_WIDTH,
    CAPTION_STYLE,
    CAPTION_Y_POSITION,
    CARD_ACCENT_COLOR,
    CARD_BG_COLOR,
    CARD_TEXT_COLOR,
    CARD_TITLE_COLOR,
    HOOK_DURATION,
    HOOK_LINES,
    MUSIC_DIR,
    MUSIC_VOLUME,
    OUTPUT_DIR,
    VIDEO_FPS,
    VIDEO_H,
    VIDEO_W,
    WORDS_PER_CAPTION,
)

# ── FONT LOADING ───────────────────────────────────────────────────────────────

def _load_fonts(sizes):
    """
    Try to load Arial (Windows) then DejaVu (Linux/Mac), falling back to the
    PIL built-in default. Returns one font per size in the given list.
    """
    font_paths = [
        ("arialbd.ttf", "arial.ttf"),
        (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ),
    ]
    for bold_path, regular_path in font_paths:
        try:
            return [ImageFont.truetype(bold_path if i == 0 else regular_path, s) for i, s in enumerate(sizes)]
        except OSError:
            continue
    fallback = ImageFont.load_default()
    return [fallback] * len(sizes)


# ── REDDIT HEADER CARD ─────────────────────────────────────────────────────────

def make_reddit_card(title: str, width: int = VIDEO_W) -> Image.Image:
    """Render a Reddit-style story card as a PIL RGBA image."""
    padding = 40
    font_title, font_handle, font_small = _load_fonts([52, 36, 30])

    wrapped_lines = textwrap.fill(title, width=38).split("\n")

    # Measure how tall the card needs to be
    dummy_draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    line_h  = dummy_draw.textbbox((0, 0), "Ag", font=font_title)[3] + 8
    title_h = line_h * len(wrapped_lines)
    card_h  = padding + 60 + 16 + title_h + 40 + 50 + padding

    img  = Image.new("RGBA", (width, card_h), (*CARD_BG_COLOR, 245))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([(0, 0), (width - 1, card_h - 1)], radius=20, fill=(*CARD_BG_COLOR, 245))

    y = padding

    # Reddit logo circle + "Reddit World ✓" handle
    logo_r = 24
    draw.ellipse([(padding, y + 6), (padding + logo_r * 2, y + 6 + logo_r * 2)], fill=CARD_ACCENT_COLOR)
    draw.text((padding + logo_r - 9, y + 10), "r/", font=font_handle, fill=(255, 255, 255))
    draw.text((padding + logo_r * 2 + 16, y + 6), "Reddit World ✓", font=font_handle, fill=CARD_TEXT_COLOR)
    y += 60 + 16

    for line in wrapped_lines:
        draw.text((padding, y), line, font=font_title, fill=CARD_TITLE_COLOR)
        y += line_h
    y += 16

    # Fake engagement counts
    draw.text((padding, y), "♡  99+    💬  99+", font=font_small, fill=(120, 124, 126))

    return img


def card_to_clip(title: str, duration: float) -> ImageClip:
    """Wrap the Reddit card PIL image in a MoviePy ImageClip pinned to the top of the frame."""
    img = make_reddit_card(title)
    return ImageClip(np.array(img), duration=duration).set_position(("center", 60))


# ── BACKGROUND VIDEO ───────────────────────────────────────────────────────────

def pick_random_bg() -> str:
    """Return the path to a random video in the BG_VIDEO_DIR folder."""
    if not os.path.exists(BG_VIDEO_DIR):
        raise FileNotFoundError(
            f"'{BG_VIDEO_DIR}' folder not found. Create it and add background gameplay clips."
        )
    videos = [f for f in os.listdir(BG_VIDEO_DIR) if f.lower().endswith((".mp4", ".mov", ".avi"))]
    if not videos:
        raise FileNotFoundError(f"No video files found in '{BG_VIDEO_DIR}'.")
    return os.path.join(BG_VIDEO_DIR, random.choice(videos))


def load_background(bg_path: str, duration: float) -> VideoFileClip:
    """
    Load a background clip, crop it to fill the 9:16 frame without letterboxing,
    then loop or trim it to exactly match the narration duration.
    """
    print(f"  [~] Loading background: {os.path.basename(bg_path)}")
    clip = VideoFileClip(bg_path)

    clip_aspect   = clip.w / clip.h
    target_aspect = VIDEO_W / VIDEO_H

    if clip_aspect > target_aspect:
        # Clip is wider than needed — crop the sides
        new_w = int(clip.h * target_aspect)
        x_c   = clip.w / 2
        clip  = clip.crop(x1=x_c - new_w / 2, x2=x_c + new_w / 2)
    else:
        # Clip is taller than needed — crop top and bottom
        new_h = int(clip.w / target_aspect)
        y_c   = clip.h / 2
        clip  = clip.crop(y1=y_c - new_h / 2, y2=y_c + new_h / 2)

    clip = clip.resize((VIDEO_W, VIDEO_H))

    if clip.duration < duration:
        loops = int(np.ceil(duration / clip.duration))
        clip  = concatenate_videoclips([clip] * loops)

    return clip.subclip(0, duration).without_audio()


# ── BACKGROUND MUSIC ───────────────────────────────────────────────────────────

def pick_random_music():
    """Return a random MP3 path from MUSIC_DIR, or None if the folder is absent/empty."""
    if not os.path.exists(MUSIC_DIR):
        return None
    tracks = [f for f in os.listdir(MUSIC_DIR) if f.lower().endswith(".mp3")]
    return os.path.join(MUSIC_DIR, random.choice(tracks)) if tracks else None


# ── HOOK INTRO CARD ───────────────────────────────────────────────────────────

def make_hook_clip(duration: float) -> ImageClip:
    """Full-frame dark overlay with a large centred hook line shown before narration."""
    text = random.choice(HOOK_LINES) if isinstance(HOOK_LINES, list) else HOOK_LINES

    img  = Image.new("RGBA", (VIDEO_W, VIDEO_H), (0, 0, 0, 180))
    draw = ImageDraw.Draw(img)
    font = _load_fonts([90])[0]

    lines  = textwrap.fill(text, width=20).split("\n")
    line_h = draw.textbbox((0, 0), "Ag", font=font)[3] + 16
    y      = (VIDEO_H - line_h * len(lines)) / 2

    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        x    = (VIDEO_W - (bbox[2] - bbox[0])) / 2
        for dx, dy in ((-4, -4), (4, -4), (-4, 4), (4, 4)):
            draw.text((x + dx, y + dy), line, font=font, fill=(0, 0, 0, 255))
        draw.text((x, y), line, font=font, fill=(255, 255, 255, 255))
        y += line_h

    return ImageClip(np.array(img), duration=duration).set_position("center")


# ── CAPTIONS ──────────────────────────────────────────────────────────────────

def transcribe_audio(audio_path: str) -> list:
    """
    Run Whisper on the narration to get per-word timestamps.
    Uses the 'tiny' model — fast enough for TTS narration, takes ~10 seconds on CPU.
    """
    print("  [~] Transcribing audio for captions...")
    model  = whisper.load_model("tiny")
    result = model.transcribe(audio_path, word_timestamps=True)

    words = []
    for segment in result["segments"]:
        for w in segment.get("words", []):
            words.append({"word": w["word"].strip(), "start": w["start"], "end": w["end"]})

    print(f"  [OK] Transcribed {len(words)} words")
    return words


def _load_caption_font():
    for path in ("arialbd.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(path, CAPTION_FONT_SIZE)
        except OSError:
            continue
    return ImageFont.load_default()


def make_caption_image(group: dict, highlight_idx: int = -1) -> Image.Image:
    """Render one caption group as a transparent RGBA image using the configured CAPTION_STYLE."""
    style = CAPTION_STYLE.lower()
    img   = Image.new("RGBA", (VIDEO_W, 200), (0, 0, 0, 0))
    draw  = ImageDraw.Draw(img)
    font  = _load_caption_font()

    words   = group["words"]
    display = [w["word"].upper() if style == "allcaps" else w["word"] for w in words]

    total_text = " ".join(display)
    bbox   = draw.textbbox((0, 0), total_text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x0     = (VIDEO_W - text_w) / 2
    y0     = (200     - text_h) / 2

    if style == "pill":
        # ── Pill style ────────────────────────────────────────────────────────
        # Two passes: first collect word positions, then draw pills, then text.
        PILL_PAD_X = 14
        PILL_PAD_Y = 8

        # Pass 1 — measure each word's pixel x and width
        word_specs = []   # (x, word_pixel_width, display_text)
        cx = x0
        for i, word in enumerate(display):
            full = word + (" " if i < len(display) - 1 else "")
            word_w = draw.textbbox((0, 0), word, font=font)
            full_w = draw.textbbox((0, 0), full, font=font)
            word_specs.append((cx, word_w[2] - word_w[0], word))
            cx += full_w[2] - full_w[0]

        # Pass 2 — draw pills
        radius = (text_h + PILL_PAD_Y * 2) // 2
        for i, (wx, ww, _) in enumerate(word_specs):
            fill = CAPTION_HIGHLIGHT if i == highlight_idx else (255, 255, 255)
            draw.rounded_rectangle(
                [(wx - PILL_PAD_X, y0 - PILL_PAD_Y),
                 (wx + ww + PILL_PAD_X, y0 + text_h + PILL_PAD_Y)],
                radius=radius,
                fill=(*fill, 255),
            )

        # Pass 3 — draw dark text on top of pills
        for wx, _, word in word_specs:
            draw.text((wx, y0), word, font=font, fill=(20, 20, 20, 255))

    else:
        # ── Classic / allcaps style ───────────────────────────────────────────
        x = x0
        for i, word in enumerate(display):
            color     = CAPTION_HIGHLIGHT if i == highlight_idx else CAPTION_COLOR
            word_text = word + (" " if i < len(display) - 1 else "")

            sw = CAPTION_STROKE_WIDTH
            for dx, dy in ((-sw, -sw), (sw, -sw), (-sw, sw), (sw, sw)):
                draw.text((x + dx, y0 + dy), word_text, font=font, fill=(*CAPTION_STROKE_COLOR, 255))

            draw.text((x, y0), word_text, font=font, fill=(*color, 255))
            word_bbox = draw.textbbox((0, 0), word_text, font=font)
            x += word_bbox[2] - word_bbox[0]

    return img


def build_caption_clips(words: list) -> list:
    """
    Convert a flat word-timestamp list into a series of timed ImageClips.
    Words are grouped into chunks of WORDS_PER_CAPTION. Within each chunk,
    one sub-clip is created per word so the yellow highlight tracks the narration.
    """
    print("  [~] Building caption clips...")
    clips     = []
    caption_y = int(VIDEO_H * CAPTION_Y_POSITION)

    for i in range(0, len(words), WORDS_PER_CAPTION):
        chunk = words[i:i + WORDS_PER_CAPTION]
        group = {
            "text":  " ".join(w["word"] for w in chunk),
            "start": chunk[0]["start"],
            "end":   chunk[-1]["end"],
            "words": chunk,
        }
        for j, word in enumerate(chunk):
            start    = word["start"]
            end      = word["end"] if j < len(chunk) - 1 else group["end"]
            duration = max(end - start, 0.05)

            img_arr = np.array(make_caption_image(group, highlight_idx=j))
            clip    = (
                ImageClip(img_arr, duration=duration)
                .set_start(start)
                .set_position(("center", caption_y))
            )
            clips.append(clip)

    print(f"  [OK] Built {len(clips)} caption clips")
    return clips


# ── MODULE ENTRY POINT (called by master.py) ───────────────────────────────────

def run_assembly(audio_path, meta_path, bg_path=None):
    """
    Assemble a finished MP4 from the given audio + metadata and return its path.
    Called by master.py; mirrors the --audio / --meta / --bg CLI arguments.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with open(meta_path, "r", encoding="utf-8") as f:
        story = json.load(f)

    print(f"\n  === VIDEO ASSEMBLY ===\n")
    print(f"  [*] Story: {story['title']}")

    audio          = AudioFileClip(audio_path)
    duration       = audio.duration
    total_duration = HOOK_DURATION + duration
    print(f"  [*] Duration: {duration:.1f}s  (+{HOOK_DURATION}s hook = {total_duration:.1f}s total)")

    bg        = load_background(bg_path or pick_random_bg(), total_duration)
    hook_clip = make_hook_clip(HOOK_DURATION)
    card_clip = card_to_clip(story["title"], duration).set_start(HOOK_DURATION)
    words     = transcribe_audio(audio_path)
    captions  = [c.set_start(c.start + HOOK_DURATION) for c in build_caption_clips(words)]

    music_path = pick_random_music()
    if music_path:
        print(f"  [~] Adding music: {os.path.basename(music_path)}")
        music = (
            AudioFileClip(music_path)
            .fx(afx.audio_loop, duration=total_duration)
            .subclip(0, total_duration)
            .volumex(MUSIC_VOLUME)
        )
        final_audio = CompositeAudioClip([audio.set_start(HOOK_DURATION), music])
    else:
        print("  [*] No music tracks found - skipping background music")
        final_audio = CompositeAudioClip([audio.set_start(HOOK_DURATION)])

    print("  [~] Compositing final video...")
    final = CompositeVideoClip([bg, hook_clip, card_clip] + captions, size=(VIDEO_W, VIDEO_H))
    final = final.set_audio(final_audio)

    out_name = f"video_{os.path.splitext(os.path.basename(audio_path))[0]}.mp4"
    out_path = os.path.join(OUTPUT_DIR, out_name)

    print(f"  [~] Exporting -> {out_path}")
    final.write_videofile(
        out_path,
        fps=VIDEO_FPS,
        codec="libx264",
        audio_codec="aac",
        threads=8,
        preset="ultrafast",
        logger="bar",
    )

    print(f"\n  [OK] Done! Video saved: {out_path}\n")
    return out_path


# ── MAIN ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Assemble a Reddit story short video.")
    parser.add_argument("--audio", required=True, help="Path to the story MP3 (from story_tts.py)")
    parser.add_argument("--meta",  required=True, help="Path to the story JSON (from story_tts.py)")
    parser.add_argument("--bg",    default=None,  help="Background video path (random if omitted)")
    parser.add_argument("--out",   default=None,  help="Output filename (auto-named if omitted)")
    args = parser.parse_args()

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with open(args.meta, "r", encoding="utf-8") as f:
        story = json.load(f)

    print(f"\n  === VIDEO ASSEMBLY ===\n")
    print(f"  [*] Story: {story['title']}")

    audio          = AudioFileClip(args.audio)
    duration       = audio.duration
    total_duration = HOOK_DURATION + duration
    print(f"  [*] Duration: {duration:.1f}s  (+{HOOK_DURATION}s hook = {total_duration:.1f}s total)")

    bg        = load_background(args.bg or pick_random_bg(), total_duration)
    hook_clip = make_hook_clip(HOOK_DURATION)
    card_clip = card_to_clip(story["title"], duration).set_start(HOOK_DURATION)
    words     = transcribe_audio(args.audio)
    captions  = [c.set_start(c.start + HOOK_DURATION) for c in build_caption_clips(words)]

    music_path = pick_random_music()
    if music_path:
        print(f"  [~] Adding music: {os.path.basename(music_path)}")
        music = (
            AudioFileClip(music_path)
            .fx(afx.audio_loop, duration=total_duration)
            .subclip(0, total_duration)
            .volumex(MUSIC_VOLUME)
        )
        final_audio = CompositeAudioClip([audio.set_start(HOOK_DURATION), music])
    else:
        print("  [*] No music tracks found - skipping background music")
        final_audio = CompositeAudioClip([audio.set_start(HOOK_DURATION)])

    print("  [~] Compositing final video...")
    final = CompositeVideoClip([bg, hook_clip, card_clip] + captions, size=(VIDEO_W, VIDEO_H))
    final = final.set_audio(final_audio)

    out_name = args.out or f"video_{os.path.splitext(os.path.basename(args.audio))[0]}.mp4"
    out_path = os.path.join(OUTPUT_DIR, out_name)

    print(f"  [~] Exporting -> {out_path}")
    final.write_videofile(
        out_path,
        fps=VIDEO_FPS,
        codec="libx264",
        audio_codec="aac",
        threads=8,
        preset="ultrafast",
        logger="bar",
    )

    print(f"\n  [OK] Done! Video saved: {out_path}\n")


if __name__ == "__main__":
    main()
