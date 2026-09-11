"""Safe staging of uploads before they enter the image processing pipeline."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import time
import warnings
from collections.abc import Callable

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from ..path_security import (
    PathSecurityError,
    build_child_path,
    resolve_path_within_roots,
)

try:  # pragma: no cover - optional runtime dependency
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None


_CHUNK_SIZE = 1024 * 1024
JPEG_EXTENSIONS = {"jpg", "jpeg", "jfif", "jpe", "peg"}
PNG_EXTENSIONS = {"png", "apng"}
BMP_EXTENSIONS = {"bmp", "dib"}
TIFF_EXTENSIONS = {"tif", "tiff"}
AVIF_EXTENSIONS = {"avif", "avifs"}
HEIF_EXTENSIONS = {"heic", "heif", "hif"}
JPEG2000_EXTENSIONS = {"jp2", "j2k", "jpc", "jpx"}
PNM_EXTENSIONS = {"ppm", "pgm", "pbm", "pnm"}
IMAGE_EXTENSIONS = {
    *JPEG_EXTENSIONS,
    *PNG_EXTENSIONS,
    *BMP_EXTENSIONS,
    *TIFF_EXTENSIONS,
    *AVIF_EXTENSIONS,
    *JPEG2000_EXTENSIONS,
    *PNM_EXTENSIONS,
    "webp",
    "gif",
    "ico",
    "tga",
    "pcx",
    "psd",
}


def cleanup_job_directory(
    path: str,
    *,
    managed_root: str,
    active_paths: set[str] | None = None,
) -> bool:
    """Remove one inactive job directory only when it is directly under its root."""
    try:
        root = resolve_path_within_roots(managed_root, [managed_root])
        target = resolve_path_within_roots(path, [root])
        active = {
            Path(item).resolve(strict=False)
            for item in (active_paths or set())
            if item
        }
    except (OSError, RuntimeError, TypeError, PathSecurityError):
        return False
    if target.parent != root or target in active:
        return False
    if not target.exists():
        return True
    if not target.is_dir() or target.is_symlink():
        return False
    try:
        shutil.rmtree(target)
    except OSError:
        return False
    return not target.exists()


def cleanup_expired_job_directories(
    *,
    managed_root: str,
    prefix: str,
    max_age_seconds: float,
    active_paths: set[str] | None = None,
    now: float | None = None,
) -> int:
    """Remove inactive, expired direct children whose names use the job prefix."""
    try:
        root = Path(managed_root).resolve(strict=False)
        children = list(root.iterdir())
    except OSError:
        return 0
    cutoff = (time.time() if now is None else float(now)) - max(0.0, max_age_seconds)
    removed = 0
    for child in children:
        if not child.name.startswith(prefix):
            continue
        try:
            if child.stat().st_mtime >= cutoff:
                continue
        except OSError:
            continue
        if cleanup_job_directory(
            str(child),
            managed_root=str(root),
            active_paths=active_paths,
        ):
            removed += 1
    return removed


def upload_extension(filename: object) -> str:
    suffix = Path(str(filename or "")).suffix.strip().lower()
    if not suffix or len(suffix) > 12 or not suffix[1:].isalnum():
        return ""
    return suffix[1:]


def _is_iso_base_media_brand(header: bytes, allowed_brands: set[bytes]) -> bool:
    if len(header) < 16 or header[4:8] != b"ftyp":
        return False
    brands = {header[8:12]}
    compatible = header[16:64]
    brands.update(compatible[index : index + 4] for index in range(0, len(compatible) - 3, 4))
    return any(brand in allowed_brands for brand in brands)


def _is_dib_header(header: bytes) -> bool:
    if len(header) < 16:
        return False
    header_size = int.from_bytes(header[:4], "little", signed=False)
    if header_size not in {12, 40, 52, 56, 64, 108, 124}:
        return False
    if header_size == 12:
        width = int.from_bytes(header[4:6], "little", signed=False)
        height = int.from_bytes(header[6:8], "little", signed=False)
        planes = int.from_bytes(header[8:10], "little", signed=False)
        bit_count = int.from_bytes(header[10:12], "little", signed=False)
    else:
        width = int.from_bytes(header[4:8], "little", signed=True)
        height = int.from_bytes(header[8:12], "little", signed=True)
        planes = int.from_bytes(header[12:14], "little", signed=False)
        bit_count = int.from_bytes(header[14:16], "little", signed=False)
    return width != 0 and height != 0 and planes == 1 and bit_count in {1, 2, 4, 8, 16, 24, 32}


def _is_tga_header(header: bytes) -> bool:
    if len(header) < 18:
        return False
    return (
        header[1] in {0, 1}
        and header[2] in {1, 2, 3, 9, 10, 11}
        and int.from_bytes(header[12:14], "little", signed=False) > 0
        and int.from_bytes(header[14:16], "little", signed=False) > 0
        and header[16] in {8, 15, 16, 24, 32}
    )


def _is_pnm_header(header: bytes, extension: str) -> bool:
    if len(header) < 3 or header[:1] != b"P" or header[2:3] not in {b" ", b"\t", b"\r", b"\n"}:
        return False
    expected = {
        "pbm": {b"1", b"4"},
        "pgm": {b"2", b"5"},
        "ppm": {b"3", b"6"},
    }
    return header[1:2] in expected.get(extension, {b"1", b"2", b"3", b"4", b"5", b"6"})


def signature_matches(extension: str, header: bytes) -> bool:
    if extension in JPEG_EXTENSIONS:
        return header.startswith(b"\xff\xd8\xff")
    if extension in PNG_EXTENSIONS:
        return header.startswith(b"\x89PNG\r\n\x1a\n")
    if extension == "gif":
        return header.startswith((b"GIF87a", b"GIF89a"))
    if extension == "bmp":
        return header.startswith(b"BM")
    if extension == "dib":
        return _is_dib_header(header)
    if extension in TIFF_EXTENSIONS:
        return header.startswith((b"II*\x00", b"MM\x00*"))
    if extension == "webp":
        return len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP"
    if extension in AVIF_EXTENSIONS:
        return _is_iso_base_media_brand(header, {b"avif", b"avis"})
    if extension in HEIF_EXTENSIONS:
        return _is_iso_base_media_brand(
            header,
            {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"hevm", b"hevs", b"mif1", b"msf1"},
        )
    if extension in JPEG2000_EXTENSIONS:
        return header.startswith(b"\x00\x00\x00\x0cjP  \r\n\x87\n") or header.startswith(b"\xff\x4f\xff\x51")
    if extension in {"ico", "cur"}:
        kind = b"\x01" if extension == "ico" else b"\x02"
        return len(header) >= 6 and header.startswith(b"\x00\x00" + kind + b"\x00") and int.from_bytes(header[4:6], "little", signed=False) > 0
    if extension == "tga":
        return _is_tga_header(header)
    if extension in PNM_EXTENSIONS:
        return _is_pnm_header(header, extension)
    if extension == "pcx":
        return len(header) >= 4 and header[0] == 0x0A and header[1] in {0, 2, 3, 5} and header[2] == 1 and header[3] in {1, 2, 4, 8}
    if extension == "pdf":
        return header.startswith(b"%PDF-")
    if extension == "eps":
        return header.startswith(b"%!PS-Adobe-")
    if extension == "ai":
        return header.startswith((b"%PDF-", b"%!PS-Adobe-"))
    if extension == "psd":
        return header.startswith(b"8BPS")
    return False


def validate_upload_signature(path: str, filename: object) -> None:
    extension = upload_extension(filename)
    try:
        with open(path, "rb") as handle:
            header = handle.read(128)
    except OSError as exc:
        raise HTTPException(status_code=400, detail="Nie mozna odczytac wyslanego pliku.") from exc
    if not header:
        raise HTTPException(status_code=400, detail="Plik jest pusty.")
    if header.lstrip().lower().startswith((b"<html", b"<!doctype", b"<svg", b"<?xml")):
        raise HTTPException(
            status_code=400,
            detail="Zawartosc pliku wyglada jak HTML/XML/SVG, a nie dozwolony upload.",
        )
    if not signature_matches(extension, header):
        raise HTTPException(status_code=400, detail=f"Sygnatura pliku nie pasuje do rozszerzenia .{extension}.")


def validate_image_file(path: str, filename: object, max_pixels: int) -> tuple[int, int]:
    extension = upload_extension(filename)
    if extension not in IMAGE_EXTENSIONS:
        return 0, 0
    if Image is None:
        raise HTTPException(status_code=415, detail="Pillow nie jest dostepny do walidacji obrazu.")
    try:
        with warnings.catch_warnings():
            if hasattr(Image, "DecompressionBombWarning"):
                warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as image:
                width, height = int(image.size[0]), int(image.size[1])
                pixels = width * height
                if pixels > max_pixels:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Obraz ma {pixels} pikseli ({width}x{height}), limit uploadu to {max_pixels} pikseli.",
                    )
                image.verify()
                return width, height
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Nie mozna otworzyc pliku jako obrazu.") from exc


def scan_uploaded_file(
    path: str,
    *,
    enabled: bool,
    scanner_executable: str,
    timeout_seconds: int,
    process_runner: Callable[..., object] = subprocess.run,
    on_result: Callable[[dict[str, object]], None] | None = None,
) -> dict[str, object]:
    """Run Defender for one staged file without owning application scan history."""
    if not enabled:
        result = {"enabled": False, "scanned": False, "scanner": "", "elapsed_ms": 0}
        if on_result is not None:
            on_result(result)
        return result
    if not scanner_executable:
        raise HTTPException(
            status_code=503,
            detail="Skan antywirusowy uploadu jest wlaczony, ale nie znaleziono Microsoft Defender MpCmdRun.exe.",
        )

    started = time.perf_counter()
    try:
        completed = process_runner(
            [
                scanner_executable,
                "-Scan",
                "-ScanType",
                "3",
                "-File",
                os.path.abspath(path),
                "-DisableRemediation",
            ],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) if os.name == "nt" else 0,
        )
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=503, detail="Skan antywirusowy uploadu przekroczyl limit czasu.") from exc

    return_code = int(getattr(completed, "returncode"))
    result = {
        "enabled": True,
        "scanned": return_code == 0,
        "scanner": "Microsoft Defender",
        "return_code": return_code,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }
    if on_result is not None:
        on_result(result)
    if return_code != 0:
        output = "\n".join(
            part.strip()
            for part in (getattr(completed, "stdout", ""), getattr(completed, "stderr", ""))
            if str(part or "").strip()
        )
        details = output[-500:] if output else f"kod {return_code}"
        raise HTTPException(status_code=400, detail=f"Skan antywirusowy odrzucil upload ({details}).")
    return result


@dataclass(frozen=True)
class StagedUpload:
    path: str
    original_name: str
    detected_extension: str
    size_bytes: int
    width: int | None
    height: int | None


class UploadSizeLimitExceeded(ValueError):
    """Signals a streaming size limit breach to the HTTP adapter."""

    def __init__(self, size_bytes: int, max_bytes: int) -> None:
        super().__init__("upload exceeds the configured size limit")
        self.size_bytes = size_bytes
        self.max_bytes = max_bytes


class UploadStagingService:
    """Streams an upload to an internal location and runs blocking checks off-loop."""

    def __init__(
        self,
        *,
        max_bytes: int = 50 * 1024 * 1024,
        max_pixels: int = 25_000_000,
        validate_image: Callable[[str, object, int], tuple[int, int]] | None = None,
        scan_file: Callable[[str], object] | None = None,
    ) -> None:
        self._max_bytes = max_bytes
        self._max_pixels = max_pixels
        self._validate_image = validate_image
        self._scan_file = scan_file

    async def stage(
        self,
        upload: UploadFile,
        job_dir: str,
        prefix: str,
        *,
        managed_root: str | None = None,
    ) -> StagedUpload:
        original_name = os.path.basename(str(upload.filename or f"{prefix}.upload"))
        suffix = Path(original_name).suffix.lower()
        safe_prefix = "".join(
            character if character.isalnum() or character in "-_" else "_"
            for character in str(prefix)
        ).strip("._") or "upload"
        if managed_root is not None:
            job_path = resolve_path_within_roots(job_dir, [managed_root])
        else:
            job_path = resolve_path_within_roots(job_dir, [job_dir])
        target_path = os.fspath(
            build_child_path(job_path, f"{safe_prefix}_{secrets.token_hex(8)}{suffix}")
        )
        size_bytes = 0

        try:
            await run_in_threadpool(os.makedirs, job_path, exist_ok=True)
            with open(target_path, "wb") as handle:
                while True:
                    chunk = await upload.read(_CHUNK_SIZE)
                    if not chunk:
                        break
                    size_bytes += len(chunk)
                    if size_bytes > self._max_bytes:
                        raise UploadSizeLimitExceeded(size_bytes, self._max_bytes)
                    await run_in_threadpool(handle.write, chunk)

            width: int | None = None
            height: int | None = None
            if self._validate_image is not None:
                width, height = await run_in_threadpool(
                    self._validate_image,
                    target_path,
                    original_name,
                    self._max_pixels,
                )
            if self._scan_file is not None:
                await run_in_threadpool(self._scan_file, target_path)

            return StagedUpload(
                path=target_path,
                original_name=original_name,
                detected_extension=suffix.lstrip("."),
                size_bytes=size_bytes,
                width=width,
                height=height,
            )
        except Exception:
            if os.path.exists(target_path):
                try:
                    os.remove(target_path)
                except OSError:
                    pass
            raise
        finally:
            await upload.close()
