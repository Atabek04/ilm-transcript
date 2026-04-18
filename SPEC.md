# Islamic Lecture Transcription Pipeline — Spec

> **Version:** 0.2 · **Author:** Ayub · **Status:** Draft

---

## Problem Statement

Two recurring workflows, one shared pain:

1. **English lecture with Arabic terms** — lecturer switches between English and Islamic Arabic vocabulary. Standard STT either drops Arabic script or transliterates it into Latin.
2. **Pure Arabic lecture** — needs full Arabic script output, ready for Obsidian + Anki.

Goal: a local CLI tool that handles both modes, outputs clean markdown, and feeds directly into the Obsidian/Anki study workflow.

Future goal: a Telegram bot that wraps the same pipeline — send a YouTube URL, receive a formatted document (DOCX, PDF, or MD) back in chat.

---

## Chain of Thought: Key Decisions

### Decision 1 — Subtitle-first strategy

YouTube often has auto-generated or manual Arabic subtitles. Downloading them is instant and free, with better word boundaries than Whisper on fast Arabic speech.

→ **Rule (Phase 2):** opt-in via `--subs-first` flag. When set, attempt `yt-dlp --write-subs --write-auto-subs --sub-langs ar` before downloading audio. If a subtitle track is returned, use it and skip Whisper entirely. If none is returned, fall back to the normal Whisper pipeline.

→ **"Low quality" is not auto-detected.** If the user is unhappy with subtitle output, they re-run without `--subs-first`. Cheap, explicit, no heuristic to maintain.

→ **Scope:** only applies when `--mode ar`. In `en-ar` mode, Arabic-only subtitle tracks drop all the English content, so subs are never used.

**Pros:** fast, zero compute, good for Arabic channels with auto-subs  
**Cons:** auto-subs on Arabic are often unvoweled, no harakats, occasional errors

### Decision 2 — Whisper model choice

| Model | Size | Speed (CPU) | Arabic Quality |
|---|---|---|---|
| `base` | 74MB | 20x RT | Poor |
| `medium` | 769MB | 5x RT | Acceptable |
| `large-v3` | 1.5GB | 1x RT | Best |
| `large-v3-turbo` | 809MB | 2x RT | Near-best |

→ **Default: `large-v3-turbo`** via `faster-whisper`. Best accuracy/speed tradeoff. Runs on CPU with INT8.

### Decision 3 — Code-switching handling

Standard Whisper with `language=en` set → Arabic words get transliterated into Latin. Unacceptable.

→ **Mode A `en-ar` (default — English + Arabic terms):** do NOT set language parameter. Let Whisper auto-detect per 30s chunk. Arabic phrases surface in Arabic script. English stays English.

→ **Mode B `ar` (Pure Arabic):** set `language=ar` explicitly. Full Arabic script output.

Only these two modes exist. There is no `en`-only mode — if the user wants pure English, they can still use `en-ar` (auto-detect will stay in English for English audio). Keeping mode count at two avoids a third code path.

**Pros of auto-detect:** handles mixed speech naturally  
**Cons:** occasionally misdetects a chunk; needs Claude post-processing to fix

### Decision 4 — Architecture style

Options considered: web app, Jupyter notebook, CLI script.

→ **CLI script.** You're the only user. You're a senior DevOps engineer. No web server overhead, no dependencies beyond Python. Runs unattended overnight for 9-hour files.

### Decision 5 — Long audio handling

Whisper's receptive field is 30 seconds. Two strategies: sequential (accurate, slow) vs chunked (fast, slight seam risk).

→ **Use `faster-whisper` with `vad_filter=True`.** It handles chunking internally and strips silence before processing, reducing hallucinations on quiet gaps.

### Decision 6 — Output format

Raw transcript alone is not useful. The output must be immediately pasteable into Claude for note generation.

→ Three output files per run, written inside `output/{sanitized-title}/`:
- `transcript_raw.txt` — timestamped raw Whisper output
- `transcript_clean.md` — paragraph-grouped transcript (auto-cleaned)
- `meta.json` — source URL, duration, language mode, model, timestamps

File names are fixed (not templated on title) because the containing folder already carries the title. This keeps paths predictable for downstream tooling and avoids double-escaping title sanitization.

### Decision 7 — Standalone YouTube-to-Audio converter

The audio download step is reusable beyond transcription (archiving, re-processing, sharing). It is extracted as a standalone `convert.py` tool.

→ **Rule:** `transcribe.py` calls `convert.py`'s download function internally. `convert.py` is also usable standalone.

**Audio format choice:**
- `m4a` (AAC) — default for Whisper input. Best quality/size, lossless container from YouTube.
- `mp3` — export format for sharing / external tools. Re-encoded via ffmpeg at 320kbps VBR.
- `wav` / `opus` / `flac` — available via `--format` flag; niche use.

**Quality default:** `yt-dlp` `format: bestaudio/best` + postprocessor `preferredquality: "0"` (best VBR). Never re-encode unnecessarily — if source is already m4a/AAC, skip re-encode.

**Note on MP3 bitrate:** `preferredquality: "0"` passed to `FFmpegExtractAudio` for MP3 invokes LAME `-V0`, which is VBR averaging ~220–260 kbps (highest VBR quality), NOT constant 320 kbps. This is intentional — V0 is indistinguishable from 320 CBR at a smaller file size. If a user needs strict 320 CBR, that is an explicit future flag, not the default.

### Decision 8 — Telegram bot (post-MVP)

Ayub wants to send a YouTube URL to a Telegram bot and receive a finished document (DOCX, PDF, or MD) back. The bot is a thin wrapper around the existing pipeline.

→ **Architecture:** bot receives URL → enqueues job → runs `transcribe.py` pipeline → renders output → sends file back.

→ **Not in Phase 1.** Bot is Phase 4. No bot code in core pipeline files. Core pipeline must stay importable as a library (no `sys.exit()` in functions, only in `main()`).

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        CLI Entry Point                       │
│              python transcribe.py <URL or FILE>             │
│                   --mode [en-ar | ar]                       │
└─────────────────────┬───────────────────────────────────────┘
                      │
          ┌───────────▼───────────┐
          │    Source Resolver    │
          │  YouTube URL → audio  │
          │  Local file → pass    │
          └───────────┬───────────┘
                      │
          ┌───────────▼───────────┐
          │   Subtitle Check      │  ← yt-dlp --write-subs
          │  (YouTube URLs only)  │  → if found: skip Whisper
          └───────────┬───────────┘
                      │ (no subs / local file)
          ┌───────────▼───────────┐
          │    Audio Downloader   │  ← convert.py (yt-dlp + ffmpeg)
          │   yt-dlp → m4a        │  best audio, skip re-encode
          └───────────┬───────────┘
                      │
          ┌───────────▼───────────┐
          │     Transcriber       │  ← faster-whisper large-v3-turbo
          │  Mode A: no lang lock │  (English + Arabic mixed)
          │  Mode B: lang=ar      │  (pure Arabic)
          │  vad_filter=True      │
          │  word_timestamps=True │
          └───────────┬───────────┘
                      │
          ┌───────────▼───────────┐
          │    Output Writer      │
          │  _raw.txt             │  timestamped segments
          │  _clean.md            │  grouped paragraphs
          │  _meta.json           │  run metadata
          └───────────────────────┘


Future (Phase 4):

┌──────────────────────────────────────────────────────────────┐
│                      Telegram Bot                            │
│  python bot.py                                               │
│  User sends URL → bot.py → transcribe pipeline → render      │
│  → sends DOCX / PDF / MD back to user                       │
└──────────────────────────────────────────────────────────────┘
```

---

## File Structure

```
ilm-transcript/
├── transcribe.py          # main transcription entry point
├── convert.py             # standalone YouTube → audio converter
├── bot.py                 # Phase 4 — Telegram bot (not yet)
├── requirements.txt
├── README.md
└── output/
    └── {sanitized-title}/           # ASCII-slug of yt-dlp title; falls back to video id if slug empty
        ├── audio.m4a                # downloaded audio, OR symlink to local input file
        ├── audio.mp3                # only if --format mp3 used in convert.py
        ├── transcript_raw.txt
        ├── transcript_clean.md
        └── meta.json
```

---

## CLI Interface

```bash
# YouTube URL, English lecture with Arabic terms
python transcribe.py "https://youtube.com/watch?v=XXX" --mode en-ar

# YouTube URL, pure Arabic lecture
python transcribe.py "https://youtube.com/watch?v=XXX" --mode ar

# Local MP3/MP4 file (symlinked as audio.<ext> inside output/{slug}/)
python transcribe.py ./lecture.mp3 --mode en-ar

# Use subtitle shortcut if available — Phase 2, --mode ar only
python transcribe.py "https://youtube.com/watch?v=XXX" --mode ar --subs-first

# Standalone audio converter — download best quality m4a
python convert.py "https://youtube.com/watch?v=XXX"

# Download and export as MP3 (re-encoded at 320kbps)
python convert.py "https://youtube.com/watch?v=XXX" --format mp3

# Download playlist, export as m4a
python convert.py "https://youtube.com/playlist?list=XXX" --format m4a
```

---

## convert.py — Standalone YouTube-to-Audio Converter

### Purpose

A focused tool for downloading YouTube video or playlist audio in high quality. Reused internally by `transcribe.py`. Also useful standalone for archiving lectures before transcribing, or sharing MP3s.

### Design Principles

- Uses `yt-dlp` directly (no wrapper libraries).
- Never re-encodes if source codec matches target (avoids quality loss).
- Progress hook via `yt-dlp`'s native `progress_hooks` — no subprocess polling.
- Detects ffmpeg at startup; fails with clear message if absent.
- Idempotent: skip if output file already exists (override with `--force`).

### Supported Formats

| Flag | Output | Notes |
|---|---|---|
| `m4a` (default) | AAC in M4A container | Best for Whisper input; lossless if source is AAC |
| `mp3` | MP3 @ VBR quality 0 | For sharing / external tools |
| `wav` | PCM WAV | Lossless; large files |
| `opus` | Opus in WebM | Best compression; niche compatibility |
| `flac` | FLAC | Lossless archive |

### CLI Contract

```
usage: convert.py [-h] [--format {m4a,mp3,wav,opus,flac}]
                  [--output-dir DIR] [--force]
                  url

positional arguments:
  url                   YouTube video or playlist URL

options:
  --format              Output audio format (default: m4a)
  --output-dir          Output directory (default: ./output)
  --force               Re-download even if file exists
```

### yt-dlp Options Used

```python
ydl_opts = {
    "format": "bestaudio/best",
    # Per-video subfolder; file inside is always "audio.<ext>" after postprocessing rename.
    "outtmpl": str(output_dir / "%(title)s" / "audio.%(ext)s"),
    "restrictfilenames": True,         # ASCII-only folder slug; Arabic title preserved in meta.json
    "postprocessors": [{
        "key": "FFmpegExtractAudio",
        "preferredcodec": target_format,   # "mp3", "m4a", etc.
        "preferredquality": "0",           # VBR best
    }],
    "quiet": True,
    "no_warnings": True,
    "progress_hooks": [progress_hook],
    "ignoreerrors": False,                 # fail loudly on single video
    "lazy_playlist": True,                 # stream playlist entries
}
```

**Note:** when `target_format` is `m4a` and the source is already AAC, yt-dlp will remux without re-encoding. For `mp3`, it always re-encodes. This is the correct behaviour.

### Progress Hook Pattern

```python
def progress_hook(d: dict) -> None:
    if d["status"] == "downloading":
        pct = d.get("_percent_str", "?%").strip()
        speed = d.get("_speed_str", "?").strip()
        logging.info(f"Downloading: {pct} at {speed}")
    elif d["status"] == "finished":
        logging.info(f"Download done: {d['filename']}")
```

---

## Dependencies

```
faster-whisper>=1.0.0      # Whisper with CTranslate2 backend (4x faster than original)
yt-dlp>=2025.1.0           # YouTube download + subtitle extraction
ffmpeg                     # system dependency, audio conversion
```

Phase 4 additions (Telegram bot, not yet):
```
python-telegram-bot>=21.0  # async Telegram bot framework
python-docx>=1.1.0         # DOCX rendering
reportlab>=4.0.0           # PDF rendering
```

No GPU required. No web framework. No database.

---

## Local File Handling

When `source` is a local file (detected by `Path(source).exists()` before URL parsing):

1. Derive a slug from the filename stem (ASCII-sanitize, fall back to `audio-<sha1[:8]>` if empty).
2. Create `output/{slug}/`.
3. Symlink the source as `output/{slug}/audio.{ext}` (never copy — the file may be large). On Windows or when symlinks are unavailable, fall back to a copy and log a warning.
4. Proceed to the transcriber step. Skip subtitle and download stages.

The `meta.json` `source` field records the absolute path of the original file.

---

## Idempotency

Skip rules (all can be overridden with `--force`):

- **Download skip:** `output/{slug}/audio.m4a` exists and is non-empty.
- **Transcribe skip:** `output/{slug}/transcript_raw.txt` AND `output/{slug}/meta.json` exist AND `meta.json.language_mode` matches the requested `--mode`. If the mode differs, re-transcribe (do not silently serve a stale transcript).
- **Subtitle skip (Phase 2):** no caching — `--subs-first` always re-fetches subs when invoked.

---

## Output Contract

### `transcript_raw.txt`
```
[0.0s → 4.1s] In the name of Allah, the Most Gracious
[4.2s → 6.7s] what we call in Arabic التَّوَكُّل
[6.8s → 9.2s] which means reliance upon Allah
```

### `transcript_clean.md`
```markdown
---
source: https://youtube.com/watch?v=XXX
title: Understanding Tawakkul - Sheikh Haitham
date: 2026-04-15
mode: en-ar
duration: 9h 12m
model: large-v3-turbo
subtitle_source: whisper
---

In the name of Allah, the Most Gracious. What we call in Arabic التَّوَكُّل,
which means complete reliance upon Allah...
```

### `meta.json`
```json
{
  "url": "...",
  "title": "...",
  "duration_seconds": 33120,
  "language_mode": "en-ar",
  "model": "large-v3-turbo",
  "subtitle_source": "whisper",
  "created_at": "2026-04-15T10:00:00Z"
}
```

---

## Post-Processing Workflow (Claude)

After the tool outputs `transcript_clean.md`, paste it to Claude with one of these prompts:

**For Obsidian atomic notes:**
> "From this lecture transcript, extract atomic notes in Obsidian markdown. One concept per note. Include the Arabic term with full harakats, its meaning, and a short explanation. Use frontmatter with tags: `islamic-concept`, `arabic-term`."

**For Anki flashcards:**
> "From this transcript, extract Islamic Arabic terms. For each term produce: Arabic with harakats (front), meaning + usage context from lecture (back). Format as tab-separated CSV."

---

## Phases

**Phase 1 — MVP (do first)**
- `transcribe.py` with `en-ar` and `ar` modes
- yt-dlp download + faster-whisper transcription
- `transcript_raw.txt`, `transcript_clean.md`, and `meta.json` output
- `convert.py` standalone audio downloader (m4a + mp3 support)

**Phase 2 — Quality of Life**
- `--subs-first` flag for YouTube subtitle shortcut
- Automatic audio splitting at silence for files >3h (reduces hallucination risk)
- Progress bar with ETA

**Phase 3 — Optional CLI polish**
- Config file (`~/.transcriber.toml`) for default mode and output path
- Dry-run mode: show video title + duration before downloading
- Playlist batch processing for `convert.py`

**Phase 4 — Telegram Bot**
- `bot.py` — async Telegram bot using `python-telegram-bot`
- User sends YouTube URL in chat
- Bot runs transcription pipeline (calls `transcribe.py` functions as library)
- Bot renders output as DOCX, PDF, or MD (user's choice)
- Bot sends file back to user
- Deployment: runs as a systemd service or Docker container on a VPS
- Job queue: simple asyncio queue (no Celery — single user, no concurrency needed)
- Document formats supported: DOCX (`python-docx`), PDF (`reportlab`), MD (plain file)

---

## Known Limitations

- Arabic auto-detect per 30s chunk: occasional English segment misdetected as Arabic. Fix in post-processing with Claude.
- No harakats from Whisper — Whisper outputs unvoweled Arabic. Claude adds harakats in the post-processing step.
- 9-hour files on CPU: expect ~2–4 hours of processing time. Run overnight.
- YouTube rate limits: add `--sleep-interval 3` to yt-dlp opts if downloading playlists.
- MP3 re-encode from AAC is a lossy generation loss. Unavoidable — use m4a when quality matters.
