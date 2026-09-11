from __future__ import annotations

from pathlib import Path

from PIL import Image

from picsyncra.image_pipeline import (
    ImagePipelineOptions,
    choose_jpeg_quality,
    process_image,
)


def _write_jpeg_with_exif(path: Path) -> Path:
    image = Image.new("RGB", (120, 80), "white")
    exif = Image.Exif()
    exif[0x010E] = "private description"
    image.save(path, format="JPEG", exif=exif)
    return path


def test_pipeline_removes_metadata_and_opens_source_once(tmp_path, monkeypatch) -> None:
    """Catches a final image pipeline that leaks EXIF or reopens its source."""
    source = _write_jpeg_with_exif(tmp_path / "source.jpg")
    target = tmp_path / "target.jpg"
    opens = 0
    original_open = Image.open

    def counted_open(path, *args, **kwargs):
        nonlocal opens
        if str(path) == str(source):
            opens += 1
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Image, "open", counted_open)
    process_image(str(source), str(target), ImagePipelineOptions(target_format="JPEG"))

    assert opens == 1
    with original_open(target) as result:
        assert not result.getexif()


def test_jpeg_quality_search_uses_at_most_six_attempts() -> None:
    """Catches an unbounded or linear quality-reencoding loop."""
    attempted_qualities: list[int] = []

    def measure(quality: int) -> int:
        attempted_qualities.append(quality)
        return 400_000 if quality <= 70 else 700_000

    quality = choose_jpeg_quality(
        minimum=10,
        maximum=95,
        max_attempts=6,
        max_bytes=500_000,
        measure=measure,
    )

    assert len(attempted_qualities) <= 6
    assert quality == max(item for item in attempted_qualities if item <= 70)
