"""Web upload workflow shared by the local LAN backend."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import os
import shutil
import time
from typing import Sequence

from .common import (
    AUTO_CONTENT_FIT_KEY,
    ELEMENT_PIC,
    NON_PIC,
    OPEN_FURNITURE,
    PROCESSING_SETTINGS_KEY,
    SLOT_DEFS_KEY,
)
from .image_utils import fit_image_to_content
from .image_pipeline import ImagePipelineOptions, process_image
from .product_fields import (
    effective_product_values,
    missing_required_fields,
    normalize_product_fields,
)
from .slot_utils import normalize_slot_definitions
from .workflow_utils import (
    NO_EAN_PLACEHOLDER,
    NO_EXTRA_PLACEHOLDER,
    build_product_directory,
    build_slot_filename,
    normalize_color_slots,
    normalize_extra_segment,
)

try:  # pragma: no cover - optional runtime dependency
    from PIL import Image
except Exception:  # pragma: no cover - handled when image processing is requested
    Image = None


IMAGE_EXTENSIONS = {
    ".apng",
    ".avif",
    ".avifs",
    ".bmp",
    ".cur",
    ".dib",
    ".gif",
    ".heic",
    ".heif",
    ".hif",
    ".ico",
    ".j2k",
    ".jpc",
    ".jpg",
    ".jpeg",
    ".jp2",
    ".jpx",
    ".pbm",
    ".pcx",
    ".pgm",
    ".png",
    ".pnm",
    ".ppm",
    ".tga",
    ".tif",
    ".tiff",
    ".webp",
}
IMAGE_EXTENSION_ALIASES = {
    ".jfif": ".jpg",
    ".jpe": ".jpg",
    ".jpeg": ".jpg",
    ".peg": ".jpg",
}
ALLOWED_DOCUMENT_EXTENSIONS = {".ai", ".eps", ".pdf", ".psd"}

CONVERT_FORMATS = {
    "JPG": ("JPEG", ".jpg"),
    "JPEG": ("JPEG", ".jpg"),
    "PNG": ("PNG", ".png"),
    "WEBP": ("WEBP", ".webp"),
    "BMP": ("BMP", ".bmp"),
    "GIF": ("GIF", ".gif"),
    "TIFF": ("TIFF", ".tif"),
    "TIF": ("TIFF", ".tif"),
}


def available_convert_formats() -> list[str]:
    if Image is None:
        return ["JPG", "PNG", "BMP", "GIF"]
    try:
        Image.init()
        writable = set(getattr(Image, "SAVE", {}).keys())
    except Exception:
        writable = set()
    choices = []
    for label, (pil_format, _extension) in CONVERT_FORMATS.items():
        display = "JPG" if label == "JPEG" else label
        if display in choices or display == "TIF":
            continue
        if not writable or pil_format in writable:
            choices.append(display)
    return choices or ["JPG", "PNG", "BMP", "GIF"]


@dataclass(frozen=True)
class WebProductForm:
    """Product data submitted from the browser."""

    name: str
    type_name: str
    model: str
    color1: str
    color2: str = ""
    color3: str = ""
    extra: str = ""
    ean: str = ""
    product_id: str = ""


@dataclass(frozen=True)
class WebUploadedSlot:
    """Uploaded file assigned to a configured photo slot."""

    prefix: str
    label: str
    source_path: str
    original_filename: str = ""
    filename_label: str = ""
    content_fit: bool | None = None
    preprocessed: bool = False


@dataclass(frozen=True)
class WebProcessingOptions:
    """Image processing options for the web workflow."""

    resize_enabled: bool = True
    max_dim: int = 2000
    compress_enabled: bool = False
    compress_quality: int = 85
    max_size_enabled: bool = False
    max_file_kb: int = 500
    convert_enabled: bool = False
    target_format: str = "PNG"
    auto_content_fit: bool = False


@dataclass(frozen=True)
class WebProcessedFile:
    """Single file saved by the web workflow."""

    prefix: str
    label: str
    filename_label: str
    source_name: str
    filename: str
    path: str
    size_bytes: int
    source_size_bytes: int = 0
    elapsed_ms: int = 0
    operation: str = ""
    preprocessed: bool = False
    content_fit: bool = False


@dataclass(frozen=True)
class WebProcessingResult:
    """Summary returned to the web API after processing uploads."""

    output_dir: str
    ean: str
    saved_files: list[WebProcessedFile]
    skipped_slots: list[str]


def _clean(value: object) -> str:
    return str(value or "").strip()


def _slot_category(label: str) -> str:
    """Return the filename category used by the desktop workflow."""

    base = _clean(label).rstrip("0123456789")
    if base.startswith("LED_"):
        base = base[4:]
    lowered = base.lower()
    if "assembly_instruction" in lowered:
        return "ASSEMBLY"
    if "technical_drawing" in lowered:
        return "TECHNICAL"
    if "mood_pic" in lowered:
        return "MOOD"
    if "wb_pic" in lowered:
        return "WB"
    if "detail_pic" in lowered:
        return "DETAIL"
    if ELEMENT_PIC in lowered:
        return "ELEMENT"
    if OPEN_FURNITURE in lowered:
        return "OPEN-FURNITURE"
    if "no_ean" in lowered:
        return "NO-EAN"
    if NON_PIC in lowered:
        return "NON-PIC"
    return base.replace("_", "-").upper()


def _slot_filename_segment(label: str, filename_label: str = "") -> str:
    """Return the filename segment for a slot, preserving explicit web settings."""

    explicit = _clean(filename_label)
    if explicit:
        return explicit
    return _slot_category(label)


def slot_definitions_from_config(config_dict: dict) -> list[dict[str, str]]:
    """Return normalized slot definitions from a runtime config dict."""

    slots, _issues = normalize_slot_definitions(config_dict.get(SLOT_DEFS_KEY))
    return slots


def effective_product_form(
    form: WebProductForm,
    field_settings=None,
) -> WebProductForm:
    """Return a form with every disabled product value cleared."""

    values = effective_product_values(asdict(form), field_settings)
    return replace(
        form,
        **{key: values[key] for key in asdict(form) if key in values},
    )


def validate_product_form(form: WebProductForm, field_settings=None) -> list[str]:
    """Return validation errors for the browser product form."""

    settings = normalize_product_fields(field_settings)
    effective = effective_product_form(form, settings)
    errors = [
        f"Pole „{label}” jest wymagane."
        for _key, label in missing_required_fields(asdict(effective), settings)
    ]
    ean = _clean(effective.ean)
    if ean and ean != NO_EAN_PLACEHOLDER and (not ean.isdigit() or len(ean) != 13):
        errors.append("EAN musi miec 13 cyfr albo zostac pusty.")
    return errors


def normalized_product_payload(
    form: WebProductForm,
    field_settings=None,
) -> dict[str, object]:
    """Normalize product fields in the same direction as the desktop workflow."""

    form = effective_product_form(form, field_settings)
    colors = normalize_color_slots([form.color1, form.color2, form.color3])
    extra = normalize_extra_segment(form.extra, fallback=NO_EXTRA_PLACEHOLDER)
    ean = _clean(form.ean) or NO_EAN_PLACEHOLDER
    return {
        "name": _clean(form.name),
        "type_name": _clean(form.type_name),
        "model": _clean(form.model),
        "colors": colors,
        "extra": extra,
        "ean": ean,
    }


def _resample_filter():
    if Image is not None and hasattr(Image, "Resampling"):
        return Image.Resampling.LANCZOS
    return getattr(Image, "LANCZOS", getattr(Image, "BICUBIC", 3))


def _target_format_info(options: WebProcessingOptions) -> tuple[str, str]:
    target = str(options.target_format or "PNG").strip().upper()
    return CONVERT_FORMATS.get(target, CONVERT_FORMATS["PNG"])


def normalize_upload_extension(extension: str) -> str:
    """Return the canonical extension used for saved web uploads."""

    ext = (extension or "").strip().lower()
    if ext and not ext.startswith("."):
        ext = f".{ext}"
    return IMAGE_EXTENSION_ALIASES.get(ext, ext)


def is_supported_upload_extension(extension: str) -> bool:
    """Return True for image uploads and allowed document fallbacks."""

    ext = normalize_upload_extension(extension)
    return ext in IMAGE_EXTENSIONS or ext in ALLOWED_DOCUMENT_EXTENSIONS


def _output_extension(source_extension: str, options: WebProcessingOptions) -> str:
    source_extension = normalize_upload_extension(source_extension)
    if options.convert_enabled and Image is not None and source_extension in IMAGE_EXTENSIONS:
        return _target_format_info(options)[1]
    return source_extension


def _prepare_for_format(image, target_format: str):
    if target_format == "JPEG" and image.mode in ("RGBA", "LA", "P"):
        background = Image.new("RGB", image.size, (255, 255, 255))
        rgba = image.convert("RGBA")
        background.paste(rgba, (0, 0), rgba.getchannel("A"))
        return background
    if target_format in {"BMP", "GIF"} and image.mode in ("RGBA", "LA"):
        return image.convert("RGB")
    return image


def _save_image_with_options(image, target_path: str, target_format: str | None, options: WebProcessingOptions) -> None:
    save_params = {}
    suffix = os.path.splitext(target_path)[1].lower()
    if target_format == "JPEG" or suffix in {".jpg", ".jpeg"}:
        quality = max(1, min(100, int(options.compress_quality or 85)))
        save_params["quality"] = quality if options.compress_enabled else 95
        save_params["optimize"] = True
    elif target_format == "WEBP" or suffix == ".webp":
        quality = max(1, min(100, int(options.compress_quality or 85)))
        save_params["quality"] = quality if options.compress_enabled else 95
    elif target_format == "PNG" or suffix == ".png":
        save_params["optimize"] = True
    if target_format:
        image.save(target_path, format=target_format, **save_params)
    else:
        image.save(target_path, **save_params)

    if not options.max_size_enabled:
        return
    max_bytes = max(1, int(options.max_file_kb or 500)) * 1024
    if os.path.getsize(target_path) <= max_bytes:
        return
    if not (target_format == "JPEG" or suffix in {".jpg", ".jpeg", ".webp"}):
        return
    quality = int(save_params.get("quality", 95))
    while quality > 10 and os.path.getsize(target_path) > max_bytes:
        quality -= 5
        params = dict(save_params)
        params["quality"] = quality
        if target_format:
            image.save(target_path, format=target_format, **params)
        else:
            image.save(target_path, **params)


def _save_processed_file(
    source_path: str,
    target_path: str,
    options: WebProcessingOptions,
    *,
    content_fit: bool = False,
    already_processed: bool = False,
) -> str:
    """Copy or lightly process a browser-uploaded file to its target path."""

    if already_processed and not content_fit:
        shutil.copy2(source_path, target_path)
        return "copy_preprocessed"
    ext = normalize_upload_extension(os.path.splitext(source_path)[1])
    if ext not in IMAGE_EXTENSIONS:
        shutil.copy2(source_path, target_path)
        return "copy_document"
    if (
        not options.convert_enabled
        and ext not in {".jpg", ".jpeg", ".png", ".bmp", ".gif"}
        and not content_fit
    ):
        shutil.copy2(source_path, target_path)
        return "copy_unsupported_image"
    if Image is None:
        shutil.copy2(source_path, target_path)
        return "copy_no_pillow"

    target_format = None
    if options.convert_enabled:
        target_format, _target_ext = _target_format_info(options)
    max_dim = max(1, int(options.max_dim or 2000))
    max_dimensions = (max_dim, max_dim) if options.resize_enabled else (1_000_000, 1_000_000)
    process_image(
        source_path,
        target_path,
        ImagePipelineOptions(
            target_format=target_format,
            max_dimensions=max_dimensions,
            content_fit=content_fit,
            compress_enabled=options.compress_enabled,
            compress_quality=options.compress_quality,
            max_bytes=(max(1, int(options.max_file_kb or 500)) * 1024)
            if options.max_size_enabled
            else None,
        ),
    )
    return "process_image"


def process_web_uploads(
    *,
    base_output_dir: str,
    form: WebProductForm,
    uploaded_slots: Sequence[WebUploadedSlot],
    options: WebProcessingOptions | None = None,
    allow_empty: bool = False,
    field_settings=None,
) -> WebProcessingResult:
    """Save uploaded slot files into the product folder tree."""

    field_settings = normalize_product_fields(field_settings)
    form = effective_product_form(form, field_settings)
    errors = validate_product_form(form, field_settings)
    if errors:
        raise ValueError(" ".join(errors))
    if not uploaded_slots and not allow_empty:
        raise ValueError("Dodaj przynajmniej jeden plik do slotu.")

    payload = normalized_product_payload(form, field_settings)
    options = options or WebProcessingOptions()
    output_dir = build_product_directory(
        base_output_dir,
        payload["name"],
        payload["type_name"],
        payload["model"],
        payload["colors"],
        payload["extra"],
    )
    os.makedirs(output_dir, exist_ok=True)

    saved_files: list[WebProcessedFile] = []
    skipped_slots: list[str] = []
    for upload in uploaded_slots:
        source_path = _clean(upload.source_path)
        if not source_path or not os.path.isfile(source_path):
            skipped_slots.append(upload.prefix)
            continue
        ext = os.path.splitext(upload.original_filename or source_path)[1]
        if not ext:
            ext = os.path.splitext(source_path)[1]
        if not ext:
            skipped_slots.append(upload.prefix)
            continue
        if not is_supported_upload_extension(ext):
            source_name = os.path.basename(upload.original_filename or source_path)
            raise ValueError(
                f"Nieobslugiwany format pliku w slocie {upload.prefix}: {source_name}. "
                "Dozwolone sa pliki graficzne oraz PDF."
            )
        ext = _output_extension(ext, options)
        filename = build_slot_filename(
            payload["ean"],
            upload.prefix,
            _slot_filename_segment(upload.label, upload.filename_label),
            payload["name"],
            payload["type_name"],
            payload["model"],
            payload["colors"],
            payload["extra"],
            ext.lower(),
        )
        target_path = os.path.join(output_dir, filename)
        content_fit = (
            bool(upload.content_fit)
            if upload.content_fit is not None
            else bool(options.auto_content_fit)
        )
        try:
            same_target = os.path.samefile(source_path, target_path)
        except OSError:
            same_target = os.path.normcase(os.path.abspath(source_path)) == os.path.normcase(
                os.path.abspath(target_path)
            )
        try:
            source_size_bytes = os.path.getsize(source_path)
        except OSError:
            source_size_bytes = 0
        slot_started = time.perf_counter()
        operation = "same_target"
        if not same_target:
            operation = _save_processed_file(
                source_path,
                target_path,
                options,
                content_fit=content_fit,
                already_processed=bool(upload.preprocessed),
            )
        elapsed_ms = int(round((time.perf_counter() - slot_started) * 1000))
        saved_files.append(
            WebProcessedFile(
                prefix=upload.prefix,
                label=upload.label,
                filename_label=upload.filename_label or _slot_category(upload.label),
                source_name=os.path.basename(upload.original_filename or source_path),
                filename=filename,
                path=target_path,
                size_bytes=os.path.getsize(target_path),
                source_size_bytes=source_size_bytes,
                elapsed_ms=elapsed_ms,
                operation=operation,
                preprocessed=bool(upload.preprocessed),
                content_fit=content_fit,
            )
        )

    if not saved_files and not allow_empty:
        raise ValueError("Nie zapisano zadnego pliku.")
    return WebProcessingResult(
        output_dir=output_dir,
        ean=str(payload["ean"]),
        saved_files=saved_files,
        skipped_slots=skipped_slots,
    )


def _processing_changes_enabled(options: WebProcessingOptions) -> bool:
    return bool(
        options.resize_enabled
        or options.compress_enabled
        or options.max_size_enabled
        or options.convert_enabled
    )


def preprocess_cached_upload(
    source_path: str,
    original_filename: str,
    options: WebProcessingOptions | None = None,
) -> tuple[str, str, bool]:
    """Pre-process a cached browser upload and return path, display name and flag."""

    options = options or WebProcessingOptions()
    ext = os.path.splitext(original_filename or source_path)[1] or os.path.splitext(source_path)[1]
    ext = normalize_upload_extension(ext)
    if ext not in IMAGE_EXTENSIONS or Image is None or not _processing_changes_enabled(options):
        return source_path, os.path.basename(original_filename or source_path), False
    target_ext = _output_extension(ext, options)
    target_path = f"{os.path.splitext(source_path)[0]}_processed{target_ext}"
    _save_processed_file(source_path, target_path, options, content_fit=False)
    try:
        if os.path.abspath(target_path) != os.path.abspath(source_path):
            os.remove(source_path)
    except OSError:
        pass
    source_name = os.path.basename(original_filename or source_path)
    display_name = f"{os.path.splitext(source_name)[0]}{target_ext}"
    return target_path, display_name, True


def processing_options_from_config(config_dict: dict) -> WebProcessingOptions:
    """Build conservative web defaults from the existing runtime config."""

    processing = config_dict.get(PROCESSING_SETTINGS_KEY, {}) or {}
    return WebProcessingOptions(
        resize_enabled=bool(processing.get("resize_enabled", True)),
        max_dim=max(64, min(20000, int(processing.get("max_dim", 2000) or 2000))),
        compress_enabled=bool(processing.get("compress_enabled", False)),
        compress_quality=max(1, min(100, int(processing.get("compress_quality", 85) or 85))),
        max_size_enabled=bool(processing.get("max_size_enabled", False)),
        max_file_kb=max(1, min(102400, int(processing.get("max_file_kb", 500) or 500))),
        convert_enabled=bool(processing.get("convert_enabled", False)),
        target_format=str(processing.get("target_format", "PNG") or "PNG").upper(),
        auto_content_fit=bool(config_dict.get(AUTO_CONTENT_FIT_KEY, False)),
    )
