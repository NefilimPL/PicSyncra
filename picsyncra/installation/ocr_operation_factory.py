"""Prepare the optional OCR bundle from the signed release matching the install."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from uuid import uuid4

from .contracts import InstallContext, OperationRequest, ReleaseChoice
from .downloads import download_selected_components
from .ocr_executor import StagedOcrExecutor
from .update_helper import read_active_release


class OcrSelectionError(RuntimeError):
    """No signed OCR component is available for the active installed release."""


Catalog = Callable[[str], tuple[ReleaseChoice, ...]]
ReleaseRecord = Callable[[int], Mapping[str, object] | None]


class VerifiedOcrOperationFactory:
    """Prepare only an OCR component from the signed active-release catalog entry."""

    def __init__(self, context: InstallContext, *, catalog: Catalog, release_record: ReleaseRecord) -> None:
        self._context = context
        self._catalog = catalog
        self._release_record = release_record

    def __call__(self, request: OperationRequest) -> StagedOcrExecutor:
        if request.action != "install_ocr" or request.release_id is not None:
            raise OcrSelectionError("An OCR installation cannot select an arbitrary release.")
        active_release = read_active_release(self._context)
        choice = next((item for item in self._catalog(self._channel()) if item.release_id == active_release), None)
        if choice is None or not choice.can_install:
            raise OcrSelectionError("The active release is not available in the signed channel catalog.")
        component = next((item for item in choice.components if item.name == "ocr"), None)
        if component is None:
            raise OcrSelectionError("The signed active release has no optional OCR component.")
        record = self._release_record(choice.release_id)
        if record is None:
            raise OcrSelectionError("The active release record is unavailable.")
        staging = self._context.state_root / "staging" / f"ocr-{choice.release_id}-{uuid4().hex}"
        staged = download_selected_components(choice, record, staging, {"ocr"})
        return StagedOcrExecutor(self._context, choice, component, staged["ocr"])

    def _channel(self) -> str:
        settings = self._context.state_root / "installation-settings.json"
        try:
            payload = json.loads(settings.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return "stable"
        return "dev" if isinstance(payload, dict) and payload.get("channel") == "dev" else "stable"


__all__ = ["OcrSelectionError", "VerifiedOcrOperationFactory"]
