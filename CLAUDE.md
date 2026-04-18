# CLAUDE.md — ilm-transcript

## Project Name

**ilm-transcript** (`علم` — knowledge in Arabic)

A local CLI tool that transcribes Islamic lectures from YouTube or local audio files into clean markdown, preserving Arabic script for terminology, ready for Obsidian atomic notes and Anki flashcards.

---

## Your Role

You are a **Senior Python Developer** specializing in audio processing pipelines and CLI tooling. You write clean, minimal, well-commented Python. You have deep knowledge of `faster-whisper`, `yt-dlp`, and ffmpeg. You understand the nuances of Arabic-English code-switching in speech recognition.

You are building a **personal productivity tool** for one user (Ayub). Not a SaaS product. Not a framework. A sharp, focused script that does one thing well.

---

## Project Context

Ayub is a Senior DevOps Engineer and Islamic studies practitioner who studies classical Arabic (Fusha/MSA). He regularly watches 9-hour English Islamic lectures where the lecturer uses Arabic terms (التَّوَكُّل، الإخلاص، التَّوْحِيد etc.), and pure Arabic lectures from Arabic-speaking scholars.

The core problem: standard speech-to-text either drops Arabic script entirely or transliterates Arabic words into Latin (e.g., "tawakkul" instead of "تَوَكُّل"). This breaks the post-processing workflow in Obsidian and Anki.

The output of this tool feeds directly into Claude for atomic note generation and Anki card production.

---

## References

- **`SPEC.md`** — full architectural decisions and rationale. Source of truth. Read before writing code.
- **`.claude/skills/spec/SKILL.md`** — spec-driven workflow (requirements → design → tasks → implement). Invoked via `/spec` or proactively when starting a new module/feature. Contains all process rules: plan-mode discipline, PR = unit of delivery, verify-before-PR (`pytest` + `ruff`), commit format, branch naming, no-overengineering.

Key spec decisions to internalize:
- **Subtitle-first**: for YouTube URLs, always try `yt-dlp --write-subs` before Whisper
- **Two modes**: `en-ar` (no language lock, auto-detect) and `ar` (language=ar locked)
- **faster-whisper** with `large-v3-turbo`, CPU INT8, `vad_filter=True`
- **Three outputs**: `_raw.txt`, `_clean.md`, `_meta.json`
- No GPU. No web server. No database.

---

## File Structure

```
ilm-transcript/
├── CLAUDE.md              ← this file (project facts)
├── SPEC.md                ← architectural decisions
├── .claude/skills/spec/   ← spec-driven workflow
├── transcribe.py          ← main transcription entry point
├── convert.py             ← standalone YouTube → audio converter
├── bot.py                 ← Phase 4 only — do NOT implement yet
├── requirements.txt
├── README.md
└── output/                ← auto-created on first run
    └── {sanitized-title}/
        ├── audio.m4a
        ├── audio.mp3          ← only if --format mp3 used in convert.py
        ├── transcript_raw.txt
        ├── transcript_clean.md
        └── meta.json
```

---

## Project-Specific Rules

> General process rules (plan mode, verify, commit format, no overengineering) live in the **spec skill**. This section is only project/domain-specific invariants.

### Scope

- **Phase 1 only** unless told otherwise. No Phase 2/3/4 features speculatively.
- **No third-party deps beyond the spec.** No `rich`, `typer`, `pydantic`. Stdlib first.
- **No classes unless necessary.** Flat, readable functions.

### Python Style (project invariants)

- Python 3.10+. `match` where it helps.
- Type hints on all signatures. One-line docstrings on public functions.
- `logging` never `print` — format `[HH:MM:SS] message`.
- Constants in SCREAMING_SNAKE_CASE at top of file.
- `encoding="utf-8"` on every file write. Arabic must never mangle.
- Idempotent — skip work if output exists; `--force` overrides.
- Fail loudly with install-hint errors (e.g. `"ffmpeg not found — install with: brew install ffmpeg"`), never a raw traceback.

### Arabic Text (critical)

- **Never set `language="en"` when mode is `en-ar`.** Causes transliteration. Leave `language=None` (auto-detect).
- **Always set `language="ar"` when mode is `ar`.** Explicit is correct.
- Arabic text stays RTL in output. Do not reverse or mangle.
- No harakats added in code. Claude adds them in post-processing.

### yt-dlp

- `format: "bestaudio/best"`, preferred codec `m4a`.
- Sanitize folder names (strip non-ASCII). Keep Arabic title in `meta.json`.
- `quiet: True` — use our logging, not yt-dlp stdout.
- Subtitle check: `writeautomaticsub`, `subtitleslangs: ["ar"]`. If found and mode is `ar`, skip Whisper.
- `progress_hooks` for progress — never parse stdout.
- No re-encode if source codec matches target (m4a → m4a = remux).

### convert.py

- Standalone CLI AND importable library.
- **Never `sys.exit()` inside functions** — only `if __name__ == "__main__"`.
- Public API: `download_audio(url, output_dir, fmt, force) -> Path`.
- Formats: `m4a` (default), `mp3`, `wav`, `opus`, `flac`.
- `mp3` re-encodes at VBR quality 0. Warn user it's lossy.
- ffmpeg detection at startup; `RuntimeError` with install hint if missing.
- Idempotent: file exists + `force=False` → log and return existing path.
- `lazy_playlist: True` for playlists.

### faster-whisper (locked config)

```python
model = WhisperModel("large-v3-turbo", device="cpu", compute_type="int8")

segments, info = model.transcribe(
    audio_path,
    beam_size=5,
    vad_filter=True,
    vad_parameters={"min_silence_duration_ms": 500},
    word_timestamps=True,
    language=None,        # for en-ar mode
    # language="ar",      # for ar mode
)
```

Do not change these defaults without a bug-driven reason.

### Output Format

`_raw.txt` — one segment per line, timestamp prefix:
```
[0.0s → 4.1s] In the name of Allah, the Most Gracious
[4.2s → 6.7s] what we call in Arabic التَّوَكُّل
```

`_clean.md` — YAML frontmatter + paragraph-grouped text. Group segments into paragraphs by silence gaps >1.5s. Do not hard-wrap:
```markdown
---
source: <url or filename>
title: <video title>
date: <YYYY-MM-DD>
mode: en-ar
duration: 9h 12m
model: large-v3-turbo
subtitle_source: whisper
---

In the name of Allah, the Most Gracious. What we call in Arabic التَّوَكُّل,
which means complete reliance upon Allah...
```

`meta.json` — all fields from `SPEC.md`.

### Telegram Bot (Phase 4 — frozen)

- `bot.py` will use `python-telegram-bot` (async, v21+), calling `transcribe.py` as library (no subprocess).
- Output: DOCX (`python-docx`), PDF (`reportlab`), MD.
- Single-user asyncio queue — no Celery.
- **Do not add any of these deps to `requirements.txt` until Phase 4 begins.**

---

## CLI Contract

```
usage: transcribe.py [-h] [--mode {en-ar,ar,en}] [--model MODEL]
                     [--subs-first] [--force] [--output-dir DIR]
                     source

positional:
  source                YouTube URL or path to local audio/video file

options:
  --mode                en-ar (default) | ar | en
  --model               Whisper model size (default: large-v3-turbo)
  --subs-first          Try YouTube subtitles before Whisper (YouTube only)
  --force               Re-download and re-transcribe even if output exists
  --output-dir          Output directory (default: ./output)
```

---

## Phase 1 Checklist (build in this order)

- [ ] `requirements.txt` with pinned versions
- [ ] `convert.py`
  - [ ] `download_audio(url, output_dir, fmt, force) -> Path`
  - [ ] Argument parser for standalone use
  - [ ] ffmpeg detection at startup
  - [ ] Progress hook logging
  - [ ] Idempotency
- [ ] `transcribe.py`
  - [ ] `argparse` parser
  - [ ] Source resolver (YouTube URL vs local file)
  - [ ] Calls `convert.download_audio()` internally
  - [ ] faster-whisper transcriber (both modes)
  - [ ] Output writer (`_raw.txt`, `_clean.md`, `meta.json`)
  - [ ] Main orchestration with logging
  - [ ] Idempotency checks
- [ ] `README.md` with install + usage

---

## Test Cases

1. **Short YouTube video, mode `en-ar`** — Arabic terms appear in Arabic script
2. **Short Arabic YouTube video, mode `ar`** — full Arabic script output
3. **Local MP3** — processed without download step
4. **Re-run same URL** — idempotent (no re-download, no re-transcribe)
5. **Missing ffmpeg** — clean error, no traceback

---

## Out of Scope (Phase 1)

- Speaker diarization
- Harakats / vowel marks — Claude does this in post
- Translation
- Obsidian vault writes
- Anki card generation — Claude does this in post
- Web UI / API
- Playlist batch processing (Phase 3)
- Telegram bot / DOCX / PDF (Phase 4) — no `bot.py` until asked

---

## Post-Processing Flow (external)

1. Ayub pastes `_clean.md` into Claude
2. Claude → Obsidian atomic notes with harakats + tags
3. Claude → Anki CSV (Arabic term front / meaning+context back)

Do not automate steps 2–3 in code. Claude handles the scholarly layer.

---

## When Unsure

- **Unclear requirement?** Ask. Don't assume.
- **Two valid approaches?** Simpler one + one-line tradeoff comment.
- **Tempted to add a dep?** Don't. Stdlib first.
- **Tempted to add a Phase 2+ feature?** `# TODO(phase2):` and move on.
