"""SQL value lookups for Pimcore placeholder mappings."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import re

from ..common import E, K, M, N, b, c, mysql, pyodbc
from ..pimcore_templates import TemplateError, build_source_catalog, render_template
from ..settings import BW
from ..workflow_utils import normalize_sql_value

MAX_SQL_VALUE_QUERY_LENGTH = 8000
UNSAFE_SQL_RE = re.compile(
    r"\b(insert|update|delete|merge|drop|alter|truncate|exec|execute|call|create|grant|revoke)\b",
    re.I,
)
PLACEHOLDER_RE = re.compile(r"\{([^{}]+)\}")
SQL_PARAMETER_PLACEHOLDER_RE = re.compile(r"(?:N)?'\{([^{}]+)\}'|\{([^{}]+)\}", re.I)


class SqlValueError(ValueError):
    """Raised when a Pimcore SQL value lookup cannot be validated or executed."""


@dataclass(frozen=True)
class SqlValueResult:
    value: str
    warnings: list[dict[str, str]]


def _text(value: object) -> str:
    return str(value or "").strip()


def _lookup(mapping: dict[str, object], key: str) -> object:
    if key in mapping:
        return mapping[key]
    folded = key.casefold()
    for item_key, value in mapping.items():
        if str(item_key).casefold() == folded:
            return value
    return ""


def _strip_sql_comments(query: str) -> str:
    query = re.sub(r"/\*.*?\*/", " ", query, flags=re.S)
    return re.sub(r"--[^\r\n]*", " ", query)


def validate_sql_value_query(query: object) -> str:
    """Return a sanitized single SELECT query or raise ``SqlValueError``."""

    text = str(query or "").strip()
    if not text:
        raise SqlValueError("Zapytanie SQL jest wymagane.")
    if len(text) > MAX_SQL_VALUE_QUERY_LENGTH:
        raise SqlValueError("Zapytanie SQL jest za dlugie.")
    without_comments = _strip_sql_comments(text).strip()
    if not re.match(r"(?is)^\s*select\b", without_comments):
        raise SqlValueError("Zapytanie SQL dla Pimcore musi zaczynac sie od SELECT.")
    if ";" in without_comments.rstrip(";"):
        raise SqlValueError("Zapytanie SQL dla Pimcore musi byc pojedynczym SELECT.")
    if UNSAFE_SQL_RE.search(without_comments):
        raise SqlValueError("Zapytanie SQL zawiera niedozwolona instrukcje.")
    return without_comments.rstrip("; \r\n\t")


def _placeholder_value(
    token: str,
    product_values: dict[str, object],
    pimcore_values: dict[str, object],
    mappings: Sequence[dict[str, object]] | None = None,
) -> str:
    key = _text(token)
    raw_source = key.split("|", 1)[0].strip()
    catalog_rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in mappings or ():
        if not isinstance(item, dict):
            continue
        source = _text(item.get("source"))
        if not source or source in seen:
            continue
        catalog_rows.append(
            {
                "source": source,
                "label": _text(item.get("label")) or source,
            }
        )
        seen.add(source)
    for source in pimcore_values:
        source_text = _text(source)
        if source_text and source_text not in seen:
            catalog_rows.append({"source": source_text, "label": source_text})
            seen.add(source_text)
    catalog = build_source_catalog(catalog_rows)

    def resolve(source: str) -> object:
        source_text = _text(source)
        folded = source_text.casefold()
        if folded == "ean":
            return _lookup(product_values, "ean") or _lookup(product_values, "EAN")
        if folded.startswith("product:"):
            product_key = source_text.split(":", 1)[1]
            if product_key == "type":
                return _lookup(product_values, "type") or _lookup(
                    product_values,
                    "type_name",
                )
            return _lookup(product_values, product_key)
        if folded.startswith("pimcore:"):
            return _lookup(pimcore_values, source_text.split(":", 1)[1])
        try:
            resolved = catalog.resolve(source_text)
        except TemplateError as exc:
            if exc.code != "unknown_source":
                raise
            return (
                _lookup(product_values, source_text)
                or _lookup(product_values, folded)
                or _lookup(pimcore_values, source_text)
            )
        if resolved.startswith("PRODUCT:"):
            product_key = resolved.split(":", 1)[1]
            if product_key == "type":
                return _lookup(product_values, "type") or _lookup(
                    product_values,
                    "type_name",
                )
            return _lookup(product_values, product_key)
        if resolved.startswith("PIMCORE:"):
            return _lookup(pimcore_values, resolved.split(":", 1)[1])
        return ""

    try:
        return render_template("{" + key + "}", resolve)
    except TemplateError as exc:
        raise SqlValueError(
            f"Niepoprawny placeholder SQL {raw_source or key}: {exc.message}"
        ) from exc


def bind_sql_value_query(
    query: object,
    product_values: dict[str, object],
    pimcore_values: dict[str, object],
    db_type: str,
    *,
    mappings: Sequence[dict[str, object]] | None = None,
) -> tuple[str, Sequence[str]]:
    """Bind supported ``{token}`` placeholders as DB parameters."""

    safe_query = validate_sql_value_query(query)
    marker = "%s" if str(db_type or K).casefold() == K else "?"
    params: list[str] = []

    def replace(match: re.Match[str]) -> str:
        token = match.group(1) or match.group(2) or ""
        params.append(
            _placeholder_value(
                token,
                product_values,
                pimcore_values,
                mappings,
            )
        )
        return marker

    return SQL_PARAMETER_PLACEHOLDER_RE.sub(replace, safe_query), tuple(params)


def connect_profile(profile: dict[str, object]):
    """Open a DB connection for a normalized SQL profile."""

    db_type = str(profile.get("type") or K).casefold()
    if db_type == K:
        return mysql.connector.connect(
            host=_text(profile.get("host")),
            user=_text(profile.get("user")),
            password=_text(profile.get("password")),
            database=_text(profile.get("database")),
            connection_timeout=5,
            use_pure=True,
        )

    server = _text(profile.get("host"))
    database = _text(profile.get("database"))
    user = _text(profile.get("user"))
    password = _text(profile.get("password"))
    extra = "Encrypt=yes;TrustServerCertificate=yes;Connection Timeout=5"
    last_exc = None
    for driver in BW:
        try:
            conn_str = (
                f"DRIVER={{{driver}}};SERVER={server};DATABASE={database};"
                f"UID={user};PWD={password};{extra}"
            )
            return pyodbc.connect(conn_str)
        except E as exc:
            last_exc = exc
    raise E(last_exc or "Brak dzialajacego sterownika ODBC do MSSQL.")


def execute_sql_value_query(
    profile: dict[str, object],
    query: object,
    product_values: dict[str, object],
    pimcore_values: dict[str, object],
    *,
    mappings: Sequence[dict[str, object]] | None = None,
    connection: object | None = None,
    connector: Callable[[dict[str, object]], object] = connect_profile,
) -> SqlValueResult:
    """Execute a SQL value lookup and return the first column of the first row."""

    bound_query, params = bind_sql_value_query(
        query,
        product_values,
        pimcore_values,
        str(profile.get("type") or K),
        mappings=mappings,
    )
    conn = connection
    owns_connection = connection is None
    cursor = None
    try:
        if conn is None:
            conn = connector(profile)
        cursor = conn.cursor()
        cursor.execute(bound_query, params)
        rows = cursor.fetchmany(2)
    except E as exc:
        raise SqlValueError(f"Nie mozna wykonac SQL: {exc}") from exc
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except E:
                pass
        if owns_connection and conn is not None:
            try:
                conn.close()
            except E:
                pass

    if not rows:
        return SqlValueResult(
            "",
            [{"code": "no_rows", "message": "SQL nie zwrocil wiersza."}],
        )

    first = rows[0]
    try:
        raw_value = first[0]
    except E:
        raw_value = first

    warnings = []
    if len(rows) > 1:
        warnings.append(
            {
                "code": "multiple_rows",
                "message": "SQL zwrocil wiele wierszy; uzyto pierwszego.",
            }
        )
    return SqlValueResult(normalize_sql_value(raw_value), warnings)
