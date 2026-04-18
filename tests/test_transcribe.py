"""Tests for transcribe.py — source resolver and transcriber."""

import json
import logging
import re
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from transcribe import (
    fetch_subtitles,
    main,
    merge_segments,
    parse_subtitles,
    resolve_source,
    split_audio,
    write_clean,
    write_meta,
    write_raw,
)


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


# --- main() orchestration ---


def _make_fake_info(duration: float = 5.0, language: str = "en") -> MagicMock:
    info = MagicMock()
    info.duration = duration
    info.language = language
    return info


def _run_main(args: list[str]) -> None:
    with patch("sys.argv", ["transcribe.py"] + args):
        main()


def test_main_skips_transcription_when_outputs_exist(tmp_path, caplog):
    src = tmp_path / "lecture.mp3"
    src.write_bytes(b"audio")
    out_dir = tmp_path / "output" / "lecture"
    out_dir.mkdir(parents=True)
    (out_dir / "audio.mp3").symlink_to(src)
    (out_dir / "transcript_raw.txt").write_text("existing", encoding="utf-8")
    (out_dir / "meta.json").write_text(
        json.dumps({"language_mode": "en-ar"}), encoding="utf-8"
    )

    with (
        patch("transcribe.transcribe_audio") as mock_ta,
        patch("transcribe.split_audio", return_value=[out_dir / "audio.mp3"]),
        patch("transcribe.check_ffmpeg"),
        caplog.at_level(logging.INFO),
    ):
        _run_main(
            [str(src), "--mode", "en-ar", "--output-dir", str(tmp_path / "output")]
        )

    mock_ta.assert_not_called()
    assert any("Skipping" in r.message for r in caplog.records)


def test_main_retranscribes_when_mode_differs(tmp_path):
    src = tmp_path / "lecture.mp3"
    src.write_bytes(b"audio")
    out_dir = tmp_path / "output" / "lecture"
    out_dir.mkdir(parents=True)
    (out_dir / "audio.mp3").symlink_to(src)
    (out_dir / "transcript_raw.txt").write_text("existing", encoding="utf-8")
    (out_dir / "meta.json").write_text(
        json.dumps({"language_mode": "ar"}), encoding="utf-8"
    )

    fake_info = _make_fake_info()
    with (
        patch("transcribe.transcribe_audio", return_value=([], fake_info)) as mock_ta,
        patch("transcribe.split_audio", return_value=[out_dir / "audio.mp3"]),
        patch("transcribe.check_ffmpeg"),
    ):
        _run_main(
            [str(src), "--mode", "en-ar", "--output-dir", str(tmp_path / "output")]
        )

    mock_ta.assert_called_once()


def test_main_subs_first_logs_and_continues(tmp_path, caplog):
    src = tmp_path / "lecture.mp3"
    src.write_bytes(b"audio")

    fake_info = _make_fake_info()
    with (
        patch("transcribe.transcribe_audio", return_value=([], fake_info)),
        patch("transcribe.split_audio", return_value=[src]),
        patch("transcribe.check_ffmpeg"),
        caplog.at_level(logging.INFO),
    ):
        _run_main([str(src), "--subs-first", "--output-dir", str(tmp_path / "output")])

    # en-ar mode → subs-first ignored with a log message
    assert any("ignored" in r.message for r in caplog.records)


def test_main_force_bypasses_idempotency(tmp_path):
    src = tmp_path / "lecture.mp3"
    src.write_bytes(b"audio")
    out_dir = tmp_path / "output" / "lecture"
    out_dir.mkdir(parents=True)
    (out_dir / "audio.mp3").symlink_to(src)
    (out_dir / "transcript_raw.txt").write_text("old", encoding="utf-8")
    (out_dir / "meta.json").write_text(
        json.dumps({"language_mode": "en-ar"}), encoding="utf-8"
    )

    fake_info = _make_fake_info()
    with (
        patch("transcribe.transcribe_audio", return_value=([], fake_info)) as mock_ta,
        patch("transcribe.split_audio", return_value=[out_dir / "audio.mp3"]),
        patch("transcribe.check_ffmpeg"),
    ):
        _run_main(
            [
                str(src),
                "--mode",
                "en-ar",
                "--force",
                "--output-dir",
                str(tmp_path / "output"),
            ]
        )

    mock_ta.assert_called_once()


# --- fetch_subtitles ---


def test_fetch_subtitles_returns_none_when_no_file(tmp_path):
    with patch("yt_dlp.YoutubeDL") as mock_ydl:
        mock_ydl.return_value.__enter__ = lambda s: s
        mock_ydl.return_value.__exit__ = MagicMock(return_value=False)
        result = fetch_subtitles("https://youtube.com/watch?v=abc", tmp_path)
    assert result is None


def test_fetch_subtitles_returns_path_when_file_exists(tmp_path):
    sub_file = tmp_path / "subs.ar.vtt"
    sub_file.write_text("WEBVTT\n", encoding="utf-8")

    with patch("yt_dlp.YoutubeDL") as mock_ydl:
        mock_ydl.return_value.__enter__ = lambda s: s
        mock_ydl.return_value.__exit__ = MagicMock(return_value=False)
        result = fetch_subtitles("https://youtube.com/watch?v=abc", tmp_path)

    assert result == sub_file


def test_fetch_subtitles_returns_none_on_exception(tmp_path):
    with patch("yt_dlp.YoutubeDL", side_effect=Exception("network error")):
        result = fetch_subtitles("https://youtube.com/watch?v=abc", tmp_path)
    assert result is None


# --- parse_subtitles ---


def test_parse_subtitles_srt(tmp_path):
    srt = (
        "1\n00:00:01,000 --> 00:00:04,100\nIn the name of Allah\n\n"
        "2\n00:00:04,200 --> 00:00:06,700\nالتَّوَكُّل\n\n"
    )
    path = tmp_path / "subs.ar.srt"
    path.write_text(srt, encoding="utf-8")
    segs = parse_subtitles(path)
    assert len(segs) == 2
    assert segs[0].start == pytest.approx(1.0)
    assert segs[0].end == pytest.approx(4.1)
    assert segs[0].text == "In the name of Allah"
    assert segs[1].text == "التَّوَكُّل"


def test_parse_subtitles_vtt_strips_html(tmp_path):
    vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:04.100\n<c>التَّوَكُّل</c>\n\n"
    path = tmp_path / "subs.ar.vtt"
    path.write_text(vtt, encoding="utf-8")
    segs = parse_subtitles(path)
    assert len(segs) == 1
    assert segs[0].text == "التَّوَكُّل"
    assert "<c>" not in segs[0].text


def test_parse_subtitles_arabic_preserved(tmp_path):
    arabic = "وَالَّذِينَ آمَنُوا"
    srt = f"1\n00:00:00,000 --> 00:00:02,000\n{arabic}\n\n"
    path = tmp_path / "subs.ar.srt"
    path.write_text(srt, encoding="utf-8")
    segs = parse_subtitles(path)
    assert segs[0].text == arabic


# --- split_audio ---


def test_split_audio_passthrough_short_file(tmp_path):
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"fake")
    with patch("transcribe._ffprobe_duration", return_value=3600.0):
        result = split_audio(audio, tmp_path)
    assert result == [audio]


def test_split_audio_creates_chunks_for_long_file(tmp_path):
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"fake")
    fake_silence = (
        "silence_end: 1820.5 | silence_duration: 0.8\n"
        "silence_end: 3620.1 | silence_duration: 0.6\n"
    )

    with (
        patch("transcribe._ffprobe_duration", return_value=10800.1),
        patch("subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(stderr=fake_silence, stdout="", returncode=0)
        result = split_audio(audio, tmp_path, chunk_minutes=30, force=True)

    assert len(result) > 1
    assert all(str(p).endswith(".wav") for p in result)


def test_split_audio_idempotent(tmp_path):
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"fake")
    chunks_dir = tmp_path / "chunks"
    chunks_dir.mkdir()
    existing = chunks_dir / "chunk_000.wav"
    existing.write_bytes(b"chunk")

    with patch("transcribe._ffprobe_duration", return_value=20000.0):
        result = split_audio(audio, tmp_path, force=False)

    assert result == [existing]


# --- merge_segments ---


def test_merge_segments_applies_offsets():
    chunk0 = [_seg(0.0, 2.0, "Hello"), _seg(2.5, 4.0, "world")]
    chunk1 = [_seg(0.0, 1.5, "Arabic")]
    merged = merge_segments([chunk0, chunk1], [0.0, 100.0])
    assert merged[0].start == pytest.approx(0.0)
    assert merged[1].end == pytest.approx(4.0)
    assert merged[2].start == pytest.approx(100.0)
    assert merged[2].end == pytest.approx(101.5)
    assert merged[2].text == "Arabic"


# --- subs-first wiring in main() ---


def test_main_subs_first_ar_uses_subtitles_skips_whisper(tmp_path):
    out_dir = tmp_path / "output" / "some-slug"
    out_dir.mkdir(parents=True)
    sub_path = out_dir / "subs.ar.vtt"
    fake_audio = out_dir / "audio.m4a"
    fake_audio.write_bytes(b"audio")
    fake_segs = [_seg(0.0, 2.0, "مرحبا")]

    with (
        patch("transcribe.check_ffmpeg"),
        patch(
            "transcribe.resolve_source",
            return_value=(
                fake_audio,
                {"title": "T", "url": "https://yt", "source_path": None},
            ),
        ),
        patch("transcribe.fetch_subtitles", return_value=sub_path),
        patch("transcribe.parse_subtitles", return_value=fake_segs),
        patch("transcribe.split_audio"),
        patch("transcribe.transcribe_audio") as mock_ta,
        patch("transcribe.write_raw"),
        patch("transcribe.write_clean"),
        patch("transcribe.write_meta"),
    ):
        with patch(
            "sys.argv",
            [
                "transcribe.py",
                "https://yt",
                "--mode",
                "ar",
                "--subs-first",
                "--output-dir",
                str(tmp_path / "output"),
            ],
        ):
            main()

    mock_ta.assert_not_called()


def test_main_subs_first_non_ar_logs_ignored(tmp_path, caplog):
    src = tmp_path / "lecture.mp3"
    src.write_bytes(b"audio")
    fake_info = _make_fake_info()

    with (
        patch("transcribe.check_ffmpeg"),
        patch("transcribe.split_audio", return_value=[src]),
        patch("transcribe.transcribe_audio", return_value=([], fake_info)),
        patch("transcribe.write_raw"),
        patch("transcribe.write_clean"),
        patch("transcribe.write_meta"),
        caplog.at_level(logging.INFO),
    ):
        with patch(
            "sys.argv",
            [
                "transcribe.py",
                str(src),
                "--mode",
                "en-ar",
                "--subs-first",
                "--output-dir",
                str(tmp_path / "output"),
            ],
        ):
            main()

    assert any("ignored" in r.message for r in caplog.records)
