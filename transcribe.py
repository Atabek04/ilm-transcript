"""Islamic lecture transcription pipeline."""

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
