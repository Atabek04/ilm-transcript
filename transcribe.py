"""Islamic lecture transcription pipeline."""

import datetime
import json
import logging
import os
import shutil
from pathlib import Path

from faster_whisper import WhisperModel

import convert
from utils import sanitize_slug

DEFAULT_MODEL = "large-v3-turbo"
VALID_MODES = {"en-ar", "ar", "en"}


def resolve_source(
    source: str,
    output_dir: Path,
    force: bool = False,
) -> tuple[Path, dict]:
    """Resolve source to a local audio path. Returns (audio_path, source_meta)."""
    if Path(source).exists():
        src = Path(source).resolve()
        slug = sanitize_slug(src.stem)
        dest_dir = output_dir / slug
        dest_dir.mkdir(parents=True, exist_ok=True)
        audio_path = dest_dir / f"audio{src.suffix}"

        if not audio_path.exists():
            try:
                os.symlink(src, audio_path)
            except OSError:
                logging.warning(f"Symlink failed, copying {src} → {audio_path}")
                shutil.copy2(src, audio_path)

        meta = {
            "title": src.stem,
            "url": None,
            "source_path": str(src),
        }
        return audio_path, meta

    audio_path = convert.download_audio(source, output_dir, "m4a", force)
    meta = {
        "title": audio_path.parent.name,
        "url": source,
        "source_path": None,
    }
    return audio_path, meta


def transcribe_audio(
    audio_path: Path,
    mode: str,
    model_name: str = DEFAULT_MODEL,
) -> tuple[list, object]:
    """Transcribe audio file using faster-whisper. Returns (segments, info)."""
    language_map = {"en-ar": None, "ar": "ar", "en": "en"}
    language = language_map[mode]

    logging.info(f"Loading model: {model_name}")
    model = WhisperModel(model_name, device="cpu", compute_type="int8")

    logging.info(f"Transcribing: {audio_path} | mode={mode}")
    segments_gen, info = model.transcribe(
        str(audio_path),
        beam_size=5,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        word_timestamps=True,
        language=language,
    )
    segments = list(segments_gen)

    duration = info.duration
    detected = info.language
    logging.info(
        f"Transcription done: {duration:.1f}s, detected language={detected}, segments={len(segments)}"
    )
    return segments, info


def write_raw(segments: list, path: Path) -> None:
    """Write timestamped segments to transcript_raw.txt."""
    with open(path, "w", encoding="utf-8") as f:
        for seg in segments:
            f.write(f"[{seg.start:.1f}s \u2192 {seg.end:.1f}s] {seg.text.strip()}\n")


def _format_duration(seconds: float) -> str:
    """Format seconds as 'Xh Ym' or 'Xm Ys'."""
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m"
    return f"{m}m {s}s"


def write_clean(segments: list, meta: dict, path: Path) -> None:
    """Write paragraph-grouped transcript with YAML frontmatter to transcript_clean.md."""
    frontmatter = (
        "---\n"
        f"source: {meta.get('url') or meta.get('source_path', '')}\n"
        f"title: {meta.get('title', '')}\n"
        f"date: {datetime.date.today().isoformat()}\n"
        f"mode: {meta.get('language_mode', '')}\n"
        f"duration: {_format_duration(meta.get('duration_seconds', 0))}\n"
        f"model: {meta.get('model', '')}\n"
        f"subtitle_source: {meta.get('subtitle_source', 'whisper')}\n"
        "---\n"
    )

    paragraphs: list[list[str]] = []
    current: list[str] = []
    prev_end: float = 0.0

    for seg in segments:
        if current and (seg.start - prev_end) > 1.5:
            paragraphs.append(current)
            current = []
        current.append(seg.text.strip())
        prev_end = seg.end

    if current:
        paragraphs.append(current)

    body = "\n\n".join(" ".join(p) for p in paragraphs)

    with open(path, "w", encoding="utf-8") as f:
        f.write(frontmatter + "\n" + body + "\n")


def write_meta(meta: dict, path: Path) -> None:
    """Write run metadata to meta.json."""
    payload = {
        "url": meta.get("url"),
        "title": meta.get("title"),
        "duration_seconds": meta.get("duration_seconds"),
        "language_mode": meta.get("language_mode"),
        "model": meta.get("model"),
        "subtitle_source": meta.get("subtitle_source", "whisper"),
        "created_at": datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
