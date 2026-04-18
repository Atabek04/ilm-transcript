"""Shared utilities: logging config, slug sanitizer, ffmpeg detection, config loader."""

import hashlib
import logging
import re
import shutil
import unicodedata
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]

CONFIG_PATH = Path.home() / ".transcriber.toml"
_ALLOWED_KEYS = {"mode", "model", "output_dir", "format"}


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


def load_config() -> dict:
    """Load ~/.transcriber.toml and return allowed keys as a dict. Never raises."""
    if not CONFIG_PATH.exists():
        return {}
    try:
        with open(CONFIG_PATH, "rb") as f:
            raw = tomllib.load(f)
        return {k: v for k, v in raw.items() if k in _ALLOWED_KEYS}
    except Exception as e:
        logging.debug(f"Could not read {CONFIG_PATH}: {e}")
        return {}


def check_ffmpeg() -> None:
    """Raise RuntimeError if ffmpeg is not found on PATH."""
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not found — install with: brew install ffmpeg")
