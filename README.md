# Hack the Sweep

Lansweeper Engineering hackathon anthem video for **RE:CONNECT 2026** in Szczyrk, Poland.

## What's in this repo

```
images/           40 AI-generated slide images (1024x576)
audio/            voiceover.mp3 - AI-generated audio track (~2:22)
project.json      Project definition (slides, transcripts, word-level timestamps)
stickers.png      "Vibe Outside the Box" hackathon logo overlay (transparent PNG)
compose_video.py  Python script to compose the final MP4 video
thumbnail.jpeg    Video thumbnail
```

## How to build the video

### Prerequisites

- Python 3.10+
- [Pillow](https://pillow.readthedocs.io/) (`pip install Pillow`)
- [ffmpeg](https://ffmpeg.org/) with libx264 and AAC support

### Build

```bash
python compose_video.py
```

This will:
1. Parse `project.json` for slide sequence and word-level timestamps
2. Render ~4300 frames at 30fps with captions and sticker overlay
3. Apply crossfade transitions between image changes
4. Stitch frames with audio using ffmpeg

Output: `hack-the-sweep.mp4` (~13 MB, 2:22, 1024x576)

## How it works

The script composes a video from a JSON project definition containing slide sequences, images, and word-level audio timestamps:

- **126 slides** mapped to **40 unique images** with word-level transcript timestamps
- Each slide displays its caption phrase synced to when the words are spoken in the audio
- Crossfade transitions (0.4s) are applied when the background image changes
- The hackathon sticker is composited in the top-right corner of every frame

## License

Internal Lansweeper content - not for public distribution.
