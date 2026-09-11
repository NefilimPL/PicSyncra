"""Excel-facing service helpers used by the GUI."""

from __future__ import annotations

import copy

from ..excel_utils import (
    COLOR1_HEADER,
    COLOR2_HEADER,
    COLOR3_HEADER,
    EAN_HEADER,
    ENTRY_RECORDS_KEY,
    EXTRA_HEADER,
    MODEL_HEADER,
    NAME_HEADER,
    PRODUCT_ID_HEADER,
    TYPE_HEADER,
)
from ..common import W


ENTRY_VALUE_HEADERS = (
    NAME_HEADER,
    TYPE_HEADER,
    MODEL_HEADER,
    COLOR1_HEADER,
    COLOR2_HEADER,
    COLOR3_HEADER,
    EXTRA_HEADER,
    PRODUCT_ID_HEADER,
)


def merge_saved_entry_into_lists(excel_lists, save_result):
    """Return a cache payload updated with the saved entry without reloading Excel."""

    if not isinstance(excel_lists, dict) or not isinstance(save_result, dict):
        return excel_lists
    entry = save_result.get("entry")
    if not isinstance(entry, dict):
        return excel_lists
    ean = str(entry.get(EAN_HEADER) or "").strip()
    if not ean:
        return excel_lists
    updated = copy.deepcopy(excel_lists)
    entries = updated.setdefault(W, {})
    if isinstance(entries, dict):
        entries[ean] = {header: entry.get(header, "") for header in ENTRY_VALUE_HEADERS}
    records = updated.setdefault(ENTRY_RECORDS_KEY, [])
    if isinstance(records, list):
        replacement = dict(entry)
        replacement[EAN_HEADER] = ean
        replaced = False
        product_id = str(replacement.get(PRODUCT_ID_HEADER) or "").strip().upper()
        for idx, record in enumerate(records):
            if not isinstance(record, dict):
                continue
            record_product_id = str(record.get(PRODUCT_ID_HEADER) or "").strip().upper()
            record_ean = str(record.get(EAN_HEADER) or "").strip().upper()
            if (product_id and product_id == record_product_id) or record_ean == ean.upper():
                records[idx] = replacement
                replaced = True
                break
        if not replaced:
            records.append(replacement)
    return updated
