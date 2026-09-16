"""Turn a selected release ID into one verified staged transaction executor."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from uuid import uuid4

from .contracts import InstallContext, OperationRequest, ReleaseChoice
from .downloads import download_selected_components
from .release_executor import StagedReleaseExecutor


class ReleaseSelectionError(RuntimeError):
    """The requested release cannot be safely prepared for installation."""


Catalog = Callable[[str], tuple[ReleaseChoice, ...]]
ReleaseRecord = Callable[[int], Mapping[str, object] | None]


class VerifiedReleaseOperationFactory:
    """Prepare only a release present in the signed selected-channel catalog."""

    def __init__(self, context: InstallContext, *, catalog: Catalog, release_record: ReleaseRecord) -> None:
        self._context = context
        self._catalog = catalog
        self._release_record = release_record

    def __call__(self, request: OperationRequest) -> StagedReleaseExecutor:
        if request.action not in {"update", "downgrade"} or request.release_id is None:
            raise ReleaseSelectionError("A release operation requires a selected release.")
        channel = self._channel()
        choice = next((item for item in self._catalog(channel) if item.release_id == request.release_id), None)
        if choice is None or not choice.can_install:
            raise ReleaseSelectionError("Selected release is not available in the signed channel catalog.")
        record = self._release_record(choice.release_id)
        if record is None:
            raise ReleaseSelectionError("Selected release record is unavailable.")
        staging = self._context.state_root / "staging" / f"{choice.release_id}-{uuid4().hex}"
        staged = download_selected_components(
            choice,
            record,
            staging,
            {component.name for component in choice.components if component.name != "ocr"},
        )
        return StagedReleaseExecutor(self._context, choice, staged)

    def _channel(self) -> str:
        settings = self._context.state_root / "installation-settings.json"
        try:
            import json
            payload = json.loads(settings.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return "stable"
        return "dev" if isinstance(payload, dict) and payload.get("channel") == "dev" else "stable"


__all__ = ["ReleaseSelectionError", "VerifiedReleaseOperationFactory"]
