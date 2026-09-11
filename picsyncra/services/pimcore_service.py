from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
import hashlib
import json
import re
import ssl
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from ..common import SSL_CONTEXT
from ..history_changes import field_changes
from ..pimcore_config import (
    PIMCORE_API_KEY,
    PIMCORE_FIELD_NAME,
    SUPPORTED_FIELD_PARSERS,
    field_mapping_issues,
    normalize_pimcore_settings,
    parse_mapping_value,
)
from .pimcore_transport import (
    LegacyPimcoreTransport,
    PimcoreTransportNetworkError,
    RequestsPimcoreTransport,
)

LOCALIZED_FIELD_LANGUAGES = ("en", "pl")


@dataclass
class PimcoreApiError(Exception):
    message: str
    endpoint: str
    status_code: int | None = None
    response_excerpt: str = ""
    response_detail: str = ""
    kind: str = "request"

    def __str__(self) -> str:
        return self.message

    def as_dict(self, *, include_detail: bool = False) -> dict[str, object]:
        result = {
            "message": self.message,
            "endpoint": self.endpoint,
            "status_code": self.status_code,
            "response_excerpt": self.response_excerpt,
            "kind": self.kind,
        }
        if include_detail:
            result["response_detail"] = self.response_detail
        return result


@dataclass
class PimcoreConflictError(Exception):
    message: str
    object_id: int
    expected_marker: str
    current_marker: str

    def __str__(self) -> str:
        return self.message


def _response_excerpt(value: object, limit: int = 2000) -> str:
    return str(value or "").replace("\r", " ").replace("\n", " ")[:limit]


def _response_detail(value: object, secret: object = "") -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    secret_text = str(secret or "")
    return text.replace(secret_text, "[REDACTED]") if secret_text else text


def _default_opener(request: Request, timeout: int, context: ssl.SSLContext | None):
    return urlopen(request, timeout=timeout, context=context)


class PimcoreClient:
    def __init__(
        self,
        settings: object,
        *,
        opener: Callable[[Request, int, ssl.SSLContext | None], object] = _default_opener,
        session_factory: Callable[[], object] | None = None,
    ) -> None:
        self.settings = normalize_pimcore_settings(settings)
        self.base_url = self.settings["base_url"].rstrip("/")
        self.opener = opener
        context = None
        if self.base_url.lower().startswith("https://"):
            context = (
                SSL_CONTEXT
                if self.settings["verify_tls"]
                else ssl._create_unverified_context()
            )
        if opener is not _default_opener:
            self._session_factory = None
            self._transport = LegacyPimcoreTransport(opener, ssl_context=context)
        else:
            if session_factory is None:
                import requests

                session_factory = requests.Session
            self._session_factory = session_factory
            self._transport = self._new_requests_transport()
        self.last_response: dict[str, object] = {}

    def _new_requests_transport(self) -> RequestsPimcoreTransport:
        return RequestsPimcoreTransport(
            self._session_factory(),
            verify_tls=bool(self.settings["verify_tls"]),
        )

    def close(self) -> None:
        self._transport.close()

    def __enter__(self) -> "PimcoreClient":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self.close()
        return False

    def request_json(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, object] | None = None,
        body: dict[str, object] | None = None,
    ) -> dict[str, Any]:
        endpoint = f"{self.base_url}{path}"
        request_arguments = {
            "headers": {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-api-key": self.settings[PIMCORE_API_KEY],
            },
            "query": query,
            "body": body,
            "timeout": self.settings["timeout_seconds"],
        }
        normalized_method = method.upper()
        try:
            response = self._transport.request(
                normalized_method,
                endpoint,
                **request_arguments,
            )
        except PimcoreTransportNetworkError as original_error:
            network_error: BaseException | None = original_error
            if normalized_method == "GET" and self._session_factory is not None:
                self._transport.close()
                self._transport = self._new_requests_transport()
                try:
                    response = self._transport.request(
                        normalized_method,
                        endpoint,
                        **request_arguments,
                    )
                except PimcoreTransportNetworkError as retry_error:
                    network_error = retry_error
                else:
                    network_error = None
            if network_error is not None:
                detail = _response_detail(network_error, self.settings[PIMCORE_API_KEY])
                raise PimcoreApiError(
                    f"Nie mozna polaczyc sie z Pimcore: {network_error}",
                    path,
                    response_excerpt=_response_excerpt(detail),
                    response_detail=detail,
                    kind="network",
                ) from network_error
        except (URLError, TimeoutError, OSError) as exc:
            detail = _response_detail(exc, self.settings[PIMCORE_API_KEY])
            raise PimcoreApiError(
                f"Nie mozna polaczyc sie z Pimcore: {exc}",
                path,
                response_excerpt=_response_excerpt(detail),
                response_detail=detail,
                kind="network",
            ) from exc
        raw = response.text
        status = response.status_code
        if status < 200 or status >= 300:
            detail = _response_detail(raw, self.settings[PIMCORE_API_KEY])
            raise PimcoreApiError(
                f"Pimcore zwrocil HTTP {status}.",
                path,
                status_code=status,
                response_excerpt=_response_excerpt(detail),
                response_detail=detail,
                kind="http",
            )
        self.last_response = {
            "method": method.upper(),
            "endpoint": path,
            "status_code": status,
        }
        try:
            payload = json.loads(raw or "{}")
        except json.JSONDecodeError as exc:
            detail = _response_detail(raw, self.settings[PIMCORE_API_KEY])
            raise PimcoreApiError(
                "Pimcore zwrocil niepoprawny JSON.",
                path,
                status_code=status,
                response_excerpt=_response_excerpt(detail),
                response_detail=detail,
                kind="json",
            ) from exc
        if not isinstance(payload, dict):
            raise PimcoreApiError(
                "Pimcore zwrocil niepoprawny format danych.",
                path,
                status_code=status,
            )
        return payload

    def server_info(self) -> dict[str, Any]:
        return self.request_json("GET", "/webservice/rest/server-info")

    def classes(self) -> dict[str, Any]:
        return self.request_json("GET", "/webservice/rest/classes")

    def class_definition(self, class_id: object) -> dict[str, Any]:
        return self.request_json(
            "GET",
            f"/webservice/rest/class/id/{quote(str(class_id))}",
        )

    def object_by_id(self, object_id: object) -> dict[str, Any]:
        return self.request_json(
            "GET",
            f"/webservice/rest/object/id/{quote(str(object_id))}",
        )

    def object_list(
        self,
        query_filter: dict[str, object] | None = None,
        *,
        object_class: str = "",
        limit: int = 2,
        offset: int = 0,
    ) -> dict[str, Any]:
        query: dict[str, object] = {
            "limit": max(1, min(1000, int(limit))),
            "offset": max(0, int(offset)),
        }
        if query_filter:
            query["q"] = json.dumps(
                query_filter,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        if str(object_class or "").strip():
            query["objectClass"] = str(object_class).strip()
        return self.request_json("GET", "/webservice/rest/object-list", query=query)

    def create_object(self, payload: dict[str, object]) -> dict[str, Any]:
        return self.request_json("POST", "/webservice/rest/object", body=payload)

    def update_object(self, object_id: object, payload: dict[str, object]) -> dict[str, Any]:
        return self.request_json(
            "PUT",
            f"/webservice/rest/object/id/{quote(str(object_id))}",
            body=payload,
        )

    def delete_object(self, object_id: object) -> dict[str, Any]:
        return self.request_json(
            "DELETE",
            f"/webservice/rest/object/id/{quote(str(object_id))}",
        )


@contextmanager
def pimcore_client_scope(
    config: object,
    supplied: PimcoreClient | None = None,
    *,
    factory: Callable[[object], PimcoreClient] = PimcoreClient,
):
    """Yield a caller-owned client or close one created for this operation."""

    if supplied is not None:
        yield supplied
        return
    client = factory(config)
    try:
        yield client
    finally:
        client.close()


def validate_ean(ean: object) -> str:
    value = str(ean or "").strip()
    if not re.fullmatch(r"\d{13}", value):
        raise ValueError("EAN musi zawierac dokladnie 13 cyfr.")
    return value


def build_ean_filter(ean: object, field_names: list[str]) -> dict[str, object]:
    value = validate_ean(ean)
    fields: list[str] = []
    for field in field_names:
        name = str(field or "").strip()
        if not PIMCORE_FIELD_NAME.fullmatch(name):
            raise ValueError(f"Niepoprawna nazwa pola Pimcore: {name}")
        if name not in fields:
            fields.append(name)
    if not fields:
        raise ValueError("Brak pol do sprawdzania EAN.")
    clauses = [{name: value} for name in fields]
    return clauses[0] if len(clauses) == 1 else {"$or": clauses}


def _safe_object_key(value: object) -> str:
    key = re.sub(r"[^0-9A-Za-z_.-]+", "-", str(value or "").strip()).strip(".-")
    if not key:
        raise ValueError("Nie mozna zbudowac klucza obiektu Pimcore.")
    return key[:190]


def render_object_key(template: str, values: dict[str, object]) -> str:
    missing: list[str] = []

    def replace(match: re.Match[str]) -> str:
        source = match.group(1)
        value = str(values.get(source) or "").strip()
        if not value:
            missing.append(source)
        return value

    rendered = re.sub(r"\{([^{}]+)\}", replace, str(template or "{EAN}"))
    if missing:
        raise ValueError("Brak wartosci dla klucza: " + ", ".join(sorted(set(missing))))
    return _safe_object_key(rendered)


def _mapped_elements(
    config: dict[str, object],
    values: dict[str, object],
    *,
    use_defaults: bool,
    include_empty: bool = False,
    nest_localized: bool = False,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    errors: list[str] = []
    elements: list[dict[str, object]] = []
    localized: list[dict[str, object]] = []
    effective_values = dict(values or {})
    for mapping in config["field_mappings"]:
        source = mapping["source"]
        if source not in effective_values and not use_defaults:
            continue
        raw = effective_values.get(source)
        if (raw is None or str(raw).strip() == "") and use_defaults:
            raw = mapping["default"]
        if mapping["required"] and (raw is None or str(raw).strip() == ""):
            errors.append(f"Pole {mapping['label']} jest wymagane.")
            continue
        if (
            (raw is None or str(raw).strip() == "")
            and not include_empty
            and mapping["parser"] != "empty_to_null"
        ):
            continue
        try:
            parsed = parse_mapping_value(raw, mapping["parser"])
        except (TypeError, ValueError) as exc:
            errors.append(f"Pole {mapping['label']}: {exc}")
            continue
        effective_values[source] = parsed
        element = {
            "type": mapping["type"],
            "name": mapping["pimcore_field"],
            "value": parsed,
            "language": mapping["language"],
        }
        if nest_localized and str(mapping.get("language") or "").strip():
            localized.append(element)
        else:
            elements.append(element)
    if errors:
        raise ValueError(" ".join(errors))
    if localized:
        elements.append(
            {
                "type": "localizedfields",
                "name": "localizedfields",
                "value": localized,
            }
        )
    return elements, effective_values


def build_create_payload(
    settings: object,
    values: dict[str, object],
    *,
    published: bool | None = None,
    use_defaults: bool = True,
) -> dict[str, object]:
    config = normalize_pimcore_settings(settings)
    elements, effective_values = _mapped_elements(
        config,
        values,
        use_defaults=use_defaults,
        nest_localized=True,
    )
    try:
        parent_id = int(config["parent_id"])
    except (TypeError, ValueError) as exc:
        raise ValueError("parent_id musi byc liczba.") from exc
    return {
        "className": config["class_name"],
        "parentId": parent_id,
        "key": render_object_key(config["object_key_template"], effective_values),
        "published": config["published"] if published is None else bool(published),
        "elements": elements,
    }


def extract_object_id(payload: object) -> int:
    candidates = [payload]
    if isinstance(payload, dict):
        candidates.extend([payload.get("data"), payload.get("object")])
    for candidate in candidates:
        if isinstance(candidate, dict):
            try:
                return int(candidate.get("id"))
            except (TypeError, ValueError):
                pass
    raise ValueError("Odpowiedz Pimcore nie zawiera ID obiektu.")


def _list_records(payload: object, keys: tuple[str, ...]) -> list[dict[str, object]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested = _list_records(value, keys)
            if nested:
                return nested
    return []


def extract_class_fields(payload: object) -> dict[str, str]:
    fields: dict[str, str] = {}

    def visit(node: object) -> None:
        if isinstance(node, dict):
            name = str(node.get("name") or "").strip()
            field_type = str(node.get("fieldtype") or node.get("datatype") or "").strip()
            if name and field_type:
                fields[name] = field_type
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(payload)
    return fields


def discover_classes(api: PimcoreClient) -> list[dict[str, str]]:
    records = _list_records(api.classes(), ("data", "classes", "items"))
    result = [
        {
            "id": str(item.get("id") or item.get("classId") or ""),
            "name": str(item.get("name") or "").strip(),
        }
        for item in records
        if str(item.get("id") or item.get("classId") or "").strip()
        and str(item.get("name") or "").strip()
    ]
    return sorted(result, key=lambda item: item["name"].casefold())


def extract_class_field_records(payload: object) -> list[dict[str, object]]:
    fields: dict[tuple[str, str], dict[str, object]] = {}

    def add_field(
        *,
        name: str,
        label: str,
        node_type: str,
        language: str | None,
    ) -> None:
        parser = SUPPORTED_FIELD_PARSERS.get(node_type, "")
        field_label = f"{label} [{language}]" if language else label
        fields[(name, language or "")] = {
            "name": name,
            "label": field_label,
            "type": node_type,
            "language": language,
            "parser": parser,
            "supported": bool(parser),
            "unsupported_reason": (
                "" if parser else f"Typ {node_type} nie jest obslugiwany."
            ),
        }

    def visit(
        node: object,
        language: str | None = None,
        localized: bool = False,
    ) -> None:
        if isinstance(node, dict):
            node_type = str(node.get("fieldtype") or node.get("datatype") or "").lower()
            name = str(node.get("name") or "").strip()
            current_language = str(node.get("language") or language or "").strip() or None
            is_localized_container = node_type == "localizedfields"
            inside_localized = localized or is_localized_container
            if name and node_type and not is_localized_container:
                label = str(node.get("title") or node.get("label") or name).strip()
                if inside_localized and not current_language:
                    for item_language in LOCALIZED_FIELD_LANGUAGES:
                        add_field(
                            name=name,
                            label=label,
                            node_type=node_type,
                            language=item_language,
                        )
                else:
                    add_field(
                        name=name,
                        label=label,
                        node_type=node_type,
                        language=current_language,
                    )
            for value in node.values():
                visit(value, current_language, inside_localized)
        elif isinstance(node, list):
            for value in node:
                visit(value, language, localized)

    visit(payload)
    return sorted(
        fields.values(),
        key=lambda item: (str(item["name"]).casefold(), str(item.get("language") or "")),
    )


def discover_fields(api: PimcoreClient, class_id: object) -> list[dict[str, object]]:
    return extract_class_field_records(api.class_definition(class_id))


def discover_folders(api: PimcoreClient, limit: int = 500) -> list[dict[str, object]]:
    bounded_limit = min(500, max(1, int(limit)))
    records: list[dict[str, object]] = []
    page_size = min(100, bounded_limit)
    query_filter: dict[str, object] | None = {"type": "folder"}
    try:
        for offset in range(0, bounded_limit, page_size):
            payload = api.object_list(
                query_filter,
                limit=min(page_size, bounded_limit - offset),
                offset=offset,
            )
            page = _list_records(payload, ("data", "objects", "items"))
            records.extend(page)
            if len(page) < page_size:
                break
    except PimcoreApiError as exc:
        if not exc.status_code or exc.status_code < 500 or records:
            raise
        payload = api.object_list(limit=bounded_limit, offset=0)
        records = _list_records(payload, ("data", "objects", "items"))
    folders: list[dict[str, object]] = []
    for record in records:
        if str(record.get("type") or "").casefold() != "folder":
            continue
        identity = normalize_object_identity(record)
        if not identity["id"]:
            continue
        path = identity["path"]
        key = identity["key"]
        if not path:
            try:
                detail = api.object_by_id(identity["id"])
            except PimcoreApiError:
                continue
            source = detail.get("data") if isinstance(detail.get("data"), dict) else detail
            path = extract_object_path(source)
            key = str(source.get("key") or key) if isinstance(source, dict) else key
        if not key and path:
            key = path.rstrip("/").rsplit("/", 1)[-1]
        folders.append({"id": identity["id"], "path": path, "key": key})
    return sorted(folders, key=lambda item: str(item["path"] or item["key"]).casefold())


def mapping_compatibility_issues(
    mappings: list[dict[str, object]],
    class_fields: dict[str, str],
) -> list[str]:
    parser_types = {
        "text": {"input", "textarea", "select"},
        "integer": {"numeric"},
        "decimal_comma": {"numeric"},
        "boolean": {"checkbox"},
        "empty_to_null": {"input", "textarea", "numeric", "select"},
    }
    issues: list[str] = []
    for mapping in mappings:
        target = str(mapping["pimcore_field"])
        actual_type = str(class_fields.get(target) or "")
        configured_type = str(mapping["type"])
        parser = str(mapping["parser"])
        if actual_type and actual_type != configured_type:
            issues.append(f"{target}: typ klasy {actual_type}, mapowanie {configured_type}")
        if configured_type not in parser_types.get(parser, set()):
            issues.append(f"{target}: parser {parser} nie pasuje do typu {configured_type}")
    return issues


def _check(
    key: str,
    status: str,
    message: str,
    *,
    endpoint: str = "local",
    status_code: int | None = None,
    response_excerpt: str = "",
    response_detail: str = "",
    suggested_fix: str = "",
    elapsed_ms: int = 0,
) -> dict[str, object]:
    return {
        "key": key,
        "status": status,
        "message": message,
        "endpoint": endpoint,
        "status_code": status_code,
        "response_excerpt": response_excerpt,
        "response_detail": response_detail,
        "suggested_fix": suggested_fix,
        "elapsed_ms": elapsed_ms,
    }


def _skipped(key: str, message: str, suggested_fix: str = "") -> dict[str, object]:
    return _check(
        key,
        "skipped",
        message,
        suggested_fix=suggested_fix,
    )


def _last_status_code(api: object) -> int | None:
    last_response = getattr(api, "last_response", {})
    if isinstance(last_response, dict):
        status_code = last_response.get("status_code")
        if isinstance(status_code, int):
            return status_code
    return None


def find_class_record(payload: object, class_name: str) -> dict[str, object] | None:
    return next(
        (
            item
            for item in _list_records(payload, ("data", "classes", "items"))
            if str(item.get("name") or "") == class_name
        ),
        None,
    )


def mapping_field_errors(
    mappings: list[dict[str, object]], fields: dict[str, str]
) -> list[str]:
    targets = [str(item["pimcore_field"]) for item in mappings]
    missing = [name for name in targets if name not in fields]
    return (
        (["Brak pol w klasie: " + ", ".join(missing)] if missing else [])
        + mapping_compatibility_issues(mappings, fields)
    )


def append_version_check(checks: list[dict[str, object]], server_info: object) -> None:
    version_text = json.dumps(server_info, ensure_ascii=True, default=str)
    compatible = "6." in version_text or "version" not in version_text.lower()
    checks.append(
        _check(
            "version",
            "ok" if compatible else "warning",
            "Wersja Pimcore jest zgodna."
            if compatible
            else "Serwer nie zglosil wersji Pimcore 6.x.",
        )
    )


def class_exists_check(
    class_name: str, class_record: dict[str, object] | None
) -> dict[str, object]:
    return _check(
        "class_exists",
        "ok" if class_record else "error",
        f"Znaleziono klase {class_name}."
        if class_record
        else f"Nie znaleziono klasy {class_name}.",
        suggested_fix="" if class_record else "Wybierz klase z listy pobranej z Pimcore.",
    )


def mapping_fields_check(errors: list[str]) -> dict[str, object]:
    return _check(
        "mapping_fields",
        "error" if errors else "ok",
        " | ".join(errors) if errors else "Wszystkie mapowane pola istnieja i maja zgodne typy.",
        suggested_fix=(
            "Zmien przypisanie pol zgodnie z definicja klasy Pimcore." if errors else ""
        ),
    )


def run_settings_test(
    settings: object,
    *,
    client: PimcoreClient | None = None,
) -> dict[str, object]:
    started = time.perf_counter()
    raw_settings = settings if isinstance(settings, dict) else {}
    config = normalize_pimcore_settings(settings)
    checks: list[dict[str, object]] = []

    def timed(key: str, endpoint: str, callback: Callable[[], object]) -> object | None:
        check_started = time.perf_counter()
        try:
            result = callback()
            checks.append(
                _check(
                    key,
                    "ok",
                    "Test zakonczony poprawnie.",
                    endpoint=endpoint,
                    status_code=_last_status_code(api),
                    elapsed_ms=int((time.perf_counter() - check_started) * 1000),
                )
            )
            return result
        except PimcoreApiError as exc:
            checks.append(
                _check(
                    key,
                    "error",
                    str(exc),
                    endpoint=exc.endpoint,
                    status_code=exc.status_code,
                    response_excerpt=exc.response_excerpt,
                    response_detail=exc.response_detail,
                    suggested_fix=(
                        "Sprawdz adres, klucz API, Webservice API i uprawnienia "
                        "uzytkownika Pimcore."
                    ),
                    elapsed_ms=int((time.perf_counter() - check_started) * 1000),
                )
            )
            return None

    base_ok = bool(re.fullmatch(r"https?://[^\s/]+(?::\d+)?(?:/.*)?", config["base_url"]))
    checks.append(
        _check(
            "base_url",
            "ok" if base_ok else "error",
            (
                "Adres bazowy jest poprawny."
                if base_ok
                else "Adres Pimcore musi zaczynac sie od http:// albo https://."
            ),
            suggested_fix=(
                ""
                if base_ok
                else "Wpisz pelny adres panelu Pimcore, np. http://twoj-adres-pimcore.example."
            ),
        )
    )
    key_ok = bool(config[PIMCORE_API_KEY])
    checks.append(
        _check(
            "api_key",
            "ok" if key_ok else "error",
            "Klucz API jest ustawiony." if key_ok else "Brak klucza API.",
            suggested_fix=(
                ""
                if key_ok
                else "Wklej klucz API dedykowanego uzytkownika Pimcore i zapisz ustawienia."
            ),
        )
    )
    definition_issues = field_mapping_issues(raw_settings.get("field_mappings", []))
    checks.append(
        _check(
            "mapping_definitions",
            "error" if definition_issues else "ok",
            (
                " | ".join(definition_issues)
                if definition_issues
                else "Definicje mapowania sa poprawne."
            ),
            suggested_fix=(
                "Popraw wskazane wiersze tabeli mapowania." if definition_issues else ""
            ),
        )
    )
    required_sources = {
        item["source"] for item in config["field_mappings"] if item["required"]
    }
    key_sources = set(re.findall(r"\{([^{}]+)\}", config["object_key_template"]))
    mapped_sources = {item["source"] for item in config["field_mappings"]}
    local_ok = "EAN" in required_sources and bool(key_sources & mapped_sources)
    checks.append(
        _check(
            "mapping_local",
            "ok" if local_ok else "error",
            (
                "Mapowanie zawiera EAN i zrodlo klucza."
                if local_ok
                else "EAN musi byc wymagany, a szablon klucza musi wskazywac mapowane pole."
            ),
            suggested_fix=(
                ""
                if local_ok
                else "Oznacz EAN jako wymagany i ustaw szablon np. {SKU} albo {EAN}."
            ),
        )
    )
    if not config["parent_id"]:
        checks.append(
            _check(
                "parent",
                "error",
                "Brak parent_id folderu Produkty.",
                suggested_fix="Wpisz numeryczne ID folderu Produkty z Pimcore.",
            )
        )
    checks.append(
        _check(
            "test_form_schema",
            "ok" if config["field_mappings"] else "error",
            (
                "Formularz testowy moze zostac zbudowany."
                if config["field_mappings"]
                else "Brak mapowania pol."
            ),
            suggested_fix=(
                ""
                if config["field_mappings"]
                else "Dodaj co najmniej mapowania EAN i pola uzywanego przez szablon klucza."
            ),
        )
    )
    remote_prerequisites = base_ok and key_ok
    server_ready = False
    if not remote_prerequisites:
        checks.extend(
            [
                _skipped("server_info", "Pominieto test serwera z powodu bledow lokalnych."),
                _skipped("classes", "Pominieto pobieranie klas."),
                _skipped("class_exists", "Pominieto sprawdzanie klasy."),
                _skipped("class_definition", "Pominieto pobieranie definicji klasy."),
                _skipped("mapping_fields", "Pominieto zgodnosc pol klasy."),
                _skipped("object_list", "Pominieto test wyszukiwania EAN."),
            ]
        )
        if config["parent_id"]:
            checks.append(_skipped("parent", "Pominieto sprawdzanie folderu docelowego."))
    else:
        api = client or PimcoreClient(config)
        server_info = timed("server_info", "/webservice/rest/server-info", api.server_info)
        if server_info is None:
            checks.extend(
                [
                    _skipped("classes", "Pominieto pobieranie klas po bledzie serwera."),
                    _skipped("class_exists", "Pominieto sprawdzanie klasy."),
                    _skipped("class_definition", "Pominieto pobieranie definicji klasy."),
                    _skipped("mapping_fields", "Pominieto zgodnosc pol klasy."),
                    _skipped("object_list", "Pominieto test wyszukiwania EAN."),
                ]
            )
            if config["parent_id"]:
                checks.append(_skipped("parent", "Pominieto sprawdzanie folderu docelowego."))
        else:
            server_ready = True
            append_version_check(checks, server_info)
            classes_payload = timed("classes", "/webservice/rest/classes", api.classes)
            if classes_payload is None:
                checks.extend(
                    [
                        _skipped("class_exists", "Pominieto sprawdzanie klasy."),
                        _skipped("class_definition", "Pominieto pobieranie definicji klasy."),
                        _skipped("mapping_fields", "Pominieto zgodnosc pol klasy."),
                        _skipped("object_list", "Pominieto test wyszukiwania EAN."),
                    ]
                )
            else:
                class_record = find_class_record(classes_payload, config["class_name"])
                checks.append(class_exists_check(config["class_name"], class_record))
                fields: dict[str, str] = {}
                if class_record:
                    class_id = class_record.get("id") or class_record.get("classId")
                    class_payload = timed(
                        "class_definition",
                        f"/webservice/rest/class/id/{class_id}",
                        lambda: api.class_definition(class_id),
                    )
                    if class_payload is not None:
                        fields = extract_class_fields(class_payload)
                else:
                    checks.append(_skipped("class_definition", "Klasa nie istnieje."))

                mapping_ready = bool(config["field_mappings"]) and local_ok and bool(fields)
                if fields and config["field_mappings"]:
                    errors = mapping_field_errors(config["field_mappings"], fields)
                    checks.append(mapping_fields_check(errors))
                    mapping_ready = mapping_ready and not errors
                else:
                    checks.append(_skipped("mapping_fields", "Brak klasy albo mapowania."))

                if mapping_ready:
                    timed(
                        "object_list",
                        "/webservice/rest/object-list",
                        lambda: api.object_list(
                            build_ean_filter("0000000000000", config["existence_fields"]),
                            object_class=config["class_name"],
                            limit=2,
                        ),
                    )
                else:
                    checks.append(
                        _skipped("object_list", "Klasa lub mapowanie EAN nie jest gotowe.")
                    )

        if server_ready and config["parent_id"]:
            timed(
                "parent",
                f"/webservice/rest/object/id/{config['parent_id']}",
                lambda: api.object_by_id(config["parent_id"]),
            )
    checks.append(
        _check(
            "create_permission",
            "info",
            "Uprawnienie tworzenia nie zostalo sprawdzone. Uruchom testowe dodanie obiektu.",
        )
    )
    return {
        "ok": not any(item["status"] == "error" for item in checks),
        "checks": checks,
        "total_ms": int((time.perf_counter() - started) * 1000),
    }


def extract_object_values(payload: object) -> dict[str, object]:
    values: dict[str, object] = {}

    def visit(node: object) -> None:
        if isinstance(node, dict):
            name = str(node.get("name") or "").strip()
            if name and "value" in node:
                values[name] = node.get("value")
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(payload)
    return values


def extract_object_path(payload: object) -> str:
    if isinstance(payload, dict):
        for key in ("fullPath", "path"):
            if payload.get(key):
                return str(payload[key])
        for key in ("data", "object"):
            path = extract_object_path(payload.get(key))
            if path:
                return path
    return ""


def normalize_object_identity(record: object) -> dict[str, object]:
    source = record if isinstance(record, dict) else {}
    raw_id = source.get("id") or source.get("o_id") or source.get("objectId")
    try:
        object_id = int(raw_id)
    except (TypeError, ValueError):
        object_id = 0
    return {
        "id": object_id,
        "key": str(source.get("key") or source.get("o_key") or ""),
        "path": str(
            source.get("fullPath")
            or source.get("path")
            or source.get("o_path")
            or ""
        ),
    }


def _object_data(payload: object) -> dict[str, object]:
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        return dict(payload["data"])
    if isinstance(payload, dict) and isinstance(payload.get("object"), dict):
        return dict(payload["object"])
    return dict(payload) if isinstance(payload, dict) else {}


def _object_marker(data: dict[str, object]) -> str:
    timestamp = str(data.get("modificationDate") or data.get("modification_date") or "")
    if timestamp:
        return timestamp
    canonical = json.dumps(data, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _configured_values(config: dict[str, object], data: dict[str, object]) -> dict[str, object]:
    elements = data.get("elements") if isinstance(data.get("elements"), list) else []
    indexed: dict[tuple[str, str], object] = {}

    def visit(node: object) -> None:
        if isinstance(node, dict):
            name = str(node.get("name") or "")
            language = str(node.get("language") or "")
            if name and "value" in node and not isinstance(node.get("value"), (dict, list)):
                indexed[(name, language)] = node.get("value")
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(elements)
    return {
        mapping["source"]: indexed.get(
            (mapping["pimcore_field"], str(mapping.get("language") or "")),
            "",
        )
        for mapping in config["field_mappings"]
    }


def fetch_product_for_edit(
    settings: object,
    object_id: object,
    *,
    client: PimcoreClient | None = None,
) -> dict[str, object]:
    config = normalize_pimcore_settings(settings)
    api = client or PimcoreClient(config)
    data = _object_data(api.object_by_id(object_id))
    identity = normalize_object_identity(data)
    return {
        "object": identity,
        "marker": _object_marker(data),
        "values": _configured_values(config, data),
    }


def merge_product_update_payload(
    settings: object,
    current_data: dict[str, object],
    values: dict[str, object],
) -> dict[str, object]:
    config = normalize_pimcore_settings(settings)
    submitted_ean = validate_ean(values.get("EAN"))
    current_values = _configured_values(config, current_data)
    if current_values.get("EAN") and str(current_values["EAN"]) != submitted_ean:
        raise ValueError("EAN istniejacego produktu nie moze zostac zmieniony.")
    replacements, _effective_values = _mapped_elements(
        config,
        values,
        use_defaults=False,
        include_empty=True,
    )
    replacement_keys = {
        (item["name"], str(item.get("language") or "")): item for item in replacements
    }
    existing = current_data.get("elements") if isinstance(current_data.get("elements"), list) else []
    used: set[tuple[str, str]] = set()

    def merge_node(raw: object, *, in_localized: bool = False) -> object:
        if isinstance(raw, list):
            return [merge_node(item, in_localized=in_localized) for item in raw]
        if not isinstance(raw, dict):
            return raw
        item = dict(raw)
        is_localized_container = (
            str(item.get("type") or "").casefold() == "localizedfields"
            or str(item.get("name") or "").casefold() == "localizedfields"
        )
        key = (str(item.get("name") or ""), str(item.get("language") or ""))
        replacement = replacement_keys.get(key)
        replacement_language = str(replacement.get("language") or "") if replacement else ""
        if replacement and (not replacement_language or in_localized):
            used.add(key)
            item.update(replacement)
            return item
        for field, value in list(item.items()):
            if isinstance(value, (dict, list)):
                item[field] = merge_node(
                    value,
                    in_localized=in_localized or is_localized_container,
                )
        return item

    merged_elements = [merge_node(item) for item in existing]

    def localized_container() -> dict[str, object]:
        for item in merged_elements:
            if not isinstance(item, dict):
                continue
            if (
                str(item.get("type") or "").casefold() == "localizedfields"
                or str(item.get("name") or "").casefold() == "localizedfields"
            ):
                if not isinstance(item.get("value"), list):
                    item["value"] = []
                return item
        item = {"type": "localizedfields", "name": "localizedfields", "value": []}
        merged_elements.append(item)
        return item

    for key, item in replacement_keys.items():
        if key in used:
            continue
        if str(item.get("language") or ""):
            container = localized_container()
            value = container.get("value")
            if not isinstance(value, list):
                value = []
                container["value"] = value
            value.append(dict(item))
        else:
            merged_elements.append(dict(item))
    payload = dict(current_data)
    payload["elements"] = merged_elements
    payload["published"] = True
    return payload


def find_product_by_ean(
    settings: object,
    ean: object,
    *,
    client: PimcoreClient | None = None,
) -> dict[str, object] | None:
    config = normalize_pimcore_settings(settings)
    api = client or PimcoreClient(config)
    payload = api.object_list(
        build_ean_filter(ean, config["existence_fields"]),
        object_class=config["class_name"],
        limit=2,
    )
    records = _list_records(payload, ("data", "objects", "items"))
    if len(records) > 1:
        raise ValueError("Znaleziono wiele produktow Pimcore z tym samym EAN.")
    identity = normalize_object_identity(records[0]) if records else None
    if identity is not None and int(identity["id"] or 0) <= 0:
        raise ValueError("Odpowiedz Pimcore zawiera produkt bez poprawnego ID.")
    return identity


def create_product(
    settings: object,
    values: dict[str, object],
    *,
    client: PimcoreClient | None = None,
    emit: Callable[..., None],
) -> dict[str, object]:
    config = normalize_pimcore_settings(settings)
    api = client or PimcoreClient(config)
    ean = validate_ean(values.get("EAN"))
    stage_started = time.perf_counter()
    duplicate = find_product_by_ean(config, ean, client=api)
    if duplicate:
        emit(
            "duplicate_check",
            "success",
            "EAN juz istnieje w Pimcore.",
            object_id=duplicate["id"],
            object_path=duplicate["path"],
            status="existing",
            stage_elapsed_ms=int((time.perf_counter() - stage_started) * 1000),
        )
        return {
            "created": False,
            "duplicate": True,
            "object": duplicate,
            "object_id": duplicate["id"],
        }
    emit(
        "duplicate_check",
        "success",
        "EAN nie istnieje; mozna utworzyc produkt.",
        stage_elapsed_ms=int((time.perf_counter() - stage_started) * 1000),
    )

    stage_started = time.perf_counter()
    payload = build_create_payload(config, values, published=config["published"], use_defaults=True)
    emit(
        "payload",
        "success",
        "Zbudowano dane produktu.",
        payload=payload,
        stage_elapsed_ms=int((time.perf_counter() - stage_started) * 1000),
    )

    stage_started = time.perf_counter()
    try:
        response = api.create_object(payload)
        object_id = extract_object_id(response)
    except PimcoreApiError as exc:
        emit(
            "create",
            "error",
            str(exc),
            method="POST",
            endpoint="/webservice/rest/object",
            error=exc.as_dict(include_detail=True),
            stage_elapsed_ms=int((time.perf_counter() - stage_started) * 1000),
        )
        raise
    except ValueError as exc:
        emit(
            "create",
            "error",
            str(exc),
            method="POST",
            endpoint="/webservice/rest/object",
            response_excerpt=_response_excerpt(json.dumps(response, ensure_ascii=True)),
            stage_elapsed_ms=int((time.perf_counter() - stage_started) * 1000),
        )
        raise
    emit(
        "create",
        "success",
        "Utworzono produkt Pimcore.",
        object_id=object_id,
        method="POST",
        endpoint="/webservice/rest/object",
        status_code=_last_status_code(api),
        response_excerpt=_response_excerpt(json.dumps(response, ensure_ascii=True)),
        stage_elapsed_ms=int((time.perf_counter() - stage_started) * 1000),
    )

    stage_started = time.perf_counter()
    fetched = api.object_by_id(object_id)
    source = fetched.get("data") if isinstance(fetched, dict) and isinstance(fetched.get("data"), dict) else fetched
    identity = normalize_object_identity(source)
    if not identity["id"]:
        identity["id"] = object_id
    emit(
        "verify",
        "success",
        "Potwierdzono produkt w Pimcore.",
        object_id=object_id,
        endpoint=f"/webservice/rest/object/id/{object_id}",
        status_code=_last_status_code(api),
        response_excerpt=_response_excerpt(json.dumps(fetched, ensure_ascii=True)),
        stage_elapsed_ms=int((time.perf_counter() - stage_started) * 1000),
    )
    return {
        "created": True,
        "duplicate": False,
        "object": identity,
        "object_id": identity["id"],
        "payload": payload,
        "change_set": {
            "kind": "created",
            "fields": [
                {"key": key, "label": key, "before": None, "after": value}
                for key, value in sorted(values.items())
            ],
        },
    }


def update_product(
    settings: object,
    object_id: object,
    expected_marker: object,
    values: dict[str, object],
    *,
    client: PimcoreClient | None = None,
    emit: Callable[..., None],
) -> dict[str, object]:
    config = normalize_pimcore_settings(settings)
    api = client or PimcoreClient(config)
    numeric_id = int(object_id)
    stage_started = time.perf_counter()
    current_payload = api.object_by_id(numeric_id)
    current_data = _object_data(current_payload)
    current_values = _configured_values(config, current_data)
    current_marker = _object_marker(current_data)
    if current_marker != str(expected_marker or ""):
        emit(
            "conflict",
            "warning",
            "Obiekt zostal zmieniony w Pimcore.",
            object_id=numeric_id,
            expected_marker=str(expected_marker or ""),
            current_marker=current_marker,
            stage_elapsed_ms=int((time.perf_counter() - stage_started) * 1000),
        )
        raise PimcoreConflictError(
            "Obiekt zostal zmieniony w Pimcore. Otworz go ponownie.",
            numeric_id,
            str(expected_marker or ""),
            current_marker,
        )

    payload = merge_product_update_payload(config, current_data, values)
    emit(
        "payload",
        "success",
        "Polaczono zmiany z aktualnym obiektem.",
        object_id=numeric_id,
        stage_elapsed_ms=int((time.perf_counter() - stage_started) * 1000),
    )

    stage_started = time.perf_counter()
    try:
        response = api.update_object(numeric_id, payload)
    except PimcoreApiError as exc:
        emit(
            "update",
            "error",
            str(exc),
            method="PUT",
            endpoint=f"/webservice/rest/object/id/{numeric_id}",
            error=exc.as_dict(include_detail=True),
            stage_elapsed_ms=int((time.perf_counter() - stage_started) * 1000),
        )
        raise
    emit(
        "update",
        "success",
        "Zaktualizowano i opublikowano produkt Pimcore.",
        object_id=numeric_id,
        method="PUT",
        endpoint=f"/webservice/rest/object/id/{numeric_id}",
        status_code=_last_status_code(api),
        response_excerpt=_response_excerpt(json.dumps(response, ensure_ascii=True)),
        stage_elapsed_ms=int((time.perf_counter() - stage_started) * 1000),
    )

    stage_started = time.perf_counter()
    verified_payload = api.object_by_id(numeric_id)
    verified_data = _object_data(verified_payload)
    verified_values = _configured_values(config, verified_data)
    _elements, expected_values = _mapped_elements(
        config,
        values,
        use_defaults=False,
        include_empty=True,
    )
    mismatches = [
        source
        for source, expected in expected_values.items()
        if str(verified_values.get(source, ""))
        != str(expected if expected is not None else "")
    ]
    if mismatches:
        raise ValueError(
            "Pimcore nie potwierdzil zapisanych wartosci: " + ", ".join(mismatches)
        )
    identity = normalize_object_identity(verified_data)
    emit(
        "verify",
        "success",
        "Potwierdzono zapisane wartosci.",
        object_id=numeric_id,
        object_path=identity["path"],
        stage_elapsed_ms=int((time.perf_counter() - stage_started) * 1000),
    )
    changes = field_changes(current_values, verified_values)
    return {
        "object": identity,
        "values": verified_values,
        "marker": _object_marker(verified_data),
        "change_set": {
            "kind": "updated" if changes else "synchronized",
            "fields": changes,
        },
    }


def run_test_create(
    settings: object,
    values: dict[str, object],
    cleanup_policy: str,
    *,
    client: PimcoreClient | None = None,
    emit: Callable[..., None],
) -> dict[str, object]:
    if cleanup_policy not in {"delete", "keep"}:
        raise ValueError("Wybierz usuniecie albo pozostawienie obiektu testowego.")
    config = normalize_pimcore_settings(settings)
    api = client or PimcoreClient(config)
    preflight = run_settings_test(config, client=api)
    for check in preflight["checks"]:
        severity = {
            "ok": "success",
            "warning": "warning",
            "error": "error",
            "skipped": "info",
            "info": "info",
        }.get(str(check.get("status")), "info")
        emit(
            "preflight",
            severity,
            f"{check.get('key')}: {check.get('message')}",
            endpoint=check.get("endpoint"),
            status_code=check.get("status_code"),
            response_excerpt=check.get("response_excerpt"),
            suggested_fix=check.get("suggested_fix"),
            stage_elapsed_ms=check.get("elapsed_ms", 0),
        )
    if not preflight["ok"]:
        failed = [
            str(item.get("message"))
            for item in preflight["checks"]
            if item.get("status") == "error"
        ]
        raise ValueError("Test konfiguracji blokuje zapis: " + " | ".join(failed))

    stage_started = time.perf_counter()
    try:
        payload = build_create_payload(
            config,
            values,
            published=False,
            use_defaults=False,
        )
    except ValueError as exc:
        emit(
            "validate",
            "error",
            str(exc),
            stage_elapsed_ms=int((time.perf_counter() - stage_started) * 1000),
        )
        raise
    emit(
        "validate",
        "success",
        "Walidacja konfiguracji i pol zakonczona.",
        stage_elapsed_ms=int((time.perf_counter() - stage_started) * 1000),
    )
    safe_payload = {**payload, "elements": [dict(item) for item in payload["elements"]]}
    emit(
        "payload",
        "info",
        "Zbudowano dane obiektu.",
        payload=safe_payload,
        stage_elapsed_ms=int((time.perf_counter() - stage_started) * 1000),
    )

    stage_started = time.perf_counter()
    ean = validate_ean(values.get("EAN"))
    duplicates = api.object_list(
        build_ean_filter(ean, config["existence_fields"]),
        object_class=config["class_name"],
        limit=2,
    )
    duplicate_records = _list_records(duplicates, ("data", "objects", "items"))
    if duplicate_records:
        duplicate = duplicate_records[0]
        emit(
            "duplicate_check",
            "error",
            "Testowy EAN juz istnieje w Pimcore.",
            object_id=duplicate.get("id"),
            object_path=duplicate.get("fullPath") or duplicate.get("path"),
            stage_elapsed_ms=int((time.perf_counter() - stage_started) * 1000),
        )
        raise ValueError("Testowy EAN juz istnieje w Pimcore; podaj izolowana wartosc.")
    emit(
        "duplicate_check",
        "success",
        "Testowy EAN nie istnieje w Pimcore.",
        stage_elapsed_ms=int((time.perf_counter() - stage_started) * 1000),
    )

    stage_started = time.perf_counter()
    try:
        created = api.create_object(payload)
        object_id = extract_object_id(created)
    except PimcoreApiError as exc:
        emit(
            "create",
            "error",
            str(exc),
            method="POST",
            endpoint="/webservice/rest/object",
            error=exc.as_dict(include_detail=True),
            stage_elapsed_ms=int((time.perf_counter() - stage_started) * 1000),
        )
        raise
    except ValueError as exc:
        emit(
            "create",
            "error",
            str(exc),
            method="POST",
            endpoint="/webservice/rest/object",
            response_excerpt=_response_excerpt(json.dumps(created, ensure_ascii=True)),
            stage_elapsed_ms=int((time.perf_counter() - stage_started) * 1000),
        )
        raise
    emit(
        "create",
        "success",
        "Utworzono obiekt.",
        object_id=object_id,
        method="POST",
        endpoint="/webservice/rest/object",
        status_code=_last_status_code(api),
        response_excerpt=_response_excerpt(json.dumps(created, ensure_ascii=True)),
        stage_elapsed_ms=int((time.perf_counter() - stage_started) * 1000),
    )

    status = "completed"
    cleanup_result = "kept"
    error = ""
    object_path = ""
    try:
        stage_started = time.perf_counter()
        fetched = api.object_by_id(object_id)
        object_path = extract_object_path(fetched)
        fetched_data = _object_data(fetched)
        actual = _configured_values(config, fetched_data)
        expected = _configured_values(config, {"elements": payload["elements"]})
        mismatched = [
            source
            for source, value in expected.items()
            if str(actual.get(source, ""))
            != str(value if value is not None else "")
        ]
        if mismatched:
            status = "partial"
            error = "Nie potwierdzono pol: " + ", ".join(mismatched)
            emit(
                "verify",
                "warning",
                error,
                object_id=object_id,
                endpoint=f"/webservice/rest/object/id/{object_id}",
                status_code=_last_status_code(api),
                response_excerpt=_response_excerpt(json.dumps(fetched, ensure_ascii=True)),
                stage_elapsed_ms=int((time.perf_counter() - stage_started) * 1000),
            )
        else:
            emit(
                "verify",
                "success",
                "Odczyt kontrolny potwierdzil dane.",
                object_id=object_id,
                endpoint=f"/webservice/rest/object/id/{object_id}",
                status_code=_last_status_code(api),
                response_excerpt=_response_excerpt(json.dumps(fetched, ensure_ascii=True)),
                stage_elapsed_ms=int((time.perf_counter() - stage_started) * 1000),
            )
    except PimcoreApiError as exc:
        status = "partial"
        error = str(exc)
        emit(
            "verify",
            "error",
            str(exc),
            object_id=object_id,
            error=exc.as_dict(include_detail=True),
            stage_elapsed_ms=int((time.perf_counter() - stage_started) * 1000),
        )

    if cleanup_policy == "delete":
        try:
            stage_started = time.perf_counter()
            deleted = api.delete_object(object_id)
            cleanup_result = "deleted"
            emit(
                "delete",
                "success",
                "Usunieto obiekt testowy.",
                object_id=object_id,
                method="DELETE",
                endpoint=f"/webservice/rest/object/id/{object_id}",
                status_code=_last_status_code(api),
                response_excerpt=_response_excerpt(json.dumps(deleted, ensure_ascii=True)),
                stage_elapsed_ms=int((time.perf_counter() - stage_started) * 1000),
            )
        except PimcoreApiError as exc:
            status = "partial"
            cleanup_result = "delete_failed"
            error = str(exc)
            emit(
                "delete",
                "error",
                str(exc),
                object_id=object_id,
                error=exc.as_dict(include_detail=True),
                stage_elapsed_ms=int((time.perf_counter() - stage_started) * 1000),
            )
    return {
        "status": status,
        "object_id": object_id,
        "object_key": payload["key"],
        "object_path": object_path,
        "cleanup_policy": cleanup_policy,
        "cleanup_result": cleanup_result,
        "error": error,
        "payload": safe_payload,
    }
