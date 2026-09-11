"""Conservative builder for standard parameterized photo SQL updates."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping


_IDENTIFIER_RE = re.compile(r"[0-9A-Za-z_\.]+\Z")
_STANDARD_TEMPLATE_RE = re.compile(
    r"\AUPDATE\s+\{table\}\s+SET\s+\{(?:col|column)\}\s*=\s*'\{filename\}'\s+\{where\}\s*;?\Z",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PhotoSqlBatch:
    query: str
    params: tuple[str, ...]


def _identifier(value: object) -> str:
    text = str(value or "").strip()
    return text if _IDENTIFIER_RE.fullmatch(text) else ""


def build_photo_sql_batch(
    table: object,
    where_clause: object,
    assignments: Mapping[object, object],
    db_type: object,
    template: object,
    *,
    allow_concrete_template: bool = False,
) -> PhotoSqlBatch | None:
    normalized_template = " ".join(str(template or "").strip().split())
    safe_table = _identifier(table)
    concrete_template_re = re.compile(
        rf"\AUPDATE\s+{re.escape(safe_table)}\s+SET\s+\{{(?:col|column)\}}\s*=\s*'\{{filename\}}'\s+WHERE\s+.+\{{ean\}}.+\Z",
        re.IGNORECASE,
    )
    if not safe_table or not (
        _STANDARD_TEMPLATE_RE.fullmatch(normalized_template)
        or (allow_concrete_template and concrete_template_re.fullmatch(normalized_template))
    ):
        return None
    ordered_assignments = [
        (_identifier(column), str(filename or ""))
        for column, filename in assignments.items()
    ]
    if not ordered_assignments or any(
        not column for column, _filename in ordered_assignments
    ):
        return None
    database_type = str(db_type or "").strip().casefold()
    placeholder = "?" if database_type == "mssql" else "%s" if database_type == "mysql" else ""
    if not placeholder:
        return None
    where = str(where_clause or "").strip()
    if not where:
        return None
    assignments_sql = ", ".join(
        f"{column} = {placeholder}" for column, _filename in ordered_assignments
    )
    return PhotoSqlBatch(
        query=f"UPDATE {safe_table} SET {assignments_sql} {where}",
        params=tuple(filename for _column, filename in ordered_assignments),
    )
