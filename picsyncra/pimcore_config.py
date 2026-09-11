from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

from .pimcore_templates import (
    PRODUCT_SOURCES,
    SourceDefinition,
    TemplateError,
    build_source_catalog,
    generate_test_values,
    placeholder_sources,
    parse_template,
    render_mapping_templates,
)

PIMCORE_SETTINGS_KEY = "pimcore"
PIMCORE_API_KEY = "api_key"
PIMCORE_FIELD_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SUPPORTED_ELEMENT_TYPES = {"input", "textarea", "numeric", "checkbox", "select"}
SUPPORTED_PARSERS = {"text", "integer", "decimal_comma", "boolean", "empty_to_null"}
SUPPORTED_FIELD_PARSERS = {
    "input": "text",
    "textarea": "text",
    "numeric": "decimal_comma",
    "checkbox": "boolean",
    "select": "text",
}
DEFAULT_PIMCORE_SETTINGS: dict[str, Any] = {
    "setup_complete": False,
    "enabled": False,
    "base_url": "",
    PIMCORE_API_KEY: "",
    "class_id": "",
    "class_name": "",
    "parent_id": "",
    "parent_path": "",
    "published": True,
    "object_key_template": "{EAN}",
    "existence_fields": ["EAN"],
    "timeout_seconds": 30,
    "verify_tls": True,
    "field_mappings": [],
    "export_columns": [],
}


def _text(value: object) -> str:
    return str(value or "").strip()


def _clean_layout_group(value: object) -> str:
    return _text(value).rstrip(":*").strip()


def _layout_order(value: object, default: int) -> int:
    try:
        if isinstance(value, bool):
            raise ValueError
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def default_pimcore_settings() -> dict[str, Any]:
    return deepcopy(DEFAULT_PIMCORE_SETTINGS)


def normalize_field_mapping(raw: object, *, default_order: int = 0) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    source = _text(raw.get("source"))
    target = _text(raw.get("pimcore_field"))
    if not source or not PIMCORE_FIELD_NAME.fullmatch(target):
        return None
    element_type = _text(raw.get("type")).lower() or "input"
    parser = _text(raw.get("parser")).lower() or "text"
    if element_type not in SUPPORTED_ELEMENT_TYPES:
        element_type = "input"
    if parser not in SUPPORTED_PARSERS:
        parser = "text"
    language = _text(raw.get("language")).lower() or None
    return {
        "source": source,
        "label": _text(raw.get("label")) or source,
        "pimcore_field": target,
        "type": element_type,
        "language": language,
        "required": bool(raw.get("required")),
        "default": _text(raw.get("default")),
        "parser": parser,
        "value_template": _text(raw.get("value_template")),
        "sql_query": _text(raw.get("sql_query")),
        "sql_profile_id": _text(raw.get("sql_profile_id")),
        "translate": bool(raw.get("translate")),
        "target_language": _text(raw.get("target_language")) or None,
        "ocr_validation": bool(raw.get("ocr_validation", False)),
        "layout_group": _clean_layout_group(raw.get("layout_group")),
        "layout_order": _layout_order(raw.get("layout_order"), default_order),
    }


def _default_export_columns(mappings: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {
            "type": "field",
            "pimcore_field": _text(item.get("pimcore_field")),
            "header": _text(item.get("pimcore_field")),
        }
        for item in mappings
        if _text(item.get("pimcore_field"))
    ]


def _normalize_export_columns(
    raw: object, mappings: list[dict[str, Any]]
) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    available_fields = {
        _text(item.get("pimcore_field")) for item in mappings if _text(item.get("pimcore_field"))
    }
    columns: list[dict[str, str]] = []
    used_fields: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        column_type = _text(item.get("type")).lower()
        header = _text(item.get("header"))
        if column_type == "blank":
            columns.append({"type": "blank", "header": header})
            continue
        if column_type != "field":
            continue
        pimcore_field = _text(item.get("pimcore_field"))
        if pimcore_field not in available_fields or pimcore_field in used_fields:
            continue
        columns.append(
            {
                "type": "field",
                "pimcore_field": pimcore_field,
                "header": header or pimcore_field,
            }
        )
        used_fields.add(pimcore_field)
    return columns


def infer_field_mapping(
    *,
    source: object,
    label: object,
    pimcore_field: object,
    field_type: object,
    language: object = None,
    required: bool = False,
) -> dict[str, Any]:
    source_text = _text(source)
    target = _text(pimcore_field)
    normalized_type = _text(field_type).lower()
    if not source_text or not PIMCORE_FIELD_NAME.fullmatch(target):
        raise ValueError("Pole formularza i pole Pimcore sa wymagane.")
    if normalized_type not in SUPPORTED_FIELD_PARSERS:
        raise ValueError(
            f"Nieobslugiwany typ pola Pimcore: {normalized_type or '[pusty]'}."
        )
    is_ean = source_text.casefold() == "ean"
    return {
        "source": "EAN" if is_ean else source_text,
        "label": _text(label) or source_text,
        "pimcore_field": target,
        "type": normalized_type,
        "language": _text(language).lower() or None,
        "required": True if is_ean else bool(required),
        "default": "",
        "parser": SUPPORTED_FIELD_PARSERS[normalized_type],
        "value_template": "",
        "sql_query": "",
        "sql_profile_id": "",
        "translate": False,
        "target_language": None,
        "ocr_validation": False,
        "layout_group": "",
        "layout_order": 0,
    }


def _legacy_setup_is_complete(settings: dict[str, Any]) -> bool:
    mappings = settings.get("field_mappings") or []
    ean_mapping = next(
        (
            item
            for item in mappings
            if str(item.get("source") or "").casefold() == "ean"
            and bool(item.get("required"))
        ),
        None,
    )
    return bool(
        settings.get("base_url")
        and settings.get(PIMCORE_API_KEY)
        and settings.get("class_name")
        and settings.get("parent_id")
        and ean_mapping
    )


def _template_uses_sql_source(template: object) -> bool:
    try:
        return any(source.casefold() == "sql" for source in placeholder_sources(template))
    except TemplateError:
        return False


def field_mapping_issues(
    raw_mappings: object,
    *,
    sql_profiles: object = None,
) -> list[str]:
    if not isinstance(raw_mappings, list):
        return ["Mapowanie pol musi byc lista."]
    parser_types = {
        "text": {"input", "textarea", "select"},
        "integer": {"numeric"},
        "decimal_comma": {"numeric"},
        "boolean": {"checkbox"},
        "empty_to_null": {"input", "textarea", "numeric", "select"},
    }
    issues: list[str] = []
    sources: set[str] = set()
    targets: set[tuple[str, str]] = set()
    sql_profile_ids: set[str] | None = None
    if isinstance(sql_profiles, list):
        sql_profile_ids = {
            _text(item.get("id"))
            for item in sql_profiles
            if isinstance(item, dict) and _text(item.get("id"))
        }
    for index, raw in enumerate(raw_mappings, start=1):
        if not isinstance(raw, dict):
            issues.append(f"Mapowanie {index}: niepoprawny format wiersza.")
            continue
        source = _text(raw.get("source"))
        target = _text(raw.get("pimcore_field"))
        language = _text(raw.get("language")).lower()
        element_type = _text(raw.get("type")).lower() or "input"
        parser = _text(raw.get("parser")).lower() or "text"
        template = _text(raw.get("value_template"))
        is_sql_mode = template.casefold() == "sql"
        uses_sql_source = not is_sql_mode and _template_uses_sql_source(template)
        translate = bool(raw.get("translate"))
        target_language = _text(raw.get("target_language"))
        if not source:
            issues.append(f"Mapowanie {index}: brak kolumny zrodlowej.")
        elif source in sources:
            issues.append(f"Mapowanie {index}: zduplikowana kolumna zrodlowa {source}.")
        if not PIMCORE_FIELD_NAME.fullmatch(target):
            issues.append(
                f"Mapowanie {index}: niepoprawne pole Pimcore {target or '[puste]'}."
            )
        elif (target, language) in targets:
            suffix = f" ({language})" if language else ""
            issues.append(f"Mapowanie {index}: zduplikowane pole Pimcore {target}{suffix}.")
        if element_type not in SUPPORTED_ELEMENT_TYPES:
            issues.append(f"Mapowanie {index}: nieobslugiwany typ {element_type}.")
        if parser not in SUPPORTED_PARSERS:
            issues.append(f"Mapowanie {index}: nieobslugiwany parser {parser}.")
        elif element_type in SUPPORTED_ELEMENT_TYPES and element_type not in parser_types[parser]:
            issues.append(
                f"Mapowanie {index}: parser {parser} nie pasuje do typu {element_type}."
            )
        if template and element_type not in {"input", "textarea", "select"}:
            issues.append(f"Mapowanie {index}: szablon wymaga pola tekstowego.")
        if is_sql_mode or uses_sql_source:
            sql_query = _text(raw.get("sql_query"))
            profile_id = _text(raw.get("sql_profile_id"))
            if not sql_query:
                issues.append(f"Mapowanie {index}: SQL wymaga zapytania.")
            if not profile_id:
                issues.append(f"Mapowanie {index}: wybierz profil SQL.")
            elif sql_profile_ids is not None and profile_id not in sql_profile_ids:
                issues.append(f"Mapowanie {index}: nieznany profil SQL {profile_id}.")
        if translate and not template:
            issues.append(
                f"Mapowanie {index}: tlumaczenie wymaga szablonu wartosci."
            )
        if translate and not target_language:
            issues.append(
                f"Mapowanie {index}: wybierz jezyk docelowy tlumaczenia."
            )
        if source:
            sources.add(source)
        if PIMCORE_FIELD_NAME.fullmatch(target):
            targets.add((target, language))
    try:
        template_mappings = [
            {
                **raw,
                "value_template": ""
                if isinstance(raw, dict)
                and _text(raw.get("value_template")).casefold() == "sql"
                else raw.get("value_template", ""),
            }
            if isinstance(raw, dict)
            else raw
            for raw in raw_mappings
        ]
        sql_template_source = SourceDefinition("SQL", "SQL", "sql", ("SQL",))
        catalog = build_source_catalog(template_mappings, [sql_template_source])
        for index, raw in enumerate(raw_mappings, start=1):
            if not isinstance(raw, dict):
                continue
            template = _text(raw.get("value_template"))
            if not template or template.casefold() == "sql":
                continue
            parse_template(template)
            for source in placeholder_sources(template):
                catalog.resolve(source)
        render_mapping_templates(
            template_mappings,
            product_values={key: "1" for key in PRODUCT_SOURCES},
            pimcore_values=generate_test_values(template_mappings),
            extra_sources=[sql_template_source],
            extra_values={"SQL": "1"},
        )
    except TemplateError as exc:
        issues.append(f"Mapowanie {index}: {exc.message}")
    return issues


def normalize_pimcore_settings(raw: object) -> dict[str, Any]:
    settings = default_pimcore_settings()
    source = raw if isinstance(raw, dict) else {}
    settings["enabled"] = bool(source.get("enabled", settings["enabled"]))
    raw_base_url = _text(source.get("base_url", settings["base_url"])).rstrip("/")
    settings["base_url"] = raw_base_url
    settings[PIMCORE_API_KEY] = _text(source.get(PIMCORE_API_KEY))
    settings["class_id"] = _text(source.get("class_id"))
    settings["class_name"] = _text(source.get("class_name", settings["class_name"]))
    settings["parent_id"] = _text(source.get("parent_id"))
    settings["parent_path"] = _text(source.get("parent_path"))
    settings["published"] = bool(source.get("published", settings["published"]))
    settings["object_key_template"] = "{EAN}"
    fields: list[str] = []
    raw_fields = source.get("existence_fields", settings["existence_fields"])
    if isinstance(raw_fields, str):
        raw_fields = raw_fields.split(",")
    if not isinstance(raw_fields, list):
        raw_fields = settings["existence_fields"]
    for item in raw_fields:
        name = _text(item)
        if PIMCORE_FIELD_NAME.fullmatch(name) and name not in fields:
            fields.append(name)
    settings["existence_fields"] = fields or ["EAN"]
    try:
        timeout = int(source.get("timeout_seconds", settings["timeout_seconds"]))
    except (TypeError, ValueError):
        timeout = 30
    settings["timeout_seconds"] = max(1, min(120, timeout))
    settings["verify_tls"] = bool(source.get("verify_tls", settings["verify_tls"]))
    mappings: list[dict[str, Any]] = []
    for index, item in enumerate(source.get("field_mappings", [])):
        normalized = normalize_field_mapping(item, default_order=index)
        if normalized:
            mappings.append(normalized)
    settings["field_mappings"] = mappings
    export_columns = _normalize_export_columns(source.get("export_columns"), mappings)
    settings["export_columns"] = export_columns or _default_export_columns(mappings)
    ean_targets = [
        item["pimcore_field"]
        for item in mappings
        if item["source"].casefold() == "ean"
    ]
    settings["existence_fields"] = ean_targets or fields or ["EAN"]
    if "setup_complete" in source:
        settings["setup_complete"] = bool(source.get("setup_complete"))
    else:
        settings["setup_complete"] = _legacy_setup_is_complete(settings)
    return settings


def parse_mapping_value(value: object, parser: str) -> object:
    text = _text(value)
    if parser == "integer":
        return int(text)
    if parser == "decimal_comma":
        return float(text.replace(" ", "").replace(",", "."))
    if parser == "boolean":
        lowered = text.casefold()
        if lowered in {"1", "true", "yes", "tak"}:
            return True
        if lowered in {"0", "false", "no", "nie"}:
            return False
        raise ValueError(f"Niepoprawna wartosc logiczna: {text}")
    if parser == "empty_to_null":
        return text or None
    return text
