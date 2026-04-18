# TASKS — ilm-transcript Phase 1

> Source of truth: `SPEC.md` + `CLAUDE.md`. Workflow: `.claude/skills/spec/SKILL.md`.
> Implement via `/spec implement transcribe [PR<N>]`. PR is the unit of delivery.

## PR Plan

| PR  | Tasks              | Description                                                  |
|-----|--------------------|--------------------------------------------------------------|
| PR1 | T1, T2, T3         | Foundation — deps, logging config, ffmpeg detection, slug utils |
| PR2 | T4, T5             | `convert.py` — `download_audio()` + standalone CLI           |
| PR3 | T6, T7             | `transcribe.py` — source resolver + Whisper transcriber      |
| PR4 | T8, T9 [P], T10 [P]| Output writers — `_raw.txt`, `_clean.md`, `meta.json`        |
| PR5 | T11, T12           | `transcribe.py` orchestration + idempotency + README         |

---

## Tasks

### Task 1 (PR1): Create `requirements.txt` with pinned deps
- **Complexity:** S
- **PR:** PR1
- **Depends on:** —
- **Deliverable:** `requirements.txt`
- **Acceptance criteria:**
  - [ ] `faster-whisper>=1.0.0` pinned
  - [ ] `yt-dlp>=2025.1.0` pinned
  - [ ] No Phase 4 deps (`python-telegram-bot`, `python-docx`, `reportlab`)
  - [ ] `pip install -r requirements.txt` succeeds in a fresh venv

### Task 2 (PR1): Shared utils — logging config + slug sanitizer
- **Complexity:** S
- **PR:** PR1
- **Depends on:** —
- **Deliverable:** `utils.py` (or inline in both scripts if < 30 LOC total)
- **Acceptance criteria:**
  - [ ] `configure_logging()` sets format `[HH:MM:SS] message` via `logging` module
  - [ ] `sanitize_slug(title: str) -> str` — ASCII-only, falls back to `audio-<sha1[:8]>` if empty
  - [ ] All file writes in the codebase use `encoding="utf-8"` (grep-enforceable)

### Task 3 (PR1): ffmpeg detection helper
- **Complexity:** S
- **PR:** PR1
- **Depends on:** T2
- **Deliverable:** `check_ffmpeg() -> None` in `utils.py`
- **Acceptance criteria:**
  - [ ] Raises `RuntimeError("ffmpeg not found — install with: brew install ffmpeg")` if `shutil.which("ffmpeg")` returns `None`
  - [ ] Returns silently when ffmpeg present
  - [ ] Unit test covers both branches (mock `shutil.which`)

---

### Task 4 (PR2): `convert.download_audio()` function
- **Complexity:** M
- **PR:** PR2
- **Depends on:** T1, T2, T3
- **Deliverable:** `convert.py` with public API `download_audio(url: str, output_dir: Path, fmt: str = "m4a", force: bool = False) -> Path`
- **Acceptance criteria:**
  - [ ] yt-dlp opts match `SPEC.md` §convert.py (`bestaudio/best`, `restrictfilenames`, `lazy_playlist`, `quiet`, `progress_hooks`)
  - [ ] `postprocessors` uses `FFmpegExtractAudio` with `preferredcodec=fmt`, `preferredquality="0"`
  - [ ] Idempotent — existing non-empty `audio.{fmt}` + `force=False` → log + return existing path
  - [ ] Supports formats: `m4a`, `mp3`, `wav`, `opus`, `flac`
  - [ ] Logs `"MP3 re-encoding from source — lossy"` when `fmt == "mp3"`
  - [ ] Progress hook logs `"Downloading: X% at Y"` — never parses stdout
  - [ ] **Never calls `sys.exit()` inside the function** (importable)
  - [ ] Returns `Path` to the final audio file
  - [ ] Test: mock yt-dlp; verify idempotent skip; verify `force=True` re-download

### Task 5 (PR2): `convert.py` standalone CLI
- **Complexity:** S
- **PR:** PR2
- **Depends on:** T4
- **Deliverable:** `if __name__ == "__main__":` block in `convert.py` with `argparse`
- **Acceptance criteria:**
  - [ ] CLI matches `SPEC.md` §convert.py contract: `url`, `--format`, `--output-dir`, `--force`
  - [ ] Calls `check_ffmpeg()` at startup before parsing URL
  - [ ] `sys.exit(1)` on `RuntimeError` with clear message — **only here, not inside functions**
  - [ ] `python convert.py <url>` downloads m4a to `./output/<slug>/audio.m4a`
  - [ ] `python convert.py <url> --format mp3` re-encodes to mp3

---

### Task 6 (PR3): Source resolver + local file handling
- **Complexity:** S
- **PR:** PR3
- **Depends on:** T2, T4
- **Deliverable:** `resolve_source(source: str, output_dir: Path) -> tuple[Path, dict]` in `transcribe.py`
- **Acceptance criteria:**
  - [ ] Detection order per `SPEC.md` §Local File Handling: `Path(source).exists()` before URL parse
  - [ ] Local file → create `output/<slug>/`, symlink as `audio.<ext>`; on symlink failure (Windows / permission), fall back to copy + warn
  - [ ] YouTube URL → call `convert.download_audio(source, output_dir, "m4a", force)` and return its path
  - [ ] Returns `(audio_path, source_meta)` where `source_meta` contains `url`, `title`, original absolute path for local files
  - [ ] Test: local file → symlink created; nonexistent URL-looking path → passed to yt-dlp

### Task 7 (PR3): Whisper transcriber — both modes
- **Complexity:** M
- **PR:** PR3
- **Depends on:** T1, T2
- **Deliverable:** `transcribe_audio(audio_path: Path, mode: str, model_name: str) -> tuple[list[Segment], Info]` in `transcribe.py`
- **Acceptance criteria:**
  - [ ] `WhisperModel(model_name, device="cpu", compute_type="int8")` — exact config from `CLAUDE.md`
  - [ ] `mode == "en-ar"` → `language=None` (auto-detect); **never** `language="en"`
  - [ ] `mode == "ar"` → `language="ar"` locked
  - [ ] `mode == "en"` → `language="en"` (per CLI contract; Arabic terms will transliterate)
  - [ ] `beam_size=5`, `vad_filter=True`, `vad_parameters={"min_silence_duration_ms": 500}`, `word_timestamps=True`
  - [ ] Returns materialized list of segments (not generator) so callers can iterate twice
  - [ ] Logs start/end with duration + detected language
  - [ ] Test (integration, skippable if model missing): 5-second Arabic WAV → output contains Arabic script

---

### Task 8 (PR4): `_raw.txt` writer
- **Complexity:** S
- **PR:** PR4
- **Depends on:** T7
- **Parallel with:** T9, T10
- **Deliverable:** `write_raw(segments, path: Path) -> None` in `transcribe.py`
- **Acceptance criteria:**
  - [ ] Format exactly per `SPEC.md`: `[0.0s → 4.1s] text`
  - [ ] One segment per line, `encoding="utf-8"`
  - [ ] Arabic text preserved byte-for-byte (round-trip test: read back, assert equality)

### Task 9 (PR4): `_clean.md` writer with paragraph grouping [P]
- **Complexity:** M
- **PR:** PR4
- **Depends on:** T7
- **Parallel with:** T8, T10
- **Deliverable:** `write_clean(segments, meta: dict, path: Path) -> None` in `transcribe.py`
- **Acceptance criteria:**
  - [ ] YAML frontmatter matches `SPEC.md` exactly: `source`, `title`, `date`, `mode`, `duration`, `model`, `subtitle_source`
  - [ ] Paragraphs grouped by silence gap > 1.5s between segments
  - [ ] **No hard-wrap** — one paragraph = one line
  - [ ] **No harakats added** — output Whisper text verbatim
  - [ ] `encoding="utf-8"`
  - [ ] Test: two segments separated by 2s gap → two paragraphs; 1s gap → one paragraph

### Task 10 (PR4): `meta.json` writer [P]
- **Complexity:** S
- **PR:** PR4
- **Depends on:** T7
- **Parallel with:** T8, T9
- **Deliverable:** `write_meta(meta: dict, path: Path) -> None` in `transcribe.py`
- **Acceptance criteria:**
  - [ ] All fields from `SPEC.md` §meta.json: `url`, `title`, `duration_seconds`, `language_mode`, `model`, `subtitle_source`, `created_at` (ISO 8601 UTC)
  - [ ] `json.dump(..., ensure_ascii=False, indent=2)` — Arabic title readable
  - [ ] `encoding="utf-8"`

---

### Task 11 (PR5): `transcribe.py` CLI + orchestration + idempotency
- **Complexity:** M
- **PR:** PR5
- **Depends on:** T6, T7, T8, T9, T10
- **Deliverable:** `main()` + `if __name__ == "__main__":` in `transcribe.py`
- **Acceptance criteria:**
  - [ ] CLI matches `CLAUDE.md` contract: `source`, `--mode {en-ar,ar,en}`, `--model`, `--subs-first`, `--force`, `--output-dir`
  - [ ] `--subs-first` logs `"Phase 2 feature — not yet implemented"` and continues with Whisper (do not fail)
  - [ ] Idempotency (per `SPEC.md` §Idempotency):
    - Skip download if `audio.m4a` exists + non-empty + no `--force`
    - Skip transcription if `transcript_raw.txt` + `meta.json` exist AND `meta.json.language_mode` matches `--mode`
    - Re-transcribe if mode differs (do not silently serve stale)
  - [ ] `check_ffmpeg()` at startup
  - [ ] `sys.exit(1)` on `RuntimeError` with clear message — only in `main()`
  - [ ] End-to-end test with local 5s MP3 produces all three output files

### Task 12 (PR5): README with install + usage
- **Complexity:** S
- **PR:** PR5
- **Depends on:** T5, T11
- **Deliverable:** `README.md`
- **Acceptance criteria:**
  - [ ] Install section: `brew install ffmpeg`, `pip install -r requirements.txt`
  - [ ] Usage examples mirror `SPEC.md` §CLI Interface (both `transcribe.py` and `convert.py`)
  - [ ] Notes: 9h file ≈ 2–4h on CPU, run overnight
  - [ ] Points to `CLAUDE.md` + `SPEC.md` for contributors

---

## Verification (run before every PR)

```bash
python -m py_compile $(git diff --name-only main -- '*.py')
pytest -q
ruff check .
ruff format --check .
```

Zero failures, zero warnings. Self-review `git diff main` before opening PR.

## Out of Scope (do not touch in Phase 1)

- `bot.py` — Phase 4
- `--subs-first` real implementation — Phase 2 (stub only in T11)
- Playlist batch transcription — Phase 3
- Diarization, harakats, translation, Obsidian/Anki writes — never in code

---

# TASKS — ilm-transcript Phase 2

> Builds on Phase 1. All Phase 1 PRs must be merged before starting Phase 2.
> Same workflow: `/spec implement transcribe [PR<N>]`. PR is the unit of delivery.

## PR Plan

| PR  | Tasks       | Description                                                         |
|-----|-------------|---------------------------------------------------------------------|
| PR6 | T13, T14    | `--subs-first` — subtitle fetch, SRT parser, Whisper fallback       |
| PR7 | T15, T16    | Long audio splitting >3h at silence + segment merge                 |
| PR8 | T17         | Progress bar with ETA during transcription                          |

---

## Tasks

### Task 13 (PR6): Subtitle fetcher
- **Complexity:** M
- **PR:** PR6
- **Depends on:** T6 (resolve_source)
- **Deliverable:** `fetch_subtitles(url: str, output_dir: Path) -> Path | None` in `transcribe.py`
- **Acceptance criteria:**
  - [ ] Uses `yt-dlp` with `writeautomaticsub=True`, `writesubtitles=True`, `subtitleslangs=["ar"]`, `skip_download=True`
  - [ ] Returns path to downloaded `.ar.vtt` or `.ar.srt` file if found, else `None`
  - [ ] Only called when `--subs-first` AND `--mode ar` (enforced in `main()`)
  - [ ] If `--mode` is not `ar`, logs `"--subs-first ignored for mode {mode} — subtitles only used in ar mode"` and returns `None`
  - [ ] Does not raise on missing subtitles — returns `None` silently
  - [ ] `quiet=True` — no yt-dlp stdout noise
  - [ ] Test: mock yt-dlp; verify returns `None` when no sub file created; verify path returned when file exists

### Task 14 (PR6): SRT/VTT parser + `--subs-first` wiring
- **Complexity:** M
- **PR:** PR6
- **Depends on:** T13
- **Deliverable:** `parse_subtitles(path: Path) -> list[Segment]` in `transcribe.py` + wiring in `main()`
- **Acceptance criteria:**
  - [ ] Parses both `.srt` and `.vtt` formats — strips cue headers, timestamps, HTML tags (`<c>`, `<b>`, etc.)
  - [ ] Returns list of objects with `.start`, `.end`, `.text` — same shape as faster-whisper segments so downstream writers work unchanged
  - [ ] Arabic text preserved byte-for-byte (round-trip test)
  - [ ] `main()`: if `fetch_subtitles()` returns a path → parse it, set `subtitle_source="subtitles"` in meta, skip `transcribe_audio()`
  - [ ] `main()`: if `fetch_subtitles()` returns `None` → log `"No subtitles found, falling back to Whisper"`, proceed normally
  - [ ] `meta.json` `subtitle_source` field is `"subtitles"` when subs used, `"whisper"` otherwise
  - [ ] Idempotency: if `transcript_raw.txt` + `meta.json` exist with matching mode AND `subtitle_source` matches requested path — skip (same `--force` override)
  - [ ] Test: SRT with Arabic → segments parsed correctly; VTT with HTML tags → tags stripped

---

### Task 15 (PR7): Audio splitter for files >3h
- **Complexity:** M
- **PR:** PR7
- **Depends on:** T4 (download_audio)
- **Deliverable:** `split_audio(audio_path: Path, output_dir: Path, chunk_minutes: int = 30) -> list[Path]` in `transcribe.py`
- **Acceptance criteria:**
  - [ ] Only activates when audio duration > 3h (10800s) — shorter files pass through unchanged as `[audio_path]`
  - [ ] Uses `ffmpeg` subprocess (via `shutil.which`) to split at silence: `ffmpeg -i input -af silencedetect=noise=-35dB:d=0.5 -f null -`
  - [ ] Parses silence timestamps from ffmpeg stderr, picks nearest silence boundary to each `chunk_minutes` mark
  - [ ] Falls back to hard time-split (no silence found near boundary) with a warning log
  - [ ] Chunk files written to `output_dir/chunks/chunk_NNN.wav` — zero-padded index
  - [ ] Returns list of chunk paths in order
  - [ ] Idempotent: existing chunk files + no `--force` → return existing list
  - [ ] Test: mock ffmpeg; verify split points; verify passthrough for <3h audio

### Task 16 (PR7): Multi-chunk transcription + segment merge
- **Complexity:** M
- **PR:** PR7
- **Depends on:** T15, T7
- **Deliverable:** updated `transcribe_audio()` to accept list of paths; `merge_segments()` helper
- **Acceptance criteria:**
  - [ ] `transcribe_audio()` signature extended: `audio_path: Path | list[Path]` — single path behaviour unchanged
  - [ ] Each chunk transcribed independently; segment timestamps offset by chunk start time so final timeline is continuous
  - [ ] `merge_segments(chunks: list[list[Segment]], offsets: list[float]) -> list[Segment]` — flat list, correct timestamps
  - [ ] Logs progress: `"Transcribing chunk 2/8"` etc.
  - [ ] `meta.json` `duration_seconds` reflects total audio, not single chunk
  - [ ] Test: two chunks with known offsets → merged timestamps correct; single path → no change in behaviour

---

### Task 17 (PR8): Progress bar with ETA
- **Complexity:** S
- **PR:** PR8
- **Depends on:** T7, T16
- **Deliverable:** progress reporting during transcription in `transcribe_audio()`
- **Acceptance criteria:**
  - [ ] Uses `logging` only — no `rich`, no `tqdm`, no new deps
  - [ ] Reports every completed segment: `"[{pct:.0f}%] {elapsed}s elapsed, ETA {eta}s — {seg.text[:40]}"`
  - [ ] `pct` derived from `seg.end / total_duration * 100`; `total_duration` from `info.duration` (available after model loads, before segment iteration — use two-pass: collect then report, OR use `audio_duration` from file metadata pre-transcription)
  - [ ] ETA = `elapsed / pct * (100 - pct)` — simple linear estimate, no external dep
  - [ ] For multi-chunk (T16): progress is chunk-level, not segment-level (`"Chunk 2/8 done"`)
  - [ ] No progress spam on short files (<60s) — log only start + end
  - [ ] Test: mock segments with known timestamps → log messages contain expected % and ETA values

---

## Verification (run before every PR)

```bash
uv run python -m py_compile $(git diff --name-only main -- '*.py')
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

Zero failures, zero warnings. Self-review `git diff main` before opening PR.

## Out of Scope (Phase 2)

- `bot.py` — Phase 4
- Playlist batch transcription — Phase 3
- Diarization, harakats, translation — never in code
- Config file (`~/.transcriber.toml`) — Phase 3
- `--subs-first` for `en-ar` mode — intentionally unsupported (Arabic-only subs drop English content)

---

# TASKS — ilm-transcript Phase 3

> Builds on Phase 2. Optional CLI polish — none of these are blockers for the Telegram bot.
> Same workflow: PR is the unit of delivery.

## PR Plan

| PR   | Tasks       | Description                                              |
|------|-------------|----------------------------------------------------------|
| PR7  | T18, T19    | Config file `~/.transcriber.toml` — defaults for mode, model, output-dir |
| PR8  | T20         | `--dry-run` — show title + duration before downloading   |
| PR9  | T21, T22    | Playlist batch processing in `convert.py`                |

---

## Tasks

### Task 18 (PR7): Config file loader
- **Complexity:** S
- **PR:** PR7
- **Depends on:** —
- **Deliverable:** `load_config() -> dict` in `utils.py`
- **Acceptance criteria:**
  - [ ] Reads `~/.transcriber.toml` if it exists; returns `{}` if absent (never raises)
  - [ ] Supported keys: `mode`, `model`, `output_dir`, `format` (for convert.py)
  - [ ] Uses stdlib `tomllib` (Python 3.11+) with fallback to `tomli` for 3.10
  - [ ] Values are plain strings/paths — no complex types
  - [ ] Test: file present with valid keys → returned; file absent → empty dict; unknown keys → ignored silently

### Task 19 (PR7): Wire config into `transcribe.py` and `convert.py` CLIs
- **Complexity:** S
- **PR:** PR7
- **Depends on:** T18
- **Deliverable:** config applied as defaults in `main()` (transcribe.py) and `__main__` block (convert.py)
- **Acceptance criteria:**
  - [ ] CLI args override config — config is the fallback, not a hard override
  - [ ] Priority order: CLI arg > config file > hardcoded default
  - [ ] `transcribe.py`: config keys `mode`, `model`, `output_dir` used as argparse defaults
  - [ ] `convert.py`: config keys `format`, `output_dir` used as argparse defaults
  - [ ] If config has `output_dir`, it is treated as a `Path`
  - [ ] Log `"Config loaded from ~/.transcriber.toml"` at DEBUG level (not INFO — not noise on every run)
  - [ ] Test: config sets `mode=ar`; CLI passes no `--mode` → `ar` used; CLI passes `--mode en-ar` → `en-ar` wins

---

### Task 20 (PR8): `--dry-run` mode
- **Complexity:** S
- **PR:** PR8
- **Depends on:** T4 (download_audio), T6 (resolve_source)
- **Deliverable:** `--dry-run` flag in both `transcribe.py` and `convert.py` CLIs
- **Acceptance criteria:**
  - [ ] For YouTube URLs: fetches video metadata via `yt-dlp` `extract_info(download=False)`, logs title + duration + format, then exits 0 — **no download, no transcription**
  - [ ] For local files: logs filename + size + duration (via `ffprobe`), then exits 0
  - [ ] Duration formatted with `_format_duration()` (already in `transcribe.py`) — reuse it
  - [ ] Output format: `[dry-run] Title: {title}` / `[dry-run] Duration: {duration}` / `[dry-run] Would save to: {output_dir}`
  - [ ] `convert.py` dry-run also shows target format
  - [ ] No files written, no ffmpeg invoked, no model loaded
  - [ ] Test: mock `yt_dlp.YoutubeDL.extract_info`; verify no download called; verify log lines present

---

### Task 21 (PR9): Playlist detection and batch iteration in `convert.py`
- **Complexity:** M
- **PR:** PR9
- **Depends on:** T4 (download_audio)
- **Deliverable:** `is_playlist(url: str) -> bool` helper + batch loop in `convert.py` `__main__`
- **Acceptance criteria:**
  - [ ] `is_playlist(url)` — returns `True` if yt-dlp `extract_info` returns `_type == "playlist"`; uses `extract_flat=True` to avoid downloading entries
  - [ ] Playlist loop: iterate `info["entries"]`, call `download_audio()` per entry with its own slug subfolder
  - [ ] `--sleep-interval N` CLI flag (default 0) — sleep N seconds between playlist entries to avoid rate limits; logged as `"Sleeping {N}s between downloads"`
  - [ ] Per-entry errors logged and skipped (`ignoreerrors=False` per entry, but loop continues)
  - [ ] Progress: `"[{i}/{total}] Downloading: {entry_title}"`
  - [ ] Single video URL → existing behaviour unchanged (no regression)
  - [ ] Test: mock yt-dlp with a 3-entry playlist; verify `download_audio` called 3 times with correct slugs

### Task 22 (PR9): Playlist support in `transcribe.py`
- **Complexity:** M
- **PR:** PR9
- **Depends on:** T21, T11 (main orchestration)
- **Deliverable:** playlist detection + per-entry orchestration loop in `transcribe.py` `main()`
- **Acceptance criteria:**
  - [ ] If source URL is a playlist → iterate entries, run full pipeline (download → split → transcribe → write) per entry
  - [ ] Each entry gets its own `output/{slug}/` — no mixing of entries
  - [ ] Failed entry: log error + continue (do not abort whole playlist)
  - [ ] Idempotency per entry: existing outputs + matching mode → skip that entry
  - [ ] `--dry-run` on playlist: list all entry titles + durations, no processing
  - [ ] Test: mock 2-entry playlist; verify output dirs created; verify second entry skipped when idempotent

---

## Verification (run before every PR)

```bash
uv run python -m py_compile $(git diff --name-only main -- '*.py')
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

Zero failures, zero warnings. Self-review `git diff main` before opening PR.

## Out of Scope (Phase 3)

- `bot.py` — Phase 4
- Diarization, harakats, translation — never in code
- Speaker identification — never in code
- GUI / web UI — never in this project
