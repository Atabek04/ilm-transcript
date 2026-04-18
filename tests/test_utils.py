"""Tests for utils.py."""

import hashlib
import logging
from unittest.mock import patch

import pytest

from utils import check_ffmpeg, configure_logging, sanitize_slug


def test_configure_logging():
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.WARNING)
    configure_logging()
    assert root.level == logging.INFO
    handler = next(h for h in root.handlers if isinstance(h, logging.StreamHandler))
    assert handler.formatter._fmt == "[%(asctime)s] %(message)s"


def test_sanitize_slug_normal():
    assert sanitize_slug("Hello World!") == "hello-world"


def test_sanitize_slug_arabic_only():
    title = "التَّوَكُّل"
    result = sanitize_slug(title)
    expected = "audio-" + hashlib.sha1(title.encode()).hexdigest()[:8]
    assert result == expected


def test_sanitize_slug_mixed():
    assert sanitize_slug("Sheikh Haitham - التَّوَكُّل") == "sheikh-haitham"


def test_sanitize_slug_empty():
    result = sanitize_slug("")
    assert result.startswith("audio-")
    assert len(result) == len("audio-") + 8


def test_sanitize_slug_collapses_dashes():
    assert sanitize_slug("hello   world") == "hello-world"


def test_check_ffmpeg_present():
    with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
        check_ffmpeg()  # must not raise


def test_check_ffmpeg_missing():
    with patch("shutil.which", return_value=None):
        with pytest.raises(RuntimeError, match="brew install ffmpeg"):
            check_ffmpeg()
