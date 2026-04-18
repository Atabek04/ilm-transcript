# ilm-transcript

> **علم** — knowledge in Arabic

A local CLI tool that transcribes Islamic lectures from YouTube or local audio files into clean markdown, preserving Arabic script for terminology. Output feeds directly into Claude for Obsidian atomic notes and Anki flashcard generation.

---

## Install

**1. Install ffmpeg** (system dependency):
```bash
brew install ffmpeg
```

**2. Install Python dependencies** (using [uv](https://github.com/astral-sh/uv)):
```bash
uv sync
```

Or with pip in a virtualenv:
```bash
pip install faster-whisper>=1.0.0 yt-dlp>=2025.1.0
```

---

## Usage

### Transcribe a YouTube lecture

```bash
# English lecture with Arabic terms (default mode)
uv run python transcribe.py "https://youtube.com/watch?v=XXX" --mode en-ar

# Pure Arabic lecture
uv run python transcribe.py "https://youtube.com/watch?v=XXX" --mode ar
```

### Transcribe a local audio file

```bash
uv run python transcribe.py ./lecture.mp3 --mode en-ar
```

### Re-run with force (re-download + re-transcribe)

```bash
uv run python transcribe.py "https://youtube.com/watch?v=XXX" --mode ar --force
```

### Full options

```
usage: transcribe.py [-h] [--mode {en-ar,ar,en}] [--model MODEL]
                     [--subs-first] [--force] [--output-dir DIR]
                     source

positional:
  source          YouTube URL or path to local audio/video file

options:
  --mode          en-ar (default) | ar | en
  --model         Whisper model name (default: large-v3-turbo)
  --subs-first    Try YouTube subtitles before Whisper — Phase 2, not yet active
  --force         Re-download and re-transcribe even if output exists
  --output-dir    Output directory (default: ./output)
```

### Download audio only (convert.py)

```bash
# Download best quality m4a (default)
uv run python convert.py "https://youtube.com/watch?v=XXX"

# Download and re-encode as MP3
uv run python convert.py "https://youtube.com/watch?v=XXX" --format mp3

# Download playlist
uv run python convert.py "https://youtube.com/playlist?list=XXX" --format m4a
```

---

## Output

Each run produces three files inside `output/{sanitized-title}/`:

| File | Contents |
|---|---|
| `transcript_raw.txt` | Timestamped segments: `[0.0s → 4.1s] text` |
| `transcript_clean.md` | YAML frontmatter + paragraph-grouped transcript |
| `meta.json` | URL, title, duration, mode, model, timestamps |

Arabic script is preserved verbatim. Harakats (vowel marks) are added in post-processing via Claude.

---

## Performance

- Model: `large-v3-turbo` (default) — best accuracy/speed tradeoff on CPU
- A **9-hour lecture** takes approximately **2–4 hours** on CPU. Run overnight.
- No GPU required.

---

## Post-processing with Claude

Paste `transcript_clean.md` into Claude with one of these prompts:

**Obsidian atomic notes:**
> "From this lecture transcript, extract atomic notes in Obsidian markdown. One concept per note. Include the Arabic term with full harakats, its meaning, and a short explanation."

**Anki flashcards:**
> "From this transcript, extract Islamic Arabic terms. For each: Arabic with harakats (front), meaning + usage context (back). Format as tab-separated CSV."

---

## Contributing

- Architecture decisions: [`SPEC.md`](SPEC.md)
- Project rules and code style: [`CLAUDE.md`](CLAUDE.md)

Run tests before opening a PR:
```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```
