"""Standalone YouTube-to-audio converter. Also used as a library by transcribe.py."""

import argparse
import logging
import sys
from pathlib import Path

import yt_dlp

from utils import check_ffmpeg, configure_logging, load_config, sanitize_slug

SUPPORTED_FORMATS = {"m4a", "mp3", "wav", "opus", "flac"}


def download_audio(
    url: str,
    output_dir: Path,
    fmt: str = "m4a",
    force: bool = False,
    stem: str = "audio",
) -> Path:
    """Download audio from URL to output_dir/{stem}.<fmt>. Returns path to file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    dest = output_dir / f"{stem}.{fmt}"

    if dest.exists() and dest.stat().st_size > 0 and not force:
        logging.info(f"Already exists, skipping download: {dest}")
        return dest

    if fmt == "mp3":
        logging.info("MP3 re-encoding from source — lossy")

    def progress_hook(d: dict) -> None:
        if d["status"] == "downloading":
            pct = d.get("_percent_str", "?%").strip()
            speed = d.get("_speed_str", "?").strip()
            logging.info(f"Downloading: {pct} at {speed}")
        elif d["status"] == "finished":
            logging.info(f"Download done: {d['filename']}")

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": str(output_dir / f"{stem}.%(ext)s"),
        "restrictfilenames": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": fmt,
                "preferredquality": "0",
            }
        ],
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [progress_hook],
        "ignoreerrors": False,
        "lazy_playlist": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    return dest


def _best_slug(title: str, video_id: str = "") -> str:
    """Slug from title; falls back to video_id when title is non-ASCII (e.g. Arabic)."""
    has_ascii = bool(title.encode("ascii", "ignore").decode("ascii").strip())
    if has_ascii:
        return sanitize_slug(title)
    return video_id or sanitize_slug(title)


def is_playlist(url: str) -> bool:
    """Return True if url resolves to a yt-dlp playlist."""
    opts = {
        "quiet": True,
        "extract_flat": True,
        "skip_download": True,
        "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return bool(info) and info.get("_type") == "playlist"


def main() -> None:
    """CLI entry point for the audio downloader."""
    import time as _time

    configure_logging()
    try:
        check_ffmpeg()
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    cfg = load_config()
    logging.debug("Config loaded from ~/.transcriber.toml")

    parser = argparse.ArgumentParser(
        description="Download YouTube video/playlist audio in high quality."
    )
    parser.add_argument("url", help="YouTube video or playlist URL")
    parser.add_argument(
        "--format",
        dest="fmt",
        choices=sorted(SUPPORTED_FORMATS),
        help="Output audio format (default: m4a)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Output directory (default: ./output)",
    )
    parser.add_argument(
        "--title",
        help="Override filename (slug derived from this value)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if file exists",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show title/duration/format/path without downloading",
    )
    parser.add_argument(
        "--sleep-interval",
        type=int,
        default=0,
        metavar="N",
        help="Seconds to sleep between playlist entries (default: 0)",
    )
    parser.set_defaults(
        fmt=cfg.get("format", "m4a"),
        output_dir=Path(cfg.get("output_dir", "./output")),
    )
    args = parser.parse_args()

    try:
        ydl_info_opts = {"quiet": True, "no_warnings": True}
        with yt_dlp.YoutubeDL(ydl_info_opts) as ydl:
            info = ydl.extract_info(args.url, download=False)

        if args.dry_run:
            # Dry-run for single video or playlist
            if info and info.get("_type") == "playlist":
                entries = info.get("entries") or []
                for entry in entries:
                    if not entry:
                        continue
                    raw_dur = entry.get("duration") or 0
                    from transcribe import _format_duration

                    title = entry.get("title", "(unknown)")
                    logging.info(f"[dry-run] Title: {title}")
                    logging.info(f"[dry-run] Duration: {_format_duration(raw_dur)}")
                    logging.info(
                        f"[dry-run] Would save to: {args.output_dir / sanitize_slug(title)}"
                    )
                    logging.info(f"[dry-run] Format: {args.fmt}")
            else:
                from transcribe import _format_duration

                title = (info.get("title", "") if info else "") or args.url
                raw_dur = (info.get("duration") or 0) if info else 0
                slug = sanitize_slug(title) if title else sanitize_slug(args.url)
                logging.info(f"[dry-run] Title: {title}")
                logging.info(f"[dry-run] Duration: {_format_duration(raw_dur)}")
                logging.info(f"[dry-run] Format: {args.fmt}")
                logging.info(f"[dry-run] Would save to: {args.output_dir / slug}")
            sys.exit(0)

        # Playlist batch or single video
        if info and info.get("_type") == "playlist":
            entries = [e for e in (info.get("entries") or []) if e]
            total = len(entries)
            for i, entry in enumerate(entries, 1):
                entry_url = (
                    entry.get("url") or entry.get("webpage_url") or entry.get("id")
                )
                entry_title = entry.get("title", f"entry-{i}")
                logging.info(f"[{i}/{total}] Downloading: {entry_title}")
                try:
                    slug = _best_slug(entry_title, entry.get("id", ""))
                    out_dir = args.output_dir / slug
                    path = download_audio(entry_url, out_dir, args.fmt, args.force, stem=slug)
                    logging.info(f"Saved to: {path}")
                except Exception as exc:
                    logging.error(f"[{i}/{total}] Failed {entry_title}: {exc}")
                if args.sleep_interval and i < total:
                    logging.info(f"Sleeping {args.sleep_interval}s between downloads")
                    _time.sleep(args.sleep_interval)
        else:
            if args.title:
                slug = sanitize_slug(args.title) or args.title
            else:
                title = (info.get("title") or "") if info else ""
                video_id = (info.get("id") or "") if info else ""
                slug = _best_slug(title, video_id)
            output_dir = args.output_dir / slug
            path = download_audio(args.url, output_dir, args.fmt, args.force, stem=slug)
            logging.info(f"Saved to: {path}")
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
