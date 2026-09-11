"""Mutable product state model used by the GUI and worker snapshots."""

from __future__ import annotations

from dataclasses import dataclass, field
import copy


@dataclass
class ProductIdentity:
    name: str = ""
    type_name: str = ""
    model: str = ""
    color1: str = ""
    color2: str = ""
    color3: str = ""
    extra: str = ""
    ean: str = ""
    product_id: str = ""

    @property
    def colors(self) -> list[str]:
        return [self.color1, self.color2, self.color3]


@dataclass
class ProductState:
    identity: ProductIdentity = field(default_factory=ProductIdentity)
    original_files: dict[str, str] = field(default_factory=dict)
    pending_additions: dict[int, str] = field(default_factory=dict)
    pending_deletions: dict[int, str] = field(default_factory=dict)
    pending_ftp_deletions: dict[int, str] = field(default_factory=dict)
    ftp_remote_only: dict[str, dict[str, str]] = field(default_factory=dict)
    ftp_presence: dict[str, str] = field(default_factory=dict)
    ftp_preview_files: dict[str, dict[str, str]] = field(default_factory=dict)
    ftp_downloaded_final: set[str] = field(default_factory=set)
    sql_presence: dict[str, bool] | None = None
    sql_values: dict[str, str] = field(default_factory=dict)

    def clone(self) -> "ProductState":
        return copy.deepcopy(self)

    def reset_runtime(self) -> None:
        self.original_files.clear()
        self.pending_additions.clear()
        self.pending_deletions.clear()
        self.pending_ftp_deletions.clear()
        self.ftp_remote_only.clear()
        self.ftp_presence.clear()
        self.ftp_preview_files.clear()
        self.ftp_downloaded_final.clear()
        self.sql_presence = None
        self.sql_values.clear()


def merge_lookup_state(
    current_state: ProductState | None,
    lookup_state: ProductState | None,
    slot_prefix_by_index: dict[int, str],
) -> ProductState | None:
    """Merge async lookup data while preserving live unsaved slot edits."""

    if not isinstance(lookup_state, ProductState):
        return lookup_state
    if not isinstance(current_state, ProductState):
        return lookup_state.clone()
    merged = lookup_state.clone()
    merged.pending_additions = dict(current_state.pending_additions)
    merged.pending_deletions = dict(current_state.pending_deletions)
    merged.pending_ftp_deletions = dict(current_state.pending_ftp_deletions)
    dirty_slots = (
        set(merged.pending_additions)
        | set(merged.pending_deletions)
        | set(merged.pending_ftp_deletions)
    )
    for idx in dirty_slots:
        slot_prefix = slot_prefix_by_index.get(idx)
        if not slot_prefix:
            continue
        if (
            slot_prefix not in merged.original_files
            and slot_prefix in current_state.original_files
        ):
            merged.original_files[slot_prefix] = current_state.original_files[slot_prefix]
        if (
            slot_prefix not in merged.ftp_presence
            and slot_prefix in current_state.ftp_presence
        ):
            merged.ftp_presence[slot_prefix] = current_state.ftp_presence[slot_prefix]
        if slot_prefix not in merged.sql_values and slot_prefix in current_state.sql_values:
            merged.sql_values[slot_prefix] = current_state.sql_values[slot_prefix]
        if idx in merged.pending_ftp_deletions and idx not in merged.pending_additions:
            merged.ftp_remote_only.pop(slot_prefix, None)
            merged.ftp_preview_files.pop(slot_prefix, None)
            continue
        preview_info = merged.ftp_preview_files.get(slot_prefix)
        if preview_info is None:
            preview_info = merged.ftp_remote_only.get(slot_prefix)
        if preview_info is None:
            preview_info = current_state.ftp_preview_files.get(slot_prefix)
        if preview_info is None:
            preview_info = current_state.ftp_remote_only.get(slot_prefix)
        if preview_info is not None:
            merged.ftp_preview_files[slot_prefix] = copy.deepcopy(preview_info)
        merged.ftp_remote_only.pop(slot_prefix, None)
    return merged
