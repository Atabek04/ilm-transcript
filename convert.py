"""Standalone YouTube-to-audio converter. Also used as a library by transcribe.py."""

import argparse
import logging
import sys
from pathlib import Path

import yt_dlp

from utils import check_ffmpeg, configure_logging, sanitize_slug

SUPPORTED_FORMATS = {"m4a", "mp3", "wav", "opus", "flac"}


def download_audio(
    url: str,
    output_dir: Path,
    fmt: str = "m4a",
    force: bool = False,
) -> Path:
    """Download audio from URL to output_dir/audio.<fmt>. Returns path to file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    dest = output_dir / f"audio.{fmt}"

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
        "outtmpl": str(output_dir / "audio.%(ext)s"),
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


if __name__ == "__main__":
    configure_logging()
    try:
        check_ffmpeg()
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser(
        description="Download YouTube video/playlist audio in high quality."
    )
    parser.add_argument("url", help="YouTube video or playlist URL")
    parser.add_argument(
        "--format",
        dest="fmt",
        choices=sorted(SUPPORTED_FORMATS),
        default="m4a",
        help="Output audio format (default: m4a)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("./output"),
        help="Output directory (default: ./output)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if file exists",
    )
    args = parser.parse_args()

    try:
        ydl_info_opts = {"quiet": True, "no_warnings": True}
        with yt_dlp.YoutubeDL(ydl_info_opts) as ydl:
            info = ydl.extract_info(args.url, download=False)
        title = info.get("title", "") if info else ""
        slug = sanitize_slug(title) if title else sanitize_slug(args.url)
        output_dir = args.output_dir / slug
        path = download_audio(args.url, output_dir, args.fmt, args.force)
        logging.info(f"Saved to: {path}")
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
