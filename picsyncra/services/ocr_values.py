"""Canonical values extracted from OCR and used by slot validation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OcrValue:
    """One numeric OCR candidate with its original image coordinates."""

    text: str
    comparison: str
    confidence: float
    bbox: tuple[int, int, int, int]


def normalize_entered_ocr_value(value: object) -> str:
    """Store user decimal commas in the canonical dot notation."""

    return str(value or "").strip().replace(",", ".")


def comparison_key(value: object) -> str:
    """Return a tolerant numeric identity without discarding decimal digits."""

    text = normalize_entered_ocr_value(value)
    result: list[str] = []
    index = 0
    while index < len(text):
        if text[index].isdigit():
            start = index
            while index < len(text) and text[index].isdigit():
                index += 1
            number = text[start:index]
            while (
                index + 1 < len(text)
                and text[index] == "."
                and text[index + 1].isdigit()
            ):
                index += 1
                decimal_start = index
                while index < len(text) and text[index].isdigit():
                    index += 1
                number += f".{text[decimal_start:index]}"
            result.append(number)
            continue
        if not text[index].isalpha() and not text[index].isspace():
            result.append("?")
        index += 1
    comparison = "".join(result)
    return comparison if any(character.isdigit() for character in comparison) else ""


def ocr_values_match(left: object, right: object) -> bool:
    """Compare values only when both contain a recognized numeric value."""

    left_key = comparison_key(left)
    return bool(left_key) and left_key == comparison_key(right)
