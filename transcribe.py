"""Islamic lecture transcription pipeline."""

import argparse
import datetime
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

from faster_whisper import WhisperModel

import convert
from utils import check_ffmpeg, configure_logging, sanitize_slug

DEFAULT_MODEL = "large-v3-turbo"
VALID_MODES = {"en-ar", "ar", "en"}
LONG_AUDIO_THRESHOLD_S = 10800  # 3 hours
DEFAULT_CHUNK_MINUTES = 30


def fetch_subtitles(url: str, output_dir: Path) -> "Path | None":
    """Fetch Arabic subtitles from YouTube. Returns path to sub file or None."""
    output_dir.mkdir(parents=True, exist_ok=True)
    ydl_opts = {
        "writeautomaticsub": True,
        "writesubtitles": True,
        "subtitleslangs": ["ar"],
        "skip_download": True,
        "outtmpl": str(output_dir / "subs"),
        "quiet": True,
        "no_warnings": True,
    }
    try:
        import yt_dlp

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except Exception as e:
        logging.warning(f"Subtitle fetch failed: {e}")
        return None

    matches = list(output_dir.glob("subs.ar.*"))
    return matches[0] if matches else None


def _ts_to_seconds(ts: str) -> float:
    """Convert SRT/VTT timestamp string to float seconds."""
    ts = ts.replace(",", ".")
    parts = ts.split(":")
    h, m, s = int(parts[0]), int(parts[1]), float(parts[2])
    return h * 3600 + m * 60 + s


def parse_subtitles(path: Path) -> list:
    """Parse SRT or VTT subtitle file. Returns segments with .start, .end, .text."""
    text = path.read_text(encoding="utf-8")
    segments = []

    # Normalise line endings, strip BOM
    text = text.replace("\r\n", "\n").lstrip("\ufeff")

    # Pattern matches both SRT (HH:MM:SS,mmm) and VTT (HH:MM:SS.mmm)
    block_re = re.compile(
        r"(\d{2}:\d{2}:\d{2}[.,]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[.,]\d{3})[^\n]*\n([\s\S]*?)(?=\n\n|\Z)",
        re.MULTILINE,
    )
    for m in block_re.finditer(text):
        start = _ts_to_seconds(m.group(1))
        end = _ts_to_seconds(m.group(2))
        raw = m.group(3).strip()
        # Strip HTML/VTT tags and cue identifiers
        clean = re.sub(r"<[^>]+>", "", raw).strip()
        if clean:
            segments.append(SimpleNamespace(start=start, end=end, text=clean))

    return segments


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


def _ffprobe_duration(path: Path) -> float:
    """Return audio duration in seconds via ffprobe."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def split_audio(
    audio_path: Path,
    output_dir: Path,
    chunk_minutes: int = DEFAULT_CHUNK_MINUTES,
    force: bool = False,
) -> list:
    """Split audio into chunks at silence boundaries if >3h. Returns list of Paths."""
    duration = _ffprobe_duration(audio_path)
    if duration <= LONG_AUDIO_THRESHOLD_S:
        return [audio_path]

    chunks_dir = output_dir / "chunks"
    if not force and chunks_dir.exists():
        existing = sorted(chunks_dir.glob("chunk_*.wav"))
        if existing:
            logging.info(f"Using {len(existing)} existing chunks in {chunks_dir}")
            return existing

    chunks_dir.mkdir(parents=True, exist_ok=True)

    # Detect silence end points
    result = subprocess.run(
        ["ffmpeg", "-i", str(audio_path), "-af", "silencedetect=noise=-35dB:d=0.5",
         "-f", "null", "-"],
        capture_output=True, text=True,
    )
    silence_ends = [
        float(m.group(1))
        for m in re.finditer(r"silence_end: (\d+\.?\d*)", result.stderr)
    ]

    # Build split boundaries
    chunk_secs = chunk_minutes * 60
    boundaries = [0.0]
    t = chunk_secs
    while t < duration:
        nearest = min(silence_ends, key=lambda s, t=t: abs(s - t), default=None)
        if nearest and abs(nearest - t) <= 60:
            boundaries.append(nearest)
        else:
            logging.warning(f"No silence near {t:.0f}s — hard split")
            boundaries.append(t)
        t += chunk_secs
    boundaries.append(duration)

    chunks: list[Path] = []
    for i, (start, end) in enumerate(zip(boundaries, boundaries[1:])):
        chunk_path = chunks_dir / f"chunk_{i:03d}.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(audio_path),
             "-ss", str(start), "-to", str(end),
             "-c", "copy", str(chunk_path)],
            capture_output=True, check=True,
        )
        chunks.append(chunk_path)

    logging.info(f"Split into {len(chunks)} chunks in {chunks_dir}")
    return chunks


def merge_segments(chunks_segments: list[list], offsets: list[float]) -> list:
    """Merge per-chunk segment lists, applying time offsets. Returns flat list."""
    merged = []
    for segs, offset in zip(chunks_segments, offsets):
        for seg in segs:
            merged.append(
                SimpleNamespace(
                    start=seg.start + offset,
                    end=seg.end + offset,
                    text=seg.text,
                )
            )
    return merged


def transcribe_audio(
    audio_path: "Path | list[Path]",
    mode: str,
    model_name: str = DEFAULT_MODEL,
) -> tuple[list, object]:
    """Transcribe audio (single path or list of chunk paths). Returns (segments, info)."""
    language_map = {"en-ar": None, "ar": "ar", "en": "en"}
    language = language_map[mode]

    logging.info(f"Loading model: {model_name}")
    model = WhisperModel(model_name, device="cpu", compute_type="int8")

    paths = audio_path if isinstance(audio_path, list) else [audio_path]
    total = len(paths)

    if total == 1:
        path = paths[0]
        total_duration = _ffprobe_duration(path)
        logging.info(f"Transcribing: {path} | mode={mode}")
        segments_gen, info = model.transcribe(
            str(path),
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
            word_timestamps=True,
            language=language,
        )
        segments = []
        t0 = time.monotonic()
        for seg in segments_gen:
            segments.append(seg)
            if total_duration > 60:
                pct = seg.end / total_duration * 100
                elapsed = time.monotonic() - t0
                eta = (elapsed / pct * (100 - pct)) if pct > 0 else 0
                logging.info(
                    f"[{pct:.0f}%] {elapsed:.0f}s elapsed, ETA {eta:.0f}s"
                    f" — {seg.text.strip()[:40]}"
                )
        logging.info(
            f"Transcription done: {info.duration:.1f}s,"
            f" detected language={info.language}, segments={len(segments)}"
        )
        return segments, info

    # Multi-chunk path
    all_segs: list[list] = []
    offsets: list[float] = []
    total_duration = 0.0
    first_info = None
    for i, path in enumerate(paths):
        logging.info(f"Transcribing chunk {i + 1}/{total}: {path}")
        chunk_dur = _ffprobe_duration(path)
        offsets.append(total_duration)
        total_duration += chunk_dur
        segments_gen, info = model.transcribe(
            str(path),
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
            word_timestamps=True,
            language=language,
        )
        all_segs.append(list(segments_gen))
        if first_info is None:
            first_info = info

    segments = merge_segments(all_segs, offsets)
    synthetic_info = SimpleNamespace(duration=total_duration, language=first_info.language)
    logging.info(
        f"Transcription done: {total_duration:.1f}s total,"
        f" detected language={first_info.language}, segments={len(segments)}"
    )
    return segments, synthetic_info


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


def main() -> None:
    """CLI entry point for the transcription pipeline."""
    configure_logging()

    try:
        check_ffmpeg()
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser(
        description="Transcribe Islamic lectures from YouTube or local audio files."
    )
    parser.add_argument("source", help="YouTube URL or path to local audio/video file")
    parser.add_argument(
        "--mode",
        choices=["en-ar", "ar", "en"],
        default="en-ar",
        help="Transcription mode (default: en-ar)",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Whisper model name (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--subs-first",
        action="store_true",
        help="Try YouTube subtitles before Whisper (YouTube only)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download and re-transcribe even if output exists",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("./output"),
        help="Output directory (default: ./output)",
    )
    args = parser.parse_args()

    try:
        audio_path, source_meta = resolve_source(
            args.source, args.output_dir, args.force
        )
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    output_dir = audio_path.parent
    raw_path = output_dir / "transcript_raw.txt"
    meta_path = output_dir / "meta.json"

    if not args.force and raw_path.exists() and meta_path.exists():
        try:
            existing = json.loads(meta_path.read_text(encoding="utf-8"))
            if existing.get("language_mode") == args.mode:
                logging.info(
                    f"Skipping transcription — outputs exist for mode {args.mode}"
                )
                return
        except (json.JSONDecodeError, KeyError):
            pass

    # --subs-first: only for YouTube URLs in ar mode
    segments = None
    subtitle_source = "whisper"

    if args.subs_first:
        if args.mode != "ar":
            logging.info(
                f"--subs-first ignored for mode {args.mode} — only used in ar mode"
            )
        elif Path(args.source).exists():
            logging.info("--subs-first ignored for local files")
        else:
            sub_path = fetch_subtitles(args.source, output_dir)
            if sub_path:
                logging.info(f"Subtitles found: {sub_path}")
                segments = parse_subtitles(sub_path)
                subtitle_source = "subtitles"
            else:
                logging.info("No subtitles found, falling back to Whisper")

    if segments is None:
        audio_paths = split_audio(audio_path, output_dir, force=args.force)
        try:
            segments, info = transcribe_audio(audio_paths, args.mode, args.model)
        except RuntimeError as e:
            print(str(e), file=sys.stderr)
            sys.exit(1)
        duration_seconds = info.duration
    else:
        duration_seconds = segments[-1].end if segments else 0.0

    meta = {
        **source_meta,
        "language_mode": args.mode,
        "model": args.model,
        "duration_seconds": duration_seconds,
        "subtitle_source": subtitle_source,
    }

    write_raw(segments, raw_path)
    write_clean(segments, meta, output_dir / "transcript_clean.md")
    write_meta(meta, meta_path)
    logging.info(f"Done. Output: {output_dir}")


if __name__ == "__main__":
    main()
