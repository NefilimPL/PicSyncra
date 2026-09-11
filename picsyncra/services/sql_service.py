"""SQL workflow helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..common import (
    AI,
    E,
    I,
    K,
    M,
    N,
    P,
    Q,
    b,
    c,
    p,
    w,
)
from ..database import connect_db
from ..workflow_utils import (
    build_sql_presence_query,
    has_presence_value,
    normalize_sql_value,
    unique_columns,
)

SAFE_IDENTIFIER_RE = re.compile(r"^[0-9A-Za-z_\.]+$")
UPDATE_TABLE_RE = re.compile(
    r"update\s+(?:top\s+\(?\d+\)?\s+)?"
    r"(?:(?:low_priority|high_priority|ignore)\s+)*"
    r"([^\s]+)\s+set",
    flags=re.I | re.S,
)


@dataclass(frozen=True)
class ColumnDetectionQuery:
    """Description of the metadata query used to list SQL columns."""

    table_ref: str
    table_name: str
    schema: str
    query: str
    params: tuple[str, ...]
    preview: str


def _safe_identifier(value):
    text = str(value or "").strip()
    if not text or not SAFE_IDENTIFIER_RE.fullmatch(text):
        return ""
    return text


def _quote_sql_literal(value: str) -> str:
    return "'" + str(value or "").replace("'", "''") + "'"


def configured_sql_query(config_dict):
    return str(config_dict.get(w, "") or "").strip()


def sql_placeholder_metadata():
    return [
        {"token": "{ean}", "description": "Aktualny EAN produktu uzywany w WHERE."},
        {"token": "{filename}", "description": "Nazwa wygenerowanego pliku zdjecia."},
        {"token": "{col}", "description": "Kolumna SQL przypisana do slotu."},
        {"token": "{column}", "description": "Alias dla {col}."},
    ]


def extract_update_table_ref(template):
    """Return the raw table reference from an UPDATE statement."""

    if not template:
        return ""
    match = UPDATE_TABLE_RE.search(str(template))
    if not match:
        return ""
    return str(match.group(1)).strip().rstrip(";")


def normalize_table_ref(table_ref):
    """Return a sanitized dotted table reference."""

    if not table_ref:
        return ""
    cleaned = (
        str(table_ref)
        .replace("[", "")
        .replace("]", "")
        .replace("`", "")
        .replace('"', "")
        .strip()
    )
    parts = []
    for raw_part in cleaned.split("."):
        part = str(raw_part or "").strip()
        if not part:
            continue
        safe_part = _safe_identifier(part)
        if not safe_part:
            return ""
        parts.append(safe_part)
    if not parts:
        return ""
    return ".".join(parts)


def split_table_ref(table_ref):
    """Split a table reference into table name and optional schema."""

    normalized = normalize_table_ref(table_ref)
    if not normalized:
        return "", ""
    parts = [part for part in normalized.split(".") if part]
    if not parts:
        return "", ""
    table_name = parts[-1]
    schema = parts[-2] if len(parts) > 1 else ""
    return table_name, schema


def build_column_detection_query(template, db_type):
    """Build the query used to inspect available columns for the UPDATE target."""

    table_ref = normalize_table_ref(extract_update_table_ref(template))
    if not table_ref:
        return None
    table_name, schema = split_table_ref(table_ref)
    if not table_name:
        return None
    if str(db_type or K).lower() == K:
        if schema:
            query = (
                "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s "
                "ORDER BY ORDINAL_POSITION"
            )
            params = (schema, table_name)
            preview = (
                "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                f"WHERE TABLE_SCHEMA = {_quote_sql_literal(schema)} "
                f"AND TABLE_NAME = {_quote_sql_literal(table_name)} "
                "ORDER BY ORDINAL_POSITION"
            )
        else:
            query = (
                "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s "
                "ORDER BY ORDINAL_POSITION"
            )
            params = (table_name,)
            preview = (
                "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() "
                f"AND TABLE_NAME = {_quote_sql_literal(table_name)} "
                "ORDER BY ORDINAL_POSITION"
            )
    else:
        if schema:
            query = (
                "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? "
                "ORDER BY ORDINAL_POSITION"
            )
            params = (schema, table_name)
            preview = (
                "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                f"WHERE TABLE_SCHEMA = {_quote_sql_literal(schema)} "
                f"AND TABLE_NAME = {_quote_sql_literal(table_name)} "
                "ORDER BY ORDINAL_POSITION"
            )
        else:
            query = (
                "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_NAME = ? ORDER BY ORDINAL_POSITION"
            )
            params = (table_name,)
            preview = (
                "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                f"WHERE TABLE_NAME = {_quote_sql_literal(table_name)} "
                "ORDER BY ORDINAL_POSITION"
            )
    return ColumnDetectionQuery(
        table_ref=table_ref,
        table_name=table_name,
        schema=schema,
        query=query,
        params=params,
        preview=preview,
    )


def detect_available_columns(config_dict):
    """Detect available SQL columns for the configured UPDATE target."""

    template = configured_sql_query(config_dict)
    if not template:
        return {
            "ok": False,
            "columns": [],
            "table": "",
            "preview": "",
            "message": "Nie skonfigurowano zapytania SQL.",
        }
    db_type = str(config_dict.get(p, K) or K).lower()
    query_info = build_column_detection_query(template, db_type)
    if query_info is None:
        return {
            "ok": False,
            "columns": [],
            "table": "",
            "preview": "",
            "message": "Nie udalo sie odczytac tabeli z zapytania SQL.",
        }
    conn = None
    cur = None
    try:
        conn = connect_db()
        cur = conn.cursor()
        cur.execute(query_info.query, query_info.params)
        rows = cur.fetchall()
        columns = []
        seen = set()
        for row in rows or []:
            try:
                value = row[0]
            except E:
                value = row
            text = str(value or "").strip()
            key = text.lower()
            if not text or key in seen:
                continue
            columns.append(text)
            seen.add(key)
        return {
            "ok": True,
            "columns": columns,
            "table": query_info.table_ref,
            "preview": query_info.preview,
            "message": f"Wykryto {len(columns)} pol SQL dla tabeli {query_info.table_ref}.",
        }
    except E as exc:
        return {
            "ok": False,
            "columns": [],
            "table": query_info.table_ref,
            "preview": query_info.preview,
            "message": str(exc),
        }
    finally:
        if cur is not None:
            try:
                cur.close()
            except E:
                pass
        if conn is not None:
            try:
                conn.close()
            except E:
                pass


def should_check_presence(config_dict):
    """Return True when database credentials are configured for lookups."""

    db_type = config_dict.get(p, K).lower()
    if db_type == K:
        mysql_cfg = config_dict.get(K, {})
        return all(mysql_cfg.get(key) for key in (c, b, N))
    sql_cfg = config_dict.get(P, {})
    if not (sql_cfg.get(c) and sql_cfg.get(b)):
        return False
    user = sql_cfg.get(N)
    password = sql_cfg.get(M)
    if user or password:
        return bool(user and password)
    return True


def extract_presence_context(config_dict, ean):
    """Return the table name and WHERE clause used for SQL presence checks."""

    if not ean:
        return None
    template = configured_sql_query(config_dict)
    if not template:
        return None
    table = normalize_table_ref(extract_update_table_ref(template))
    if not table:
        return None
    where_match = re.search(r"(?is)\bwhere\b(.+)", template)
    if where_match:
        where_template = " WHERE" + where_match.group(1)
    else:
        where_template = " WHERE EAN = '{ean}' OR Towar_powiazany_z_SKU = '{ean}'"
    where_clause = where_template.replace("{ean}", str(ean)).replace("{EAN}", str(ean))
    where_clause = where_clause.rstrip(";\n\r\t ")
    if where_clause and not where_clause.startswith(" "):
        where_clause = " " + where_clause
    return table, where_clause


def query_presence_map(columns, table, where_clause, db_type):
    """Fetch SQL presence for all mapped columns, batching when possible."""

    presence_map, _value_map = query_presence_details(columns, table, where_clause, db_type)
    return presence_map


def query_presence_details(columns, table, where_clause, db_type):
    """Fetch SQL presence flags together with the raw SQL values."""

    presence_map = {prefix: I for prefix, _, _ in columns}
    value_map = {prefix: "" for prefix, _, _ in columns}
    ordered_columns = unique_columns(
        [_safe_identifier(column_name) for _, column_name, _ in columns if column_name]
    )
    if not ordered_columns or not table:
        return presence_map, value_map
    conn = None
    cur = None
    try:
        conn = connect_db()
        cur = conn.cursor()
        batch_failed = False
        query = build_sql_presence_query(
            table,
            where_clause,
            ordered_columns,
            db_type,
            mysql_key=K,
        )
        if query:
            try:
                cur.execute(query)
                row = cur.fetchone()
            except E:
                batch_failed = True
            else:
                if not row:
                    return presence_map, value_map
                try:
                    values = list(row)
                except E:
                    values = [row]
                column_value_map = {
                    column_name: values[idx] if idx < Q(values) else I
                    for idx, column_name in enumerate(ordered_columns)
                }
                for prefix, column_name, _ in columns:
                    safe_column = _safe_identifier(column_name)
                    if not safe_column:
                        continue
                    raw_value = column_value_map.get(safe_column)
                    presence_map[prefix] = has_presence_value(raw_value)
                    value_map[prefix] = normalize_sql_value(raw_value)
                return presence_map, value_map
        if not batch_failed:
            return presence_map, value_map
        for prefix, column_name, _ in columns:
            safe_column = _safe_identifier(column_name)
            if not safe_column:
                continue
            if db_type == K:
                query = f"SELECT {safe_column} FROM {table}{where_clause}".rstrip(";\n\r\t ")
                if " limit " not in query.lower():
                    query = f"{query} LIMIT 1"
            else:
                query = f"SELECT TOP 1 {safe_column} FROM {table}{where_clause}".rstrip(";\n\r\t ")
            try:
                cur.execute(query)
                row = cur.fetchone()
            except E:
                presence_map[prefix] = I
                continue
            if not row:
                continue
            try:
                value = row[0]
            except E:
                try:
                    row_values = list(row)
                except E:
                    row_values = [row]
                value = row_values[0] if row_values else I
            presence_map[prefix] = has_presence_value(value)
            value_map[prefix] = normalize_sql_value(value)
        return presence_map, value_map
    finally:
        if cur is not None:
            try:
                cur.close()
            except E:
                pass
        if conn is not None:
            try:
                conn.close()
            except E:
                pass
