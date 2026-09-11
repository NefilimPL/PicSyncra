"""Shared product-record query types and in-memory fallback filtering."""

from __future__ import annotations

from dataclasses import dataclass

from picsyncra.excel_utils import (
    COLOR1_HEADER,
    COLOR2_HEADER,
    COLOR3_HEADER,
    EAN_HEADER,
    EXTRA_HEADER,
    MODEL_HEADER,
    NAME_HEADER,
    PRODUCT_ID_HEADER,
    TYPE_HEADER,
)


@dataclass(frozen=True)
class ProductSearchCriteria:
    """Exact-match fields accepted by product record lookups."""

    product_id: str = ""
    ean: str = ""
    name: str = ""
    type_name: str = ""
    model: str = ""
    query: str = ""


def _key(value: object) -> str:
    return str(value or "").strip().casefold()


def product_record_matches(record, criteria: ProductSearchCriteria) -> bool:
    """Return whether one record matches the shared product query semantics."""

    if criteria.product_id and _key(record.get(PRODUCT_ID_HEADER)) != _key(
        criteria.product_id
    ):
        return False
    if criteria.ean and _key(record.get(EAN_HEADER)) != _key(criteria.ean):
        return False
    if criteria.name and _key(record.get(NAME_HEADER)) != _key(criteria.name):
        return False
    if criteria.type_name and _key(record.get(TYPE_HEADER)) != _key(
        criteria.type_name
    ):
        return False
    if criteria.model and _key(record.get(MODEL_HEADER)) != _key(criteria.model):
        return False
    query_key = _key(criteria.query)
    if query_key and query_key not in " ".join(
        _key(record.get(header))
        for header in (
            PRODUCT_ID_HEADER,
            EAN_HEADER,
            NAME_HEADER,
            TYPE_HEADER,
            MODEL_HEADER,
            COLOR1_HEADER,
            COLOR2_HEADER,
            COLOR3_HEADER,
            EXTRA_HEADER,
        )
    ):
        return False
    return True


def filter_product_records(records, criteria: ProductSearchCriteria, limit: int):
    """Return bounded product matches while preserving record field shapes."""

    bounded_limit = max(1, min(int(limit), 100))
    result = []
    for record in records:
        if not product_record_matches(record, criteria):
            continue
        result.append(dict(record))
        if len(result) == bounded_limit:
            break
    return result
