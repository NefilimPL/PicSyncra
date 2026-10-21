"""Data-only contracts shared by the application and installation controller."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Channel = Literal["stable", "dev"]
Action = Literal["update", "downgrade", "install_ocr", "restart"]
OperationState = Literal[
    "idle",
    "downloading",
    "verified",
    "draining",
    "countdown",
    "stopping",
    "backing_up",
    "installing",
    "migrating",
    "validating",
    "committed",
    "rolling_back",
    "rolled_back",
    "recovery_required",
    "failed",
]


@dataclass(frozen=True)
class InstallContext:
    installation_id: str
    program_root: Path
    state_root: Path
    config_root: Path
    database_path: Path


@dataclass(frozen=True)
class ComponentRef:
    name: str
    component_id: str
    asset_name: str
    sha256: str
    size: int


@dataclass(frozen=True)
class ReleaseChoice:
    release_id: int
    tag: str
    commit: str
    channel: Channel
    source_branch: str
    manifest_sha256: str
    components: tuple[ComponentRef, ...]
    can_install: bool
    blocked_reason: str | None
    minimum_controller: int = 1


@dataclass(frozen=True)
class OperationRequest:
    request_id: str
    action: Action
    release_id: int | None
    restore_backup_id: str | None
    acknowledge_data_loss: bool


@dataclass(frozen=True)
class OperationSnapshot:
    operation_id: str
    state: OperationState
    action: Action
    target_release_id: int | None
    active_tasks: int
    queued_tasks: int
    other_users: int
    deadline_utc: str | None
    force_allowed: bool
    error_code: str | None


@dataclass(frozen=True)
class BackupReceipt:
    backup_id: str
    operation_id: str
    database_sha256: str
    config_sha256: str
    schema_version: int
    release_id: int
    verified: bool
