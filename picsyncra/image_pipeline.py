"""Single-pass, metadata-safe final raster image processing."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import secrets
from collections.abc import Callable

from PIL import Image, ImageOps

from .image_utils import fit_image_to_content


@dataclass(frozen=True)
class ImagePipelineOptions:
    target_format: str | None = None
    max_dimensions: tuple[int, int] = (2000, 2000)
    content_fit: bool = False
    compress_enabled: bool = False
    compress_quality: int = 85
    max_bytes: int | None = None


@dataclass(frozen=True)
class ImagePipelineResult:
    path: str
    size_bytes: int
    target_format: str
    quality: int | None
    encode_attempts: int


def choose_jpeg_quality(
    minimum: int,
    maximum: int,
    max_attempts: int,
    max_bytes: int,
    measure: Callable[[int], int],
) -> int:
    """Return the highest measured quality that fits, using bounded binary search."""
    lower = max(1, min(100, int(minimum)))
    upper = max(lower, min(100, int(maximum)))
    attempts = max(1, int(max_attempts))
    best: int | None = None
    lowest_attempted = upper

    for _ in range(attempts):
        if lower > upper:
            break
        quality = (lower + upper) // 2
        lowest_attempted = min(lowest_attempted, quality)
        if measure(quality) <= max_bytes:
            best = quality
            lower = quality + 1
        else:
            upper = quality - 1
    return best if best is not None else lowest_attempted


def _target_format(path: str, requested: str | None, source_format: str | None) -> str:
    if requested:
        return str(requested).upper()
    suffix = Path(path).suffix.lower()
    by_suffix = {
        ".jpg": "JPEG",
        ".jpeg": "JPEG",
        ".png": "PNG",
        ".webp": "WEBP",
        ".bmp": "BMP",
        ".gif": "GIF",
        ".tif": "TIFF",
        ".tiff": "TIFF",
    }
    return by_suffix.get(suffix, str(source_format or "PNG").upper())


def _normalize_mode(image: Image.Image, target_format: str) -> Image.Image:
    if target_format == "JPEG" and image.mode not in {"RGB", "L"}:
        if image.mode in {"RGBA", "LA"}:
            rgba = image.convert("RGBA")
            background = Image.new("RGB", rgba.size, "white")
            background.paste(rgba, mask=rgba.getchannel("A"))
            return background
        return image.convert("RGB")
    if target_format in {"BMP", "GIF"} and image.mode in {"RGBA", "LA"}:
        return image.convert("RGB")
    return image


def _save(image: Image.Image, path: str, target_format: str, quality: int | None) -> None:
    params: dict[str, object] = {}
    if target_format == "JPEG":
        params.update(quality=quality or 95, optimize=True)
    elif target_format == "WEBP":
        params["quality"] = quality or 95
    elif target_format == "PNG":
        params["optimize"] = True
    image.save(path, format=target_format, **params)


def process_image(
    source_path: str,
    target_path: str,
    options: ImagePipelineOptions,
) -> ImagePipelineResult:
    """Transform a raster once and atomically publish its metadata-free output."""
    with Image.open(source_path) as opened:
        source_format = opened.format
        image = ImageOps.exif_transpose(opened)
        image.load()
        image = image.copy()

    target_format = _target_format(target_path, options.target_format, source_format)
    image = _normalize_mode(image, target_format)
    if options.content_fit:
        image = fit_image_to_content(image)
    width, height = options.max_dimensions
    image.thumbnail((max(1, int(width)), max(1, int(height))), Image.Resampling.LANCZOS)

    target_dir = os.path.dirname(os.path.abspath(target_path)) or os.curdir
    os.makedirs(target_dir, exist_ok=True)
    prefix = f".{Path(target_path).name}.pipeline-"
    attempts: list[str] = []
    successful: dict[int, str] = {}
    selected_quality: int | None = None

    try:
        if options.max_bytes and target_format in {"JPEG", "WEBP"}:
            initial_quality = int(options.compress_quality if options.compress_enabled else 95)

            def measure(quality: int) -> int:
                attempt_path = os.path.join(target_dir, f"{prefix}{secrets.token_hex(8)}")
                attempts.append(attempt_path)
                _save(image, attempt_path, target_format, quality)
                size = os.path.getsize(attempt_path)
                if size <= int(options.max_bytes or 0):
                    successful[quality] = attempt_path
                return size

            selected_quality = choose_jpeg_quality(
                minimum=10,
                maximum=max(10, min(100, initial_quality)),
                max_attempts=6,
                max_bytes=int(options.max_bytes),
                measure=measure,
            )
            selected_path = successful.get(selected_quality)
            if selected_path is None:
                selected_path = min(attempts, key=os.path.getsize)
            os.replace(selected_path, target_path)
        else:
            temporary_path = os.path.join(target_dir, f"{prefix}{secrets.token_hex(8)}")
            attempts.append(temporary_path)
            selected_quality = (
                int(options.compress_quality if options.compress_enabled else 95)
                if target_format in {"JPEG", "WEBP"}
                else None
            )
            _save(image, temporary_path, target_format, selected_quality)
            os.replace(temporary_path, target_path)
    finally:
        for attempt_path in attempts:
            if os.path.exists(attempt_path):
                try:
                    os.remove(attempt_path)
                except OSError:
                    pass

    return ImagePipelineResult(
        path=target_path,
        size_bytes=os.path.getsize(target_path),
        target_format=target_format,
        quality=selected_quality,
        encode_attempts=len(attempts),
    )
