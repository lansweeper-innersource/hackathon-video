#!/usr/bin/env python3
"""Compose revid.ai project into an MP4 video with properly synced captions."""

import json
import os
import subprocess
import sys
from PIL import Image, ImageDraw, ImageFont

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(PROJECT_DIR, "hack-the-sweep.mp4")
IMAGES_DIR = os.path.join(PROJECT_DIR, "images")
FRAMES_DIR = os.path.join(PROJECT_DIR, "frames")
AUDIO_FILE = os.path.join(PROJECT_DIR, "audio", "voiceover.mp3")
STICKER_FILE = os.path.join(PROJECT_DIR, "stickers.png")
WIDTH = 1024
HEIGHT = 576
FPS = 30
CROSSFADE_DURATION = 0.4  # seconds for crossfade between different images


def load_project():
    with open(os.path.join(PROJECT_DIR, "project.json")) as f:
        return json.load(f)


def build_word_index(data):
    word_index = {}
    for segment in data["transcriptFull"]:
        for w in segment.get("words", []):
            word_index[w["id"]] = w
    return word_index


def build_per_slide_sequence(data, word_index):
    """Build one entry per slide (126 total) with image, caption, and timing."""
    slides = data["slides"]
    entries = []
    current_img = None

    for slide in slides:
        images = [m for m in slide.get("mediaList", []) if m.get("type") == "image"]
        if images:
            current_img = images[0]["url"].split("/")[-1]

        texts = slide.get("textList", [])
        caption = ""
        start = None
        end = None
        for t in texts:
            caption = t.get("value", "") or caption
            for wid in t.get("idWords", []):
                if wid in word_index:
                    w = word_index[wid]
                    if start is None or w["start"] < start:
                        start = w["start"]
                    if end is None or w["end"] > end:
                        end = w["end"]

        entries.append({
            "img": current_img,
            "caption": caption,
            "start": start,
            "end": end,
        })

    # Fill missing timings: interpolate between known timestamps
    # First pass: forward-fill missing starts from previous end
    for i in range(len(entries)):
        if entries[i]["start"] is None:
            if i > 0 and entries[i - 1]["end"] is not None:
                entries[i]["start"] = entries[i - 1]["end"]
            else:
                entries[i]["start"] = 0.0
        if entries[i]["end"] is None:
            # Look ahead for next known start
            for j in range(i + 1, len(entries)):
                if entries[j]["start"] is not None:
                    entries[i]["end"] = entries[j]["start"]
                    break
            if entries[i]["end"] is None:
                entries[i]["end"] = entries[i]["start"] + 1.0

    return entries


def find_font(size):
    font_paths = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Helvetica Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/SFCompact.ttf",
    ]
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                continue
    return ImageFont.load_default()


# Cache for loaded/scaled images
_img_cache = {}
_sticker = None


def load_sticker():
    """Load and scale the sticker overlay (with transparency)."""
    global _sticker
    if _sticker is not None:
        return _sticker

    sticker = Image.open(STICKER_FILE).convert("RGBA")
    # Scale sticker to ~18% of video height, preserving aspect ratio
    target_h = int(HEIGHT * 0.18)
    scale = target_h / sticker.height
    target_w = int(sticker.width * scale)
    sticker = sticker.resize((target_w, target_h), Image.LANCZOS)
    _sticker = sticker
    return _sticker


def get_base_image(img_name):
    """Load and scale an image, caching the result."""
    if img_name in _img_cache:
        return _img_cache[img_name].copy()

    img_path = os.path.join(IMAGES_DIR, img_name)
    img = Image.open(img_path).convert("RGB")

    # Scale to fit WIDTH x HEIGHT
    img_ratio = img.width / img.height
    canvas_ratio = WIDTH / HEIGHT
    if img_ratio > canvas_ratio:
        new_w = WIDTH
        new_h = int(WIDTH / img_ratio)
    else:
        new_h = HEIGHT
        new_w = int(HEIGHT * img_ratio)

    img = img.resize((new_w, new_h), Image.LANCZOS)

    canvas = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    x_offset = (WIDTH - new_w) // 2
    y_offset = (HEIGHT - new_h) // 2
    canvas.paste(img, (x_offset, y_offset))

    _img_cache[img_name] = canvas
    return canvas.copy()


def add_caption(canvas, caption):
    """Burn caption text onto a canvas image."""
    if not caption or not caption.strip() or caption.strip() == "\u200b":
        return

    draw = ImageDraw.Draw(canvas)
    font = find_font(28)

    # Word wrap
    words = caption.split()
    lines = []
    current_line = ""
    for word in words:
        test = f"{current_line} {word}".strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] > WIDTH - 80:
            if current_line:
                lines.append(current_line)
            current_line = word
        else:
            current_line = test
    if current_line:
        lines.append(current_line)

    line_height = 36
    total_height = len(lines) * line_height
    y_start = HEIGHT - total_height - 35

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        text_w = bbox[2] - bbox[0]
        x = (WIDTH - text_w) // 2
        y = y_start + i * line_height

        # Black outline
        for dx in range(-3, 4):
            for dy in range(-3, 4):
                if dx * dx + dy * dy <= 9:
                    draw.text((x + dx, y + dy), line, font=font, fill=(0, 0, 0))
        # White text
        draw.text((x, y), line, font=font, fill=(255, 255, 255))


def add_sticker(canvas):
    """Overlay the sticker in the top-right corner."""
    sticker = load_sticker()
    margin = 15
    x = WIDTH - sticker.width - margin
    y = margin
    canvas.paste(sticker, (x, y), sticker)


def render_frame(canvas, output_path):
    """Save a composed canvas to disk."""
    canvas.save(output_path, quality=95)


def compose_video(entries):
    """Render frames at FPS with crossfade transitions and sticker overlay, stitch with ffmpeg."""
    os.makedirs(FRAMES_DIR, exist_ok=True)

    # Clean old frames
    for f in os.listdir(FRAMES_DIR):
        if f.endswith(".jpg"):
            os.remove(os.path.join(FRAMES_DIR, f))

    # Compute each slide's display interval on the absolute timeline:
    # from its start to the next slide's start (or audio end for last slide)
    audio_duration = float(
        subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", AUDIO_FILE],
            capture_output=True, text=True
        ).stdout.strip() or "0"
    )
    for i in range(len(entries) - 1):
        entries[i]["display_end"] = entries[i + 1]["start"]
    entries[-1]["display_end"] = audio_duration

    total_frames = int(audio_duration * FPS)
    crossfade_frames = int(CROSSFADE_DURATION * FPS)

    # Detect image change points for crossfades
    image_changes = set()
    for i in range(1, len(entries)):
        if entries[i]["img"] != entries[i - 1]["img"]:
            image_changes.add(i)

    print(f"Rendering ~{total_frames} frames at {FPS}fps ({audio_duration:.1f}s)...")
    print(f"  {len(image_changes)} image transitions with {CROSSFADE_DURATION}s crossfade")

    frame_num = 0
    for i, entry in enumerate(entries):
        # Frame count from absolute start to absolute display_end
        frame_start = round(entry["start"] * FPS)
        frame_end = round(entry["display_end"] * FPS)
        n_frames = max(1, frame_end - frame_start)

        # Prepare the base canvas for this slide
        base = get_base_image(entry["img"])
        add_caption(base, entry["caption"])
        add_sticker(base)

        # Check if this slide starts with a crossfade from previous image
        is_transition = i in image_changes
        if is_transition and i > 0:
            prev_base = get_base_image(entries[i - 1]["img"])
            add_caption(prev_base, entries[i - 1]["caption"])
            add_sticker(prev_base)
            fade_frames = min(crossfade_frames, n_frames)
        else:
            fade_frames = 0

        for f_idx in range(n_frames):
            if f_idx < fade_frames:
                # Crossfade: blend previous image into current
                alpha = f_idx / fade_frames
                blended = Image.blend(prev_base, base, alpha)
                frame_path = os.path.join(FRAMES_DIR, f"f_{frame_num:06d}.jpg")
                render_frame(blended, frame_path)
            else:
                frame_path = os.path.join(FRAMES_DIR, f"f_{frame_num:06d}.jpg")
                render_frame(base, frame_path)
            frame_num += 1

        if i % 10 == 0:
            print(f"  slide {i}/{len(entries)}, frame {frame_num}...")

    print(f"  Total frames rendered: {frame_num}")

    print("\nComposing video with ffmpeg...")
    frame_pattern = os.path.join(FRAMES_DIR, "f_%06d.jpg")
    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(FPS),
        "-i", frame_pattern,
        "-i", AUDIO_FILE,
        "-c:v", "libx264", "-preset", "medium", "-crf", "23",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        OUTPUT_FILE,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("STDERR:", result.stderr[-3000:])
        sys.exit(1)

    size_mb = os.path.getsize(OUTPUT_FILE) / (1024 * 1024)
    duration_s = float(
        subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", OUTPUT_FILE],
            capture_output=True, text=True
        ).stdout.strip() or "0"
    )
    print(f"\nDone! {OUTPUT_FILE}")
    print(f"  Duration: {int(duration_s // 60)}:{int(duration_s % 60):02d}")
    print(f"  Size: {size_mb:.1f} MB")


def main():
    data = load_project()
    word_index = build_word_index(data)
    entries = build_per_slide_sequence(data, word_index)

    print(f"Built {len(entries)} slides")
    for i, e in enumerate(entries):
        print(f"  {i:3d}: {e['start']:7.2f}s - {e['end']:7.2f}s  {e['img']:30s}  {e['caption'][:50]}")
    print()

    compose_video(entries)


if __name__ == "__main__":
    main()
