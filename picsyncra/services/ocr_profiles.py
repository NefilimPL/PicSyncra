"""Static, offline OCR performance profiles."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OcrProfile:
    """One local PaddleOCR detector/recognizer pair."""

    id: str
    label: str
    description: str
    detector_model: str
    recognizer_model: str


_PROFILES = (
    OcrProfile(
        id="fast",
        label="Szybki",
        description="PP-OCRv5 Mobile — mniejsze zuzycie zasobow.",
        detector_model="PP-OCRv5_mobile_det",
        recognizer_model="PP-OCRv5_mobile_rec",
    ),
    OcrProfile(
        id="accurate",
        label="Dokladny",
        description="PP-OCRv5 Server — wolniejszy, dokladniejszy odczyt.",
        detector_model="PP-OCRv5_server_det",
        recognizer_model="PP-OCRv5_server_rec",
    ),
)


def available_ocr_profiles() -> tuple[OcrProfile, ...]:
    """Return profiles bundled by the application, without probing the network."""

    return _PROFILES


def normalize_ocr_profile_ids(value: object) -> list[str]:
    """Keep known profile identifiers once, preserving the requested order."""

    requested = value if isinstance(value, list) else []
    known = {profile.id for profile in _PROFILES}
    result: list[str] = []
    for raw in requested:
        profile_id = str(raw or "").strip()
        if profile_id in known and profile_id not in result:
            result.append(profile_id)
    return result


def ocr_profile(profile_id: object) -> OcrProfile:
    """Resolve one known profile, using fast as the safe default."""

    normalized = str(profile_id or "").strip()
    return next((item for item in _PROFILES if item.id == normalized), _PROFILES[0])
