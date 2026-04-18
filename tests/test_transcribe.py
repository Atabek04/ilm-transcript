"""Tests for transcribe.py — source resolver and transcriber."""

import json
import logging
import re
from types import SimpleNamespace
from unittest.mock import patch

from transcribe import resolve_source, write_clean, write_meta, write_raw


def _seg(start: float, end: float, text: str) -> SimpleNamespace:
    return SimpleNamespace(start=start, end=end, text=text)


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


# --- write_raw ---


def test_write_raw_format(tmp_path):
    segs = [_seg(0.0, 4.1, " In the name of Allah"), _seg(4.2, 6.7, " Al-hamdu lillah")]
    out = tmp_path / "transcript_raw.txt"
    write_raw(segs, out)
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "[0.0s → 4.1s] In the name of Allah"
    assert lines[1] == "[4.2s → 6.7s] Al-hamdu lillah"


def test_write_raw_arabic_preserved(tmp_path):
    arabic = "التَّوَكُّل"
    segs = [_seg(0.0, 3.0, arabic)]
    out = tmp_path / "transcript_raw.txt"
    write_raw(segs, out)
    content = out.read_text(encoding="utf-8")
    assert arabic in content


# --- write_clean ---


def test_write_clean_frontmatter(tmp_path):
    segs = [_seg(0.0, 2.0, "Hello")]
    meta = {
        "url": "https://youtube.com/watch?v=abc",
        "title": "Test Lecture",
        "language_mode": "en-ar",
        "duration_seconds": 3720,
        "model": "large-v3-turbo",
        "subtitle_source": "whisper",
    }
    out = tmp_path / "transcript_clean.md"
    write_clean(segs, meta, out)
    content = out.read_text(encoding="utf-8")
    for field in (
        "source",
        "title",
        "date",
        "mode",
        "duration",
        "model",
        "subtitle_source",
    ):
        assert f"{field}:" in content


def test_write_clean_paragraph_grouping(tmp_path):
    # gap of 2s between seg2 and seg3 → two paragraphs
    segs = [
        _seg(0.0, 1.0, "First sentence."),
        _seg(1.2, 2.0, "Second sentence."),  # gap 0.2s — same paragraph
        _seg(4.1, 5.5, "New paragraph."),  # gap 2.1s — new paragraph
    ]
    meta = {
        "url": None,
        "source_path": "file.mp3",
        "title": "T",
        "language_mode": "en",
        "duration_seconds": 6,
        "model": "large-v3-turbo",
    }
    out = tmp_path / "transcript_clean.md"
    write_clean(segs, meta, out)
    body = out.read_text(encoding="utf-8").split("---\n", 2)[-1].strip()
    paragraphs = [p for p in body.split("\n\n") if p.strip()]
    assert len(paragraphs) == 2
    assert "First sentence." in paragraphs[0]
    assert "New paragraph." in paragraphs[1]


# --- write_meta ---


def test_write_meta_fields(tmp_path):
    meta = {
        "url": "https://youtube.com/watch?v=abc",
        "title": "التَّوَكُّل",
        "duration_seconds": 3720,
        "language_mode": "ar",
        "model": "large-v3-turbo",
        "subtitle_source": "whisper",
    }
    out = tmp_path / "meta.json"
    write_meta(meta, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    for key in (
        "url",
        "title",
        "duration_seconds",
        "language_mode",
        "model",
        "subtitle_source",
        "created_at",
    ):
        assert key in data
    assert data["title"] == "التَّوَكُّل"  # Arabic readable, not escaped


def test_write_meta_created_at_format(tmp_path):
    meta = {
        "url": None,
        "title": "T",
        "duration_seconds": 0,
        "language_mode": "en",
        "model": "m",
        "subtitle_source": "whisper",
    }
    out = tmp_path / "meta.json"
    write_meta(meta, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", data["created_at"])
