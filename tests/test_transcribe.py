"""Tests for transcribe.py — source resolver and transcriber."""

import logging
from unittest.mock import patch

from transcribe import resolve_source


def test_resolve_local_file_creates_symlink(tmp_path):
    src = tmp_path / "lecture.mp3"
    src.write_bytes(b"audio")
    output_dir = tmp_path / "output"

    audio_path, meta = resolve_source(str(src), output_dir)

    assert audio_path.exists()
    assert audio_path.is_symlink()
    assert audio_path.name == "audio.mp3"
    assert meta["url"] is None
    assert meta["source_path"] == str(src.resolve())
    assert meta["title"] == "lecture"


def test_resolve_local_file_symlink_fallback_to_copy(tmp_path, caplog):
    src = tmp_path / "lecture.mp3"
    src.write_bytes(b"audio data")
    output_dir = tmp_path / "output"

    with patch("os.symlink", side_effect=OSError("no symlinks")):
        with caplog.at_level(logging.WARNING):
            audio_path, meta = resolve_source(str(src), output_dir)

    assert audio_path.exists()
    assert not audio_path.is_symlink()
    assert any("copying" in r.message.lower() for r in caplog.records)


def test_resolve_local_file_idempotent(tmp_path):
    src = tmp_path / "lecture.mp3"
    src.write_bytes(b"audio")
    output_dir = tmp_path / "output"

    audio_path1, _ = resolve_source(str(src), output_dir)
    audio_path2, _ = resolve_source(str(src), output_dir)

    assert audio_path1 == audio_path2


def test_resolve_youtube_url_calls_download_audio(tmp_path):
    fake_audio = tmp_path / "output" / "some-slug" / "audio.m4a"
    fake_audio.parent.mkdir(parents=True)
    fake_audio.write_bytes(b"audio")

    with patch("convert.download_audio", return_value=fake_audio) as mock_dl:
        audio_path, meta = resolve_source("https://youtube.com/watch?v=abc", tmp_path)

    mock_dl.assert_called_once_with(
        "https://youtube.com/watch?v=abc", tmp_path, "m4a", False
    )
    assert audio_path == fake_audio
    assert meta["url"] == "https://youtube.com/watch?v=abc"
    assert meta["source_path"] is None


def test_resolve_youtube_url_force_passed_through(tmp_path):
    fake_audio = tmp_path / "output" / "slug" / "audio.m4a"
    fake_audio.parent.mkdir(parents=True)
    fake_audio.write_bytes(b"audio")

    with patch("convert.download_audio", return_value=fake_audio) as mock_dl:
        resolve_source("https://youtube.com/watch?v=abc", tmp_path, force=True)

    mock_dl.assert_called_once_with(
        "https://youtube.com/watch?v=abc", tmp_path, "m4a", True
    )
