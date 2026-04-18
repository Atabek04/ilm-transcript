"""Tests for convert.py."""

import logging
from unittest.mock import MagicMock, patch

from convert import download_audio


def test_download_audio_idempotent(tmp_path):
    dest = tmp_path / "audio.m4a"
    dest.write_bytes(b"fake audio data")

    with patch("yt_dlp.YoutubeDL") as mock_ydl:
        result = download_audio("https://example.com", tmp_path, "m4a", force=False)

    mock_ydl.assert_not_called()
    assert result == dest


def test_download_audio_force_redownload(tmp_path):
    dest = tmp_path / "audio.m4a"
    dest.write_bytes(b"old data")

    mock_instance = MagicMock()
    with patch("yt_dlp.YoutubeDL", return_value=mock_instance):
        mock_instance.__enter__ = lambda s: s
        mock_instance.__exit__ = MagicMock(return_value=False)
        download_audio("https://example.com", tmp_path, "m4a", force=True)

    mock_instance.download.assert_called_once_with(["https://example.com"])


def test_download_audio_empty_file_triggers_download(tmp_path):
    dest = tmp_path / "audio.m4a"
    dest.write_bytes(b"")

    mock_instance = MagicMock()
    with patch("yt_dlp.YoutubeDL", return_value=mock_instance):
        mock_instance.__enter__ = lambda s: s
        mock_instance.__exit__ = MagicMock(return_value=False)
        download_audio("https://example.com", tmp_path, "m4a", force=False)

    mock_instance.download.assert_called_once()


def test_download_audio_mp3_logs_lossy_warning(tmp_path, caplog):
    mock_instance = MagicMock()
    with patch("yt_dlp.YoutubeDL", return_value=mock_instance):
        mock_instance.__enter__ = lambda s: s
        mock_instance.__exit__ = MagicMock(return_value=False)
        with caplog.at_level(logging.INFO):
            download_audio("https://example.com", tmp_path, "mp3", force=False)

    assert any("lossy" in r.message for r in caplog.records)


def test_progress_hook_downloading(tmp_path, caplog):
    captured_hook = None

    def capture_ydl(opts):
        nonlocal captured_hook
        captured_hook = opts["progress_hooks"][0]
        m = MagicMock()
        m.__enter__ = lambda s: s
        m.__exit__ = MagicMock(return_value=False)
        return m

    with patch("yt_dlp.YoutubeDL", side_effect=capture_ydl):
        with caplog.at_level(logging.INFO):
            download_audio("https://example.com", tmp_path, "m4a", force=True)

    assert captured_hook is not None
    with caplog.at_level(logging.INFO):
        captured_hook(
            {"status": "downloading", "_percent_str": " 42%", "_speed_str": "1.2MiB/s"}
        )

    assert any("42%" in r.message for r in caplog.records)


def test_progress_hook_finished(tmp_path, caplog):
    captured_hook = None

    def capture_ydl(opts):
        nonlocal captured_hook
        captured_hook = opts["progress_hooks"][0]
        m = MagicMock()
        m.__enter__ = lambda s: s
        m.__exit__ = MagicMock(return_value=False)
        return m

    with patch("yt_dlp.YoutubeDL", side_effect=capture_ydl):
        download_audio("https://example.com", tmp_path, "m4a", force=True)

    assert captured_hook is not None
    with caplog.at_level(logging.INFO):
        captured_hook({"status": "finished", "filename": "audio.m4a"})

    assert any("Download done" in r.message for r in caplog.records)
