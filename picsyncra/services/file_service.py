"""File workflow helpers for slot processing."""

from __future__ import annotations

import os

from ..common import E, I
from ..excel_utils import slot_filename_label
from ..workflow_utils import build_remote_slot_filename, build_slot_filename, parse_slot_filename


def build_slot_target_filename(
    slots,
    idx,
    ean,
    name,
    type_value,
    model,
    color_values,
    extra_value,
    src_path,
    *,
    convert_tif_enabled=False,
    target_ext="",
):
    """Return the final output filename for a slot and source file."""

    if idx is I or idx < 0 or idx >= len(slots):
        return ""
    ext = os.path.splitext(src_path or "")[1]
    if not ext:
        return ""
    final_ext = ext
    if convert_tif_enabled and ext.lower() in {".tif", ".tiff"} and target_ext:
        final_ext = target_ext
    slot = slots[idx]
    return build_slot_filename(
        ean,
        slot["prefix"],
        slot_filename_label(slot),
        name,
        type_value,
        model,
        color_values,
        extra_value,
        final_ext,
    )


def build_expected_remote_filename(
    slots,
    idx,
    ean,
    src_path,
    *,
    convert_tif_enabled=False,
    target_ext="",
):
    """Return the canonical remote FTP name for a slot output."""

    if idx is I or idx < 0 or idx >= len(slots):
        return ""
    ext = os.path.splitext(src_path or "")[1]
    if not ext:
        return ""
    final_ext = ext
    if convert_tif_enabled and ext.lower() in {".tif", ".tiff"} and target_ext:
        final_ext = target_ext
    return build_remote_slot_filename(ean, slots[idx]["prefix"], final_ext)


def seed_metadata_migration(
    product_state,
    slots,
    processed_root,
    output_dir,
    ean,
    name,
    type_value,
    model,
    color_values,
    extra_value,
    *,
    convert_tif_enabled=False,
    target_ext="",
):
    """Prepare loaded files for a metadata correction without manual renaming."""

    seeded = 0
    for idx, slot in enumerate(slots):
        if (
            idx in product_state.pending_additions
            or idx in product_state.pending_deletions
            or idx in product_state.pending_ftp_deletions
        ):
            continue
        src_path = slot.get("filepath")
        if not src_path or not os.path.isfile(src_path):
            continue
        target_name = build_slot_target_filename(
            slots,
            idx,
            ean,
            name,
            type_value,
            model,
            color_values,
            extra_value,
            src_path,
            convert_tif_enabled=convert_tif_enabled,
            target_ext=target_ext,
        )
        if not target_name:
            continue
        target_path = os.path.join(output_dir, target_name)
        current_remote_name = str(product_state.ftp_presence.get(slot["prefix"]) or "").strip()
        expected_remote_name = build_expected_remote_filename(
            slots,
            idx,
            ean,
            src_path,
            convert_tif_enabled=convert_tif_enabled,
            target_ext=target_ext,
        )
        old_local_path = src_path if processed_root and src_path.startswith(processed_root) else None
        local_matches = False
        if old_local_path:
            try:
                local_matches = os.path.samefile(old_local_path, target_path)
            except E:
                local_matches = os.path.normcase(os.path.normpath(old_local_path)) == os.path.normcase(
                    os.path.normpath(target_path)
                )
        remote_matches = (
            current_remote_name == expected_remote_name
            if current_remote_name and expected_remote_name
            else False
        )
        if local_matches and remote_matches:
            continue
        product_state.pending_additions[idx] = src_path
        if old_local_path and not local_matches:
            product_state.pending_deletions[idx] = old_local_path
        seeded += 1
    return seeded


def infer_existing_remote_filename(product_state, slot_prefix):
    """Return the current short remote name for a slot when it can be inferred."""

    current_remote_name = str(product_state.ftp_presence.get(slot_prefix) or "").strip()
    if current_remote_name:
        return current_remote_name
    original_name = str(product_state.original_files.get(slot_prefix) or "").strip()
    if not original_name:
        return ""
    original_ext = os.path.splitext(original_name)[1].lower()
    parsed = parse_slot_filename(original_name)
    if not parsed or not parsed.ean:
        return ""
    return f"{parsed.ean}_{slot_prefix}{original_ext}"
