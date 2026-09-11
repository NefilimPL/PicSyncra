"""In-memory form values staged for a queued web process job."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class QueuedUploadFile:
    path: str
    filename: str


@dataclass
class ProcessFormSnapshot:
    fields: dict[str, str] = field(default_factory=dict)
    uploads: dict[str, QueuedUploadFile] = field(default_factory=dict)
    temp_dir: str = ""

    def get(self, key: str, default: Any = None) -> Any:
        if key in self.uploads:
            return self.uploads[key]
        return self.fields.get(key, default)
