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
