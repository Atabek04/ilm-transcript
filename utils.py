"""Shared utilities: logging config, slug sanitizer, ffmpeg detection."""

import hashlib
import logging
import re
import shutil
import unicodedata


def configure_logging() -> None:
    """Configure root logger with [HH:MM:SS] format."""
    logging.basicConfig(
        format="[%(asctime)s] %(message)s",
        datefmt="%H:%M:%S",
        level=logging.INFO,
    )


def sanitize_slug(title: str) -> str:
    """Return ASCII-only slug from title; falls back to audio-<sha1[:8]> if empty."""
    normalized = unicodedata.normalize("NFKD", title)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9-]", "-", ascii_only.lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    if not slug:
        slug = "audio-" + hashlib.sha1(title.encode()).hexdigest()[:8]
    return slug


def check_ffmpeg() -> None:
    """Raise RuntimeError if ffmpeg is not found on PATH."""
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not found — install with: brew install ffmpeg")
