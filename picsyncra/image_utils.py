"""Image helpers shared by preview and save workflows."""

from __future__ import annotations

import math

from .common import AA

try:  # pragma: no cover - depends on optional Pillow availability
    from PIL import ImageChops, ImageStat
except Exception:  # pragma: no cover - handled by returning unchanged images
    ImageChops = None
    ImageStat = None


DEFAULT_CONTENT_FIT_MARGIN_RATIO = 0.06
DEFAULT_CONTENT_FIT_DIFF_THRESHOLD = 18
DEFAULT_CONTENT_FIT_ALPHA_THRESHOLD = 8
DEFAULT_CONTENT_FIT_MAX_DETECTION_SIZE = 512


def _full_box(size: tuple[int, int]) -> tuple[int, int, int, int]:
    width, height = size
    return 0, 0, width, height


def _box_area(box: tuple[int, int, int, int]) -> int:
    left, top, right, bottom = box
    return max(0, right - left) * max(0, bottom - top)


def _is_effective_crop(
    box: tuple[int, int, int, int],
    size: tuple[int, int],
    *,
    max_area_ratio: float = 0.995,
) -> bool:
    full = _full_box(size)
    if box == full:
        return False
    full_area = max(1, size[0] * size[1])
    if _box_area(box) / full_area >= max_area_ratio:
        return False
    return True


def _corner_background_color(image) -> tuple[int, int, int]:
    if ImageStat is None:
        return 255, 255, 255
    width, height = image.size
    patch = max(1, min(width, height, max(2, min(width, height) // 20)))
    corners = (
        (0, 0, patch, patch),
        (max(0, width - patch), 0, width, patch),
        (0, max(0, height - patch), patch, height),
        (max(0, width - patch), max(0, height - patch), width, height),
    )
    means = []
    for box in corners:
        try:
            means.append(ImageStat.Stat(image.crop(box)).mean[:3])
        except Exception:
            continue
    if not means:
        return 255, 255, 255
    color = []
    for channel in range(3):
        values = sorted(mean[channel] for mean in means)
        mid = len(values) // 2
        if len(values) % 2:
            value = values[mid]
        else:
            value = (values[mid - 1] + values[mid]) / 2.0
        color.append(max(0, min(255, int(round(value)))))
    return tuple(color)


def _scale_box(
    box: tuple[int, int, int, int],
    source_size: tuple[int, int],
    target_size: tuple[int, int],
) -> tuple[int, int, int, int]:
    source_w, source_h = source_size
    target_w, target_h = target_size
    scale_x = target_w / max(1, source_w)
    scale_y = target_h / max(1, source_h)
    left = max(0, min(target_w, int(math.floor(box[0] * scale_x))))
    top = max(0, min(target_h, int(math.floor(box[1] * scale_y))))
    right = max(0, min(target_w, int(math.ceil(box[2] * scale_x))))
    bottom = max(0, min(target_h, int(math.ceil(box[3] * scale_y))))
    if right <= left or bottom <= top:
        return _full_box(target_size)
    return left, top, right, bottom


def find_content_bbox(
    image,
    *,
    diff_threshold: int = DEFAULT_CONTENT_FIT_DIFF_THRESHOLD,
    alpha_threshold: int = DEFAULT_CONTENT_FIT_ALPHA_THRESHOLD,
    max_detection_size: int = DEFAULT_CONTENT_FIT_MAX_DETECTION_SIZE,
) -> tuple[int, int, int, int] | None:
    """Return the detected non-background area in original image coordinates."""

    if ImageChops is None:
        return None
    width, height = image.size
    if width <= 0 or height <= 0:
        return None
    work = image.convert("RGBA")
    if max(width, height) > max_detection_size > 0:
        work.thumbnail((max_detection_size, max_detection_size))
    work_size = work.size

    if "A" in work.getbands():
        alpha = work.getchannel("A")
        mask = alpha.point(lambda value: 255 if value > alpha_threshold else 0)
        alpha_box = mask.getbbox()
        if alpha_box and _is_effective_crop(alpha_box, work_size, max_area_ratio=0.98):
            return _scale_box(alpha_box, work_size, image.size)

    rgb = work.convert("RGB")
    bg_color = _corner_background_color(rgb)
    diff = ImageChops.difference(rgb, AA.new("RGB", rgb.size, bg_color)).convert("L")
    mask = diff.point(lambda value: 255 if value > diff_threshold else 0)
    bbox = mask.getbbox()
    if not bbox or not _is_effective_crop(bbox, work_size, max_area_ratio=0.98):
        return None
    return _scale_box(bbox, work_size, image.size)


def _expand_box(
    box: tuple[int, int, int, int],
    size: tuple[int, int],
    *,
    margin_ratio: float,
) -> tuple[int, int, int, int]:
    width, height = size
    left, top, right, bottom = box
    content_w = max(1, right - left)
    content_h = max(1, bottom - top)
    margin = int(math.ceil(max(content_w, content_h) * max(0.0, margin_ratio)))
    return (
        max(0, left - margin),
        max(0, top - margin),
        min(width, right + margin),
        min(height, bottom + margin),
    )


def _fit_box_to_aspect(
    box: tuple[int, int, int, int],
    size: tuple[int, int],
    target_aspect: float | None,
) -> tuple[int, int, int, int]:
    if not target_aspect or target_aspect <= 0:
        return box
    width, height = size
    left, top, right, bottom = box
    min_w = max(1.0, float(right - left))
    min_h = max(1.0, float(bottom - top))
    target_w = min_w
    target_h = min_h
    if target_w / target_h < target_aspect:
        target_w = target_h * target_aspect
    else:
        target_h = target_w / target_aspect
    if target_w > width:
        target_w = float(width)
        target_h = target_w / target_aspect
    if target_h > height:
        target_h = float(height)
        target_w = target_h * target_aspect
    if target_w < min_w or target_h < min_h:
        return box

    center_x = (left + right) / 2.0
    center_y = (top + bottom) / 2.0
    new_left = int(round(center_x - target_w / 2.0))
    new_top = int(round(center_y - target_h / 2.0))
    new_left = max(0, min(width - int(round(target_w)), new_left))
    new_top = max(0, min(height - int(round(target_h)), new_top))
    new_right = min(width, new_left + int(round(target_w)))
    new_bottom = min(height, new_top + int(round(target_h)))
    if new_right <= new_left or new_bottom <= new_top:
        return box
    return new_left, new_top, new_right, new_bottom


def _resample_filter():
    if hasattr(AA, "Resampling"):
        return AA.Resampling.LANCZOS
    return getattr(AA, "LANCZOS", getattr(AA, "BICUBIC", 3))


def fit_image_to_content(
    image,
    *,
    target_size: tuple[int, int] | None = None,
    margin_ratio: float = DEFAULT_CONTENT_FIT_MARGIN_RATIO,
) -> object:
    """Zoom into detected content while keeping the original image dimensions."""

    bbox = find_content_bbox(image)
    if bbox is None:
        return image.copy()
    # ``target_size`` is accepted for existing callers; zoom output keeps source size.
    width, height = image.size
    target_aspect = width / max(1, height)
    crop_box = _expand_box(bbox, image.size, margin_ratio=margin_ratio)
    crop_box = _fit_box_to_aspect(crop_box, image.size, target_aspect)
    if not _is_effective_crop(crop_box, image.size):
        return image.copy()
    return image.crop(crop_box).resize(image.size, _resample_filter())
