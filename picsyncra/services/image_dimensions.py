"""Local image-dimension extraction primitives.

The optional PaddleOCR/OpenCV runtime is deliberately isolated here so the
standard web application can operate without ML dependencies installed.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation
from importlib import metadata, util
import math
import os
from pathlib import Path
import re
import sys
from typing import Callable, Iterable, Mapping, Protocol

from .ocr_values import comparison_key
from .ocr_profiles import available_ocr_profiles, normalize_ocr_profile_ids, ocr_profile


_DIMENSIONS = frozenset({"width", "depth", "height"})
_NUMBER_PATTERN = re.compile(r"(?<![\d.,])\d+(?:[.,]\d+)*")
_DIMENSION_UNIT_PATTERN = re.compile(r"(?<![a-z])(?:mm|cm)(?![a-z])", re.IGNORECASE)
_WEIGHT_UNIT_PATTERN = re.compile(r"(?<![a-z])kg(?![a-z])", re.IGNORECASE)
_DIMENSION_HINTS = {
    "width": frozenset({"w", "width", "szer", "szerokosc", "szerokość"}),
    "depth": frozenset({"d", "depth", "gleb", "glebokosc", "głęb", "głębokość"}),
    "height": frozenset({"h", "height", "wys", "wysokosc", "wysokość"}),
}
_DIMENSION_LABELS = {
    "width": "szerokosci",
    "depth": "glebokosci",
    "height": "wysokosci",
}
_DIMENSION_NOMINATIVE_LABELS = {
    "width": "szerokosc",
    "depth": "glebokosc",
    "height": "wysokosc",
}
_OCR_ENGINE_NAME = "PaddleOCR"
_OCR_GITHUB_URL = "https://github.com/PaddlePaddle/PaddleOCR"


class ImageDimensionUnavailable(RuntimeError):
    """Raised when the optional local OCR runtime has not been installed."""


@dataclass(frozen=True)
class ImageDimensionRequest:
    slot: str
    dimension: str
    minimum_text_confidence: float = 0.8

    def __post_init__(self) -> None:
        if not str(self.slot).strip():
            raise ValueError("Numer slotu jest wymagany.")
        if self.dimension not in _DIMENSIONS:
            raise ValueError("Nieobslugiwany rodzaj wymiaru.")
        if not 0 <= float(self.minimum_text_confidence) <= 1:
            raise ValueError("Minimalna pewnosc musi byc od 0 do 1.")


@dataclass(frozen=True)
class OcrTextBox:
    text: str
    confidence: float
    bbox: tuple[int, int, int, int]
    hint: str | None = None
    angle: float | None = None


@dataclass(frozen=True)
class DimensionLine:
    x1: int
    y1: int
    x2: int
    y2: int


@dataclass(frozen=True)
class ImageDimensionResult:
    value: str
    text_confidence: float | None
    warning: dict[str, str] | None = None


@dataclass(frozen=True)
class OcrDiagnosticCandidate:
    text: str
    confidence: float
    bbox: tuple[int, int, int, int]
    dimension: str | None
    value: str
    accepted: bool
    reason: str = ""
    selected: bool = False


@dataclass(frozen=True)
class ImageOcrDiagnostics:
    available: bool
    dimensions: dict[str, str]
    candidates: list[OcrDiagnosticCandidate]
    message: str = ""
    attempts: dict[str, str] = field(default_factory=dict)
    regions: list[dict[str, object]] = field(default_factory=list)
    timings_ms: dict[str, int] = field(default_factory=dict)


class ImageDimensionRecognizer(Protocol):
    def detect(self, path: str) -> list[OcrTextBox]:
        """Return OCR candidates for one local image file."""


def _has_reliable_numeric_box(boxes: Iterable[OcrTextBox]) -> bool:
    """Return whether a primary OCR pass found a usable numeric value."""

    return any(
        bool(comparison_key(box.text)) and float(box.confidence) >= 0.8
        for box in boxes
    )


def rotate_ocr_box_to_source(
    box: OcrTextBox,
    *,
    rotation: str,
    source_width: int,
    source_height: int,
) -> OcrTextBox:
    """Map one OCR box from a 90-degree rotated image to its source image."""

    width = max(1, int(source_width))
    height = max(1, int(source_height))
    left, top, right, bottom = (int(value) for value in box.bbox)
    if rotation == "clockwise":
        mapped = (top, height - right, bottom, height - left)
        angle_offset = -90.0
    elif rotation == "counterclockwise":
        mapped = (width - bottom, left, width - top, right)
        angle_offset = 90.0
    else:
        raise ValueError(f"Nieobslugiwana rotacja OCR: {rotation}")

    mapped_left, mapped_top, mapped_right, mapped_bottom = mapped
    mapped_bbox = (
        max(0, min(width, mapped_left)),
        max(0, min(height, mapped_top)),
        max(0, min(width, mapped_right)),
        max(0, min(height, mapped_bottom)),
    )
    angle = None if box.angle is None else float(box.angle) + angle_offset
    return replace(box, bbox=mapped_bbox, angle=angle)


def image_dimension_source_key(slot: str, dimension: str) -> str:
    return f"IMAGE_DIMENSION:{str(slot).strip()}:{str(dimension).upper()}"


def _display_confidence(value: float) -> int:
    return round(max(0.0, min(1.0, value)) * 100)


def _warning(code: str, slot: str, message: str) -> dict[str, str]:
    return {"code": code, "slot": slot, "message": message}


def _normalized_hint(value: str | None) -> str | None:
    text = str(value or "").strip().casefold()
    if not text:
        return None
    for dimension, hints in _DIMENSION_HINTS.items():
        if text in hints:
            return dimension
    return None


def _parse_numeric_value(value: str) -> str | None:
    match = _NUMBER_PATTERN.search(str(value or ""))
    if not match:
        return None
    try:
        token = match.group(0).strip(".,")
        parts = [part for part in re.split(r"[.,]", token) if part]
        if not parts:
            return None
        normalized_token = parts[0]
        if len(parts) > 1:
            normalized_token += "." + "".join(parts[1:])
        parsed = Decimal(normalized_token)
    except InvalidOperation:
        return None
    if not parsed.is_finite() or parsed <= 0:
        return None
    normalized = format(parsed.normalize(), "f")
    return normalized.rstrip("0").rstrip(".") if "." in normalized else normalized


def _restore_lost_decimal_separator(
    text: str, components: Iterable[tuple[int, int, int, int, int]]
) -> str:
    """Restore a decimal only when the cropped image contains its small glyph."""

    source = str(text or "")
    match = _NUMBER_PATTERN.search(source)
    if not match:
        return source
    token = match.group(0)
    if len(token) < 2 or not token.isdigit():
        return source
    glyphs = [
        tuple(int(value) for value in component)
        for component in components
        if len(component) == 5 and int(component[4]) > 0
    ]
    if len(glyphs) <= len(token):
        return source
    digit_glyphs = sorted(glyphs, key=lambda item: item[4], reverse=True)[: len(token)]
    digit_glyphs.sort(key=lambda item: item[0] + item[2] / 2)
    minimum_digit_area = min(component[4] for component in digit_glyphs)
    minimum_digit_height = min(component[3] for component in digit_glyphs)
    for index, (left_digit, right_digit) in enumerate(
        zip(digit_glyphs, digit_glyphs[1:]), start=1
    ):
        left_center = left_digit[0] + left_digit[2] / 2
        right_center = right_digit[0] + right_digit[2] / 2
        marker_found = any(
            component not in digit_glyphs
            and left_center < component[0] + component[2] / 2 < right_center
            and component[4] <= minimum_digit_area * 0.45
            and component[3] <= minimum_digit_height * 0.5
            for component in glyphs
        )
        if marker_found:
            separator_at = match.start() + index
            return f"{source[:separator_at]},{source[separator_at:]}"
    return source


def _text_components_from_crop(
    image: object, bbox: tuple[int, int, int, int], cv2: object
) -> list[tuple[int, int, int, int, int]]:
    """Return glyph components from an enlarged OCR crop without another OCR run."""

    try:
        image_height, image_width = image.shape[:2]
        left, top, right, bottom = bbox
        left, right = max(0, left), min(int(image_width), right)
        top, bottom = max(0, top), min(int(image_height), bottom)
        if right - left < 2 or bottom - top < 2:
            return []
        crop = image[top:bottom, left:right]
        gray = (
            cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            if len(crop.shape) == 3
            else crop
        )
        if gray.shape[0] >= gray.shape[1] * 1.35 and hasattr(cv2, "ROTATE_90_CLOCKWISE"):
            gray = cv2.rotate(gray, cv2.ROTATE_90_CLOCKWISE)
        enlarged = cv2.resize(
            gray,
            (max(1, gray.shape[1] * 4), max(1, gray.shape[0] * 4)),
            interpolation=cv2.INTER_CUBIC,
        )
        _, binary = cv2.threshold(
            enlarged, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU
        )
        _, _, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
        return [tuple(int(value) for value in component) for component in stats[1:]]
    except Exception:
        return []


def _retry_low_confidence_dimension_label(
    box: OcrTextBox,
    image: object,
    cv2: object,
    predict: Callable[[object], Iterable[object]],
) -> OcrTextBox:
    """Retry one incomplete cm/mm label on a rotated, enlarged crop."""

    original_number = _NUMBER_PATTERN.search(box.text)
    if (
        float(box.confidence) >= 0.8
        or not _has_dimension_unit(box.text)
        or _is_weight_text(box.text)
        or not original_number
        or len(re.sub(r"[^0-9]", "", original_number.group(0))) != 1
    ):
        return box
    try:
        image_height, image_width = image.shape[:2]
        left, top, right, bottom = box.bbox
        padding = max(4, round(max(right - left, bottom - top) * 0.35))
        left, right = max(0, left - padding), min(int(image_width), right + padding)
        top, bottom = max(0, top - padding), min(int(image_height), bottom + padding)
        crop = image[top:bottom, left:right]
        if crop.shape[0] >= crop.shape[1] * 1.35:
            crop = cv2.rotate(crop, cv2.ROTATE_90_CLOCKWISE)
        enlarged = cv2.resize(
            crop,
            (max(1, crop.shape[1] * 4), max(1, crop.shape[0] * 4)),
            interpolation=cv2.INTER_CUBIC,
        )
        retries: list[tuple[str, float]] = []
        for page in predict(enlarged):
            payload = page.json if hasattr(page, "json") else page
            result = payload.get("res", payload) if isinstance(payload, dict) else {}
            texts = result.get("rec_texts", []) if isinstance(result, dict) else []
            scores = result.get("rec_scores", []) if isinstance(result, dict) else []
            for text, score in zip(texts, scores):
                candidate = str(text)
                candidate_number = _NUMBER_PATTERN.search(candidate)
                if (
                    not candidate_number
                    or not _has_dimension_unit(candidate)
                    or _is_weight_text(candidate)
                ):
                    continue
                confidence = float(score)
                digit_count = len(re.sub(r"[^0-9]", "", candidate_number.group(0)))
                if digit_count > 1 and confidence > float(box.confidence):
                    retries.append((candidate, confidence))
        if retries:
            text, confidence = max(
                retries,
                key=lambda candidate: (
                    len(re.sub(r"[^0-9]", "", _NUMBER_PATTERN.search(candidate[0]).group(0))),
                    candidate[1],
                ),
            )
            return replace(box, text=text, confidence=confidence)
    except Exception:
        pass
    return box


def _is_weight_text(value: str) -> bool:
    return bool(_WEIGHT_UNIT_PATTERN.search(str(value or "")))


def _has_dimension_unit(value: str) -> bool:
    return bool(_DIMENSION_UNIT_PATTERN.search(str(value or "")))


def _candidate_for_dimension(
    boxes: Iterable[OcrTextBox], dimension: str
) -> OcrTextBox | None:
    candidates = [
        box
        for box in boxes
        if _normalized_hint(box.hint) == dimension
        and _parse_numeric_value(box.text) is not None
        and not _is_weight_text(box.text)
    ]
    if not candidates:
        return None
    return max(candidates, key=_dimension_candidate_rank)


def _dimension_candidate_rank(item: OcrTextBox | OcrDiagnosticCandidate) -> tuple[Decimal, int, float]:
    """Always select the largest detected value for one dimension."""

    try:
        magnitude = Decimal(_parse_numeric_value(item.text) or "0")
    except InvalidOperation:
        magnitude = Decimal(0)
    return (magnitude, _has_dimension_unit(item.text), float(item.confidence))


def _line_dimension(line: DimensionLine) -> str | None:
    angle = abs(math.degrees(math.atan2(line.y2 - line.y1, line.x2 - line.x1)))
    if angle > 90:
        angle = 180 - angle
    if angle <= 15:
        return "width"
    if 75 <= angle <= 105:
        return "height"
    if 20 <= angle <= 70:
        return "depth"
    return None


def _text_angle_dimension(angle: float | None) -> str | None:
    """Map the orientation of a dimension label to its measured axis."""

    if angle is None or not math.isfinite(float(angle)):
        return None
    normalized = abs(float(angle)) % 180
    if normalized > 90:
        normalized = 180 - normalized
    if normalized <= 15:
        return "width"
    if normalized >= 75:
        return "height"
    if 20 <= normalized <= 70:
        return "depth"
    return None


def _box_shape_dimension(box: OcrTextBox, *, include_width: bool = False) -> str | None:
    left, top, right, bottom = box.bbox
    width = max(1, right - left)
    height = max(1, bottom - top)
    if height >= width * 1.35:
        return "height"
    if include_width and width >= height * 1.35:
        return "width"
    return None


def _unit_box_fallback_dimension(box: OcrTextBox) -> str | None:
    """Classify a cm/mm label when OCR did not preserve its text angle."""

    if not _has_dimension_unit(box.text):
        return None
    left, top, right, bottom = box.bbox
    width = max(1, right - left)
    height = max(1, bottom - top)
    if width >= height * 1.35:
        return "width"
    if height >= width * 1.35:
        return "height"
    return "depth"


def _distance_to_segment(x: float, y: float, line: DimensionLine) -> float:
    delta_x = line.x2 - line.x1
    delta_y = line.y2 - line.y1
    squared_length = delta_x * delta_x + delta_y * delta_y
    if squared_length == 0:
        return math.hypot(x - line.x1, y - line.y1)
    factor = max(
        0.0,
        min(
            1.0,
            ((x - line.x1) * delta_x + (y - line.y1) * delta_y) / squared_length,
        ),
    )
    return math.hypot(x - (line.x1 + factor * delta_x), y - (line.y1 + factor * delta_y))


def associate_dimension_hints(
    boxes: Iterable[OcrTextBox], lines: Iterable[DimensionLine]
) -> list[OcrTextBox]:
    """Classify unlabelled numeric OCR boxes by their nearest dimension line."""

    usable_lines = [line for line in lines if _line_dimension(line)]
    associated: list[OcrTextBox] = []
    for box in boxes:
        if _is_weight_text(box.text):
            associated.append(replace(box, hint=None))
            continue
        if _normalized_hint(box.hint) or _parse_numeric_value(box.text) is None:
            associated.append(box)
            continue
        shape_dimension = _box_shape_dimension(box)
        if shape_dimension:
            associated.append(replace(box, hint=shape_dimension))
            continue
        angle_dimension = _text_angle_dimension(box.angle)
        if angle_dimension:
            associated.append(replace(box, hint=angle_dimension))
            continue
        unit_fallback_dimension = _unit_box_fallback_dimension(box)
        if unit_fallback_dimension:
            associated.append(replace(box, hint=unit_fallback_dimension))
            continue
        left, top, right, bottom = box.bbox
        center_x = (left + right) / 2
        center_y = (top + bottom) / 2
        if not usable_lines:
            fallback_shape_dimension = _box_shape_dimension(box, include_width=True)
            if fallback_shape_dimension:
                associated.append(replace(box, hint=fallback_shape_dimension))
                continue
            associated.append(box)
            continue
        closest = min(
            usable_lines,
            key=lambda line: _distance_to_segment(center_x, center_y, line),
        )
        associated.append(replace(box, hint=_line_dimension(closest)))
    return associated


class MultiProfileImageDimensionRecognizer:
    """Run every selected local OCR profile and merge their text boxes."""

    def __init__(
        self,
        profile_ids: Iterable[object],
        *,
        recognizer_factory: Callable[[object], ImageDimensionRecognizer] | None = None,
    ) -> None:
        self._profile_ids = normalize_ocr_profile_ids(list(profile_ids)) or ["fast"]
        self._recognizer_factory = recognizer_factory or PaddleImageDimensionRecognizer

    @staticmethod
    def _box_key(box: OcrTextBox) -> tuple[str, tuple[int, int, int, int]]:
        text = str(box.text or "").strip().casefold()
        return text, box.bbox

    def detect(self, path: str) -> list[OcrTextBox]:
        boxes: list[OcrTextBox] = []
        positions: dict[tuple[str, tuple[int, int, int, int]], int] = {}
        failures: list[str] = []
        for profile_id in self._profile_ids:
            try:
                detected = self._recognizer_factory(profile_id).detect(path)
            except Exception as exc:
                message = str(exc).strip()
                failures.append(message or f"Nie udalo sie uruchomic profilu OCR {profile_id}.")
                continue
            for box in detected:
                key = self._box_key(box)
                existing_index = positions.get(key)
                if existing_index is None:
                    positions[key] = len(boxes)
                    boxes.append(box)
                elif box.confidence > boxes[existing_index].confidence:
                    boxes[existing_index] = box
        if boxes or not failures:
            return boxes
        raise ImageDimensionUnavailable("; ".join(failures))


def _default_recognizer(profile_ids: Iterable[object] | None = None) -> ImageDimensionRecognizer:
    return MultiProfileImageDimensionRecognizer(profile_ids or ["fast"])


def _optional_package_version(package: str) -> str | None:
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return None


def _paddlex_ocr_pipeline_is_available() -> bool:
    spec = util.find_spec("paddlex")
    origin = str(getattr(spec, "origin", "") or "").strip()
    return bool(origin) and (
        Path(origin).parent / "configs" / "pipelines" / "OCR.yaml"
    ).is_file()


def _paddlex_ocr_core_is_available() -> bool:
    try:
        from paddlex.utils.deps import is_extra_available

        return bool(is_extra_available("ocr-core"))
    except Exception:
        return False


def image_ocr_runtime_info() -> dict[str, object]:
    """Return OCR display metadata without initializing an OCR model."""

    paddleocr_version = _optional_package_version("paddleocr")
    paddle_version = _optional_package_version("paddlepaddle")
    opencv_version = (
        _optional_package_version("opencv-python-headless")
        or _optional_package_version("opencv-python")
        or _optional_package_version("opencv-contrib-python")
    )
    available = bool(
        util.find_spec("paddleocr")
        and util.find_spec("cv2")
        and _paddlex_ocr_pipeline_is_available()
        and _paddlex_ocr_core_is_available()
    )
    model_cache_path = ocr_model_cache_path()
    return {
        "available": available,
        "engine": {
            "name": _OCR_ENGINE_NAME,
            "version": paddleocr_version or "niezainstalowany",
        },
        "runtime": {
            "name": "PaddlePaddle + OpenCV",
            "version": " / ".join(
                value for value in (paddle_version, opencv_version) if value
            )
            or "niezainstalowany",
        },
        "models": [
            {
                "id": profile.id,
                "name": profile.label,
                "version": "lang=en",
                "description": profile.description,
                "status": (
                    "ready"
                    if available and _model_cache_has_profile(model_cache_path, profile)
                    else "unavailable"
                ),
            }
            for profile in available_ocr_profiles()
        ],
        "github_url": _OCR_GITHUB_URL,
    }


def bundled_ocr_model_cache_path() -> str | None:
    """Return models unpacked by a PyInstaller one-file executable, if any."""

    bundle_root = getattr(sys, "_MEIPASS", "")
    if not bundle_root:
        return None
    candidate = Path(str(bundle_root)) / "ocr_models"
    return str(candidate) if candidate.is_dir() else None


def ocr_model_cache_path() -> str:
    """Choose a stable local cache, preferring models embedded in an EXE."""

    bundled = bundled_ocr_model_cache_path()
    if bundled:
        return bundled
    configured = str(os.environ.get("PADDLE_PDX_CACHE_HOME") or "").strip()
    if configured:
        return str(Path(configured))
    app_data = os.environ.get("LOCALAPPDATA")
    root = Path(app_data) if app_data else Path.home() / ".cache"
    return str(root / "PicSyncra" / "ocr-models")


def _model_cache_has_profile(path: str, profile: object) -> bool:
    """Return whether both locally configured model directories are populated."""
    try:
        model_root = Path(path) / "official_models"
        detector = str(getattr(profile, "detector_model", ""))
        recognizer = str(getattr(profile, "recognizer_model", ""))
        if not detector or not recognizer:
            return False
        return all(
            (model_root / model_name).is_dir() and any((model_root / model_name).iterdir())
            for model_name in (detector, recognizer)
        )
    except OSError:
        return False


def analyze_image_dimensions(
    path: str,
    minimum_text_confidence: float = 0.8,
    *,
    recognizer: ImageDimensionRecognizer | None = None,
) -> ImageOcrDiagnostics:
    """Inspect every OCR box for the settings diagnostic screen."""

    threshold = float(minimum_text_confidence)
    if not 0 <= threshold <= 1:
        raise ValueError("Minimalna pewnosc musi byc od 0 do 1.")
    try:
        boxes = (recognizer or _default_recognizer()).detect(path)
    except ImageDimensionUnavailable as exc:
        return ImageOcrDiagnostics(
            available=False,
            dimensions={dimension: "" for dimension in sorted(_DIMENSIONS)},
            candidates=[],
            message=str(exc).strip() or "Lokalny OCR nie jest zainstalowany.",
        )
    except Exception as exc:
        return ImageOcrDiagnostics(
            available=False,
            dimensions={dimension: "" for dimension in sorted(_DIMENSIONS)},
            candidates=[],
            message=f"Nie udalo sie uruchomic lokalnego OCR: {exc}",
        )

    candidates: list[OcrDiagnosticCandidate] = []
    best_indexes: dict[str, int] = {}
    for box in boxes:
        dimension = _normalized_hint(box.hint)
        value = _parse_numeric_value(box.text) or ""
        accepted = bool(
            dimension
            and value
            and not _is_weight_text(box.text)
            and float(box.confidence) >= threshold
        )
        if dimension is None:
            reason = (
                "Nie rozpoznano rodzaju wymiaru na podstawie orientacji tekstu ani linii wymiarowej."
            )
        elif not value:
            reason = "Nie rozpoznano dodatniej wartosci liczbowej."
        elif _is_weight_text(box.text):
            reason = "Odrzucono: odczyt zawiera jednostke masy, a nie wymiar."
        elif float(box.confidence) < threshold:
            reason = (
                f"Odrzucono: pewnosc {_display_confidence(float(box.confidence))}% "
                f"jest ponizej progu {_display_confidence(threshold)}%."
            )
        else:
            reason = f"Kandydat do {_DIMENSION_LABELS[dimension]}."
        candidate = OcrDiagnosticCandidate(
            text=str(box.text),
            confidence=float(box.confidence),
            bbox=box.bbox,
            dimension=dimension,
            value=value,
            accepted=accepted,
            reason=reason,
        )
        candidates.append(candidate)
        if accepted and dimension:
            previous_index = best_indexes.get(dimension)
            if (
                previous_index is None
                or _dimension_candidate_rank(candidate)
                > _dimension_candidate_rank(candidates[previous_index])
            ):
                best_indexes[dimension] = len(candidates) - 1

    selected_indexes = set(best_indexes.values())
    selected_candidates: list[OcrDiagnosticCandidate] = []
    for index, candidate in enumerate(candidates):
        if index in selected_indexes:
            selected_candidates.append(
                replace(
                    candidate,
                    reason=(
                        f"Wybrano jako {_DIMENSION_NOMINATIVE_LABELS[candidate.dimension]}."
                    ),
                    selected=True,
                )
            )
        elif candidate.accepted and candidate.dimension:
            chosen = candidates[best_indexes[candidate.dimension]]
            selected_candidates.append(
                replace(
                    candidate,
                    reason=(
                        f"Odrzucono: dla {_DIMENSION_LABELS[candidate.dimension]} "
                        f"wybrano wieksza wartosc {chosen.value}."
                    ),
                )
            )
        else:
            selected_candidates.append(candidate)

    attempts: dict[str, str] = {}
    for dimension in sorted(_DIMENSIONS):
        selected_index = best_indexes.get(dimension)
        if selected_index is not None:
            attempts[dimension] = (
                f"Wybrano {candidates[selected_index].value} jako "
                f"{_DIMENSION_NOMINATIVE_LABELS[dimension]}."
            )
        else:
            attempts[dimension] = (
                f"OCR przeanalizowal {len(candidates)} odczyt"
                f"{'y' if len(candidates) != 1 else ''}, ale nie przypisal zadnego do "
                f"{_DIMENSION_LABELS[dimension]}."
            )
    return ImageOcrDiagnostics(
        available=True,
        dimensions={
            dimension: candidates[best_indexes[dimension]].value
            if dimension in best_indexes
            else ""
            for dimension in sorted(_DIMENSIONS)
        },
        candidates=selected_candidates,
        attempts=attempts,
    )


def analyze_image_values(
    path: str,
    *,
    recognizer: ImageDimensionRecognizer | None = None,
    profile_ids: Iterable[object] | None = None,
) -> ImageOcrDiagnostics:
    """Return every OCR candidate with a numeric comparison key.

    This deliberately does not classify candidates as width, depth or height.
    The original OCR text remains available for display while ``value`` is used
    only for normalized comparisons.
    """

    try:
        boxes = (recognizer or _default_recognizer(profile_ids)).detect(path)
    except ImageDimensionUnavailable as exc:
        return ImageOcrDiagnostics(
            available=False,
            dimensions={},
            candidates=[],
            message=str(exc).strip() or "Lokalny OCR nie jest zainstalowany.",
        )
    except Exception as exc:
        return ImageOcrDiagnostics(
            available=False,
            dimensions={},
            candidates=[],
            message=f"Nie udalo sie uruchomic lokalnego OCR: {exc}",
        )

    return diagnostics_for_boxes(boxes)


def diagnostics_for_boxes(boxes: Iterable[OcrTextBox]) -> ImageOcrDiagnostics:
    """Turn already-detected text boxes into value diagnostics."""

    candidates = [
        OcrDiagnosticCandidate(
            text=str(box.text),
            confidence=float(box.confidence),
            bbox=box.bbox,
            dimension=None,
            value=comparison_key(box.text),
            accepted=bool(comparison_key(box.text)),
            reason=(
                "Wykryto wartosc liczbowa."
                if comparison_key(box.text)
                else "Odczyt nie zawiera liczby."
            ),
        )
        for box in boxes
    ]
    return ImageOcrDiagnostics(
        available=True,
        dimensions={},
        candidates=candidates,
        message="" if candidates else "Nie znaleziono tekstu na obrazie.",
    )


def _result_for_request(
    request: ImageDimensionRequest, boxes: Iterable[OcrTextBox]
) -> ImageDimensionResult:
    detected_boxes = list(boxes)
    candidate = _candidate_for_dimension(detected_boxes, request.dimension)
    if candidate is None:
        return ImageDimensionResult(
            "",
            None,
            _warning(
                "image_dimension_not_found",
                request.slot,
                f"OCR przeanalizowal {len(detected_boxes)} odczyt"
                f"{'y' if len(detected_boxes) != 1 else ''} w slocie {request.slot}, "
                f"ale nie przypisal zadnego do {_DIMENSION_LABELS[request.dimension]}.",
            ),
        )
    confidence = float(candidate.confidence)
    if confidence < float(request.minimum_text_confidence):
        actual = _display_confidence(confidence)
        required = _display_confidence(float(request.minimum_text_confidence))
        return ImageDimensionResult(
            "",
            confidence,
            _warning(
                "image_dimension_low_confidence",
                request.slot,
                f"Odczyt {actual}% jest ponizej wymaganego progu {required}%.",
            ),
        )
    return ImageDimensionResult(_parse_numeric_value(candidate.text) or "", confidence)


def resolve_image_dimensions(
    requests: Iterable[ImageDimensionRequest],
    slot_paths: Mapping[str, str],
    *,
    recognizer: ImageDimensionRecognizer | None = None,
) -> tuple[dict[str, str], list[dict[str, str]]]:
    """Resolve template sources, running OCR no more than once per slot."""

    grouped: dict[str, list[ImageDimensionRequest]] = {}
    for request in requests:
        grouped.setdefault(str(request.slot), []).append(request)

    values: dict[str, str] = {}
    warnings: list[dict[str, str]] = []
    active_recognizer = recognizer
    for slot, slot_requests in grouped.items():
        path = str(slot_paths.get(slot) or "")
        if not path:
            for request in slot_requests:
                values[image_dimension_source_key(slot, request.dimension)] = ""
            warnings.append(
                _warning(
                    "image_dimension_missing_slot",
                    slot,
                    f"Brak obrazu w slocie {slot}.",
                )
            )
            continue
        try:
            if active_recognizer is None:
                active_recognizer = _default_recognizer()
            boxes = active_recognizer.detect(path)
        except Exception:
            for request in slot_requests:
                values[image_dimension_source_key(slot, request.dimension)] = ""
            warnings.append(
                _warning(
                    "ocr_unavailable",
                    slot,
                    "Lokalny OCR jest niedostepny.",
                )
            )
            continue
        for request in slot_requests:
            result = _result_for_request(request, boxes)
            values[image_dimension_source_key(slot, request.dimension)] = result.value
            if result.warning:
                warnings.append(result.warning)
    return values, warnings


class PaddleImageDimensionRecognizer:
    """Optional local PaddleOCR adapter.

    It intentionally raises a clear domain exception until optional OCR
    dependencies have been installed from requirements-vision.txt.
    """

    def __init__(self, profile_id: object = "fast") -> None:
        bundled_models = bundled_ocr_model_cache_path()
        if bundled_models:
            os.environ["PADDLE_PDX_CACHE_HOME"] = bundled_models
        else:
            os.environ.setdefault("PADDLE_PDX_CACHE_HOME", ocr_model_cache_path())
        try:
            import cv2
            from paddleocr import PaddleOCR
        except ImportError as exc:  # pragma: no cover - runtime optionality
            raise ImageDimensionUnavailable from exc
        self._cv2 = cv2
        self.profile = ocr_profile(profile_id)
        # PaddleOCR enables oneDNN by default on CPU.  PaddlePaddle 3.3 can
        # fail on OCR model PIR attributes in that backend, so prefer the
        # standard CPU executor for reliable local dimension extraction.
        # These optional classifiers require extra model files and otherwise
        # make an offline runtime attempt a download. Rotated crop handling
        # below stays fully local and preserves source-image coordinates.
        self._ocr = PaddleOCR(
            text_detection_model_name=self.profile.detector_model,
            text_recognition_model_name=self.profile.recognizer_model,
            enable_mkldnn=False,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )

    def _detect_boxes(self, source: object) -> list[OcrTextBox]:
        raw = self._ocr.predict(source)
        boxes: list[OcrTextBox] = []
        for page in raw:
            payload = page.json if hasattr(page, "json") else page
            result = payload.get("res", payload) if isinstance(payload, dict) else {}
            texts = result.get("rec_texts", []) if isinstance(result, dict) else []
            scores = result.get("rec_scores", []) if isinstance(result, dict) else []
            polygons = result.get("rec_polys", []) if isinstance(result, dict) else []
            for text, score, polygon in zip(texts, scores, polygons):
                xs = [int(point[0]) for point in polygon]
                ys = [int(point[1]) for point in polygon]
                angle = None
                if len(polygon) >= 2:
                    delta_x = float(polygon[1][0]) - float(polygon[0][0])
                    delta_y = float(polygon[1][1]) - float(polygon[0][1])
                    if delta_x or delta_y:
                        angle = math.degrees(math.atan2(delta_y, delta_x))
                boxes.append(
                    OcrTextBox(
                        str(text),
                        float(score),
                        (min(xs), min(ys), max(xs), max(ys)),
                        None,
                        angle,
                    )
                )
        return boxes

    def _rotated_boxes(
        self, image: object, *, fast_fallback: bool = False
    ) -> list[OcrTextBox]:
        image_height, image_width = image.shape[:2]
        profile_id = str(getattr(getattr(self, "profile", None), "id", ""))
        rotations: list[tuple[str, object]] = []
        clockwise = getattr(self._cv2, "ROTATE_90_CLOCKWISE", None)
        counterclockwise = getattr(self._cv2, "ROTATE_90_COUNTERCLOCKWISE", None)
        if profile_id == "fast" and fast_fallback:
            if clockwise is not None:
                rotations.append(("clockwise", clockwise))
            if counterclockwise is not None:
                rotations.append(("counterclockwise", counterclockwise))
        elif profile_id == "accurate" and image_height >= image_width * 1.35:
            # The exact model normally receives a narrow crop. Keep its
            # vertical-text correction off the fast-model critical path. The
            # optional orientation classifier is disabled for offline use, so
            # both rotations are needed to cover either reading direction.
            if clockwise is not None:
                rotations.append(("clockwise", clockwise))
            if counterclockwise is not None:
                rotations.append(("counterclockwise", counterclockwise))

        boxes: list[OcrTextBox] = []
        for rotation, cv2_rotation in rotations:
            try:
                rotated = self._cv2.rotate(image, cv2_rotation)
                detected = self._detect_boxes(rotated)
            except Exception:
                # A rotated in-memory input is optional. Keep the successful
                # original-image pass if one accelerator rejects that input.
                continue
            boxes.extend(
                rotate_ocr_box_to_source(
                    box,
                    rotation=rotation,
                    source_width=image_width,
                    source_height=image_height,
                )
                for box in detected
            )
        return boxes

    def detect(self, path: str) -> list[OcrTextBox]:  # pragma: no cover - optional runtime
        boxes = self._detect_boxes(path)
        image = self._cv2.imread(path)
        if image is None:
            return associate_dimension_hints(boxes, [])
        profile_id = str(getattr(getattr(self, "profile", None), "id", ""))
        if profile_id == "fast" and not _has_reliable_numeric_box(boxes):
            boxes.extend(self._rotated_boxes(image, fast_fallback=True))
        elif profile_id == "accurate":
            boxes.extend(self._rotated_boxes(image))
        boxes = [
            _retry_low_confidence_dimension_label(
                box, image, self._cv2, self._ocr.predict
            )
            for box in boxes
        ]
        refined_boxes: list[OcrTextBox] = []
        for box in boxes:
            number = _NUMBER_PATTERN.search(box.text)
            if number and len(number.group(0)) >= 2 and number.group(0).isdigit():
                text = _restore_lost_decimal_separator(
                    box.text,
                    _text_components_from_crop(image, box.bbox, self._cv2),
                )
                refined_boxes.append(replace(box, text=text))
            else:
                refined_boxes.append(box)
        boxes = refined_boxes
        gray = self._cv2.cvtColor(image, self._cv2.COLOR_BGR2GRAY)
        edges = self._cv2.Canny(gray, 50, 150)
        raw_lines = self._cv2.HoughLinesP(
            edges,
            1,
            math.pi / 180,
            45,
            minLineLength=30,
            maxLineGap=12,
        )
        lines = (
            [DimensionLine(*(int(value) for value in line[0])) for line in raw_lines]
            if raw_lines is not None
            else []
        )
        return associate_dimension_hints(boxes, lines)
