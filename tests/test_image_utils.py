"""Tests for image content fitting helpers."""

from __future__ import annotations

from PIL import Image

from picsyncra.image_utils import fit_image_to_content, find_content_bbox


def test_find_content_bbox_detects_white_border() -> None:
    image = Image.new("RGB", (400, 300), "white")
    for x in range(150, 251):
        for y in range(100, 201):
            image.putpixel((x, y), (20, 20, 20))

    bbox = find_content_bbox(image)

    assert bbox is not None
    assert 140 <= bbox[0] <= 155
    assert 95 <= bbox[1] <= 105
    assert 245 <= bbox[2] <= 260
    assert 195 <= bbox[3] <= 210


def test_fit_image_to_content_zooms_without_changing_image_size() -> None:
    image = Image.new("RGB", (400, 300), "white")
    for x in range(150, 251):
        for y in range(100, 201):
            image.putpixel((x, y), (20, 20, 20))

    original_bbox = find_content_bbox(image)
    fitted = fit_image_to_content(image, target_size=(200, 200), margin_ratio=0.08)
    fitted_bbox = find_content_bbox(fitted)

    assert original_bbox is not None
    assert fitted_bbox is not None
    assert fitted.size == image.size
    assert fitted_bbox[2] - fitted_bbox[0] > original_bbox[2] - original_bbox[0]
    assert fitted_bbox[3] - fitted_bbox[1] > original_bbox[3] - original_bbox[1]


def test_fit_image_to_content_uses_alpha_border() -> None:
    image = Image.new("RGBA", (300, 200), (255, 255, 255, 0))
    for x in range(90, 211):
        for y in range(60, 141):
            image.putpixel((x, y), (0, 0, 0, 255))

    original_bbox = find_content_bbox(image)
    fitted = fit_image_to_content(image, target_size=(240, 176), margin_ratio=0.05)
    fitted_bbox = find_content_bbox(fitted)

    assert original_bbox is not None
    assert fitted_bbox is not None
    assert fitted.size == image.size
    assert fitted_bbox[2] - fitted_bbox[0] > original_bbox[2] - original_bbox[0]
    assert fitted_bbox[3] - fitted_bbox[1] > original_bbox[3] - original_bbox[1]
