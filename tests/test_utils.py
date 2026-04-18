"""Tests for utils.py."""

import hashlib
import logging
from unittest.mock import patch

import pytest

from utils import check_ffmpeg, configure_logging, load_config, sanitize_slug


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


# --- load_config ---


def test_load_config_absent(tmp_path):
    fake_path = tmp_path / "noexist.toml"
    with patch("utils.CONFIG_PATH", fake_path):
        assert load_config() == {}


def test_load_config_reads_known_keys(tmp_path):
    cfg = tmp_path / ".transcriber.toml"
    cfg.write_text(
        'mode = "ar"\nmodel = "large-v3"\noutput_dir = "./out"\n', encoding="utf-8"
    )
    with patch("utils.CONFIG_PATH", cfg):
        result = load_config()
    assert result["mode"] == "ar"
    assert result["model"] == "large-v3"
    assert result["output_dir"] == "./out"


def test_load_config_ignores_unknown_keys(tmp_path):
    cfg = tmp_path / ".transcriber.toml"
    cfg.write_text('mode = "en"\nunknown_key = "something"\n', encoding="utf-8")
    with patch("utils.CONFIG_PATH", cfg):
        result = load_config()
    assert "unknown_key" not in result
    assert result["mode"] == "en"


def test_load_config_returns_empty_on_malformed(tmp_path):
    cfg = tmp_path / ".transcriber.toml"
    cfg.write_text("this is not valid toml {{{\n", encoding="utf-8")
    with patch("utils.CONFIG_PATH", cfg):
        result = load_config()
    assert result == {}


def test_load_config_format_key(tmp_path):
    cfg = tmp_path / ".transcriber.toml"
    cfg.write_text('format = "mp3"\n', encoding="utf-8")
    with patch("utils.CONFIG_PATH", cfg):
        result = load_config()
    assert result["format"] == "mp3"


def test_check_ffmpeg_present():
    with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
        check_ffmpeg()  # must not raise


def test_check_ffmpeg_missing():
    with patch("shutil.which", return_value=None):
        with pytest.raises(RuntimeError, match="brew install ffmpeg"):
            check_ffmpeg()
