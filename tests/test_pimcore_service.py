from io import BytesIO
import json
from unittest.mock import Mock
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import pytest

from picsyncra.services.pimcore_service import (
    PimcoreApiError,
    PimcoreClient,
    PimcoreConflictError,
    build_create_payload,
    build_ean_filter,
    create_product,
    discover_classes,
    discover_fields,
    discover_folders,
    extract_object_id,
    fetch_product_for_edit,
    find_product_by_ean,
    merge_product_update_payload,
    normalize_object_identity,
    run_settings_test,
    update_product,
)


class FakeResponse:
    def __init__(self, payload, status=200):
        self.status = status
        self._body = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


def test_client_uses_api_header_and_never_query_string():
    captured = {}

    def opener(request, timeout, context):
        captured["url"] = request.full_url
        captured["api_key"] = request.get_header("X-api-key")
        captured["timeout"] = timeout
        return FakeResponse({"success": True, "data": {"version": "6.6.11"}})

    client = PimcoreClient(
        {"base_url": "http://pimcore.example.test", "api_key": "secret", "timeout_seconds": 7},
        opener=opener,
    )
    result = client.server_info()

    assert result["success"] is True
    assert captured == {
        "url": "http://pimcore.example.test/webservice/rest/server-info",
        "api_key": "secret",
        "timeout": 7,
    }
    assert "secret" not in captured["url"]


def test_build_create_payload_parses_values_and_renders_key():
    config = {
        "class_name": "Product",
        "parent_id": "123",
        "published": True,
        "object_key_template": "{EAN}",
        "field_mappings": [
            {
                "source": "EAN",
                "pimcore_field": "EAN",
                "type": "input",
                "language": None,
                "required": True,
                "default": "",
                "parser": "text",
            },
            {
                "source": "SKU",
                "pimcore_field": "SKU",
                "type": "input",
                "language": None,
                "required": True,
                "default": "",
                "parser": "text",
            },
            {
                "source": "TOTAL WEIGHT",
                "pimcore_field": "TOTAL_WEIGHT",
                "type": "numeric",
                "language": None,
                "required": False,
                "default": "",
                "parser": "decimal_comma",
            },
        ],
    }

    payload = build_create_payload(
        config,
        {"EAN": "5904804578169", "SKU": "ABC-1", "TOTAL WEIGHT": "62,5"},
    )

    assert payload == {
        "className": "Product",
        "parentId": 123,
        "key": "5904804578169",
        "published": True,
        "elements": [
            {"type": "input", "name": "EAN", "value": "5904804578169", "language": None},
            {"type": "input", "name": "SKU", "value": "ABC-1", "language": None},
            {"type": "numeric", "name": "TOTAL_WEIGHT", "value": 62.5, "language": None},
        ],
    }


def test_build_create_payload_nests_localized_field_values():
    config = {
        "enabled": True,
        "class_name": "Product",
        "parent_id": "123",
        "published": True,
        "object_key_template": "{EAN}",
        "existence_fields": ["EAN"],
        "field_mappings": [
            {
                "source": "EAN",
                "pimcore_field": "EAN",
                "type": "input",
                "language": None,
                "required": True,
                "default": "",
                "parser": "text",
            },
            {
                "source": "NAME_EN",
                "pimcore_field": "name",
                "type": "input",
                "language": "en",
                "required": False,
                "default": "",
                "parser": "text",
            },
            {
                "source": "NAME_PL",
                "pimcore_field": "name",
                "type": "input",
                "language": "pl",
                "required": False,
                "default": "",
                "parser": "text",
            },
        ],
    }

    payload = build_create_payload(
        config,
        {
            "EAN": "5904804578169",
            "NAME_EN": "Vivo sideboard",
            "NAME_PL": "Komoda Vivo",
        },
    )

    assert payload["elements"] == [
        {"type": "input", "name": "EAN", "value": "5904804578169", "language": None},
        {
            "type": "localizedfields",
            "name": "localizedfields",
            "value": [
                {"type": "input", "name": "name", "value": "Vivo sideboard", "language": "en"},
                {"type": "input", "name": "name", "value": "Komoda Vivo", "language": "pl"},
            ],
        },
    ]


def test_ean_filter_is_structured_and_rejects_unsafe_names():
    assert build_ean_filter("5904804578169", ["EAN"]) == {"EAN": "5904804578169"}
    assert build_ean_filter(
        "5904804578169", ["EAN", "Towar_powiazany_z_SKU"]
    ) == {
        "$or": [
            {"EAN": "5904804578169"},
            {"Towar_powiazany_z_SKU": "5904804578169"},
        ]
    }
    with pytest.raises(ValueError, match="Niepoprawna nazwa pola"):
        build_ean_filter("5904804578169", ["EAN OR 1=1"])


def test_object_list_uses_q_and_object_class_not_removed_parameters():
    captured = {}

    def opener(request, timeout, context):
        captured["url"] = request.full_url
        return FakeResponse({"success": True, "data": []})

    client = PimcoreClient(
        {"base_url": "http://pimcore.example.test", "api_key": "secret"},
        opener=opener,
    )
    client.object_list({"EAN": "5904804578169"}, object_class="product", limit=2)

    query = parse_qs(urlsplit(captured["url"]).query)
    assert json.loads(query["q"][0]) == {"EAN": "5904804578169"}
    assert query["objectClass"] == ["product"]
    assert query["limit"] == ["2"]
    assert "condition" not in query
    assert "className" not in query


class DiscoveryClient:
    def classes(self):
        return {"data": [{"id": "7", "name": "product"}, {"id": 3, "name": "category"}]}

    def class_definition(self, class_id):
        assert str(class_id) == "7"
        return {
            "data": {
                "layoutDefinitions": {
                    "children": [
                        {"fieldtype": "input", "name": "EAN", "title": "EAN"},
                        {"fieldtype": "numeric", "name": "totalWeight", "title": "Waga"},
                        {
                            "fieldtype": "localizedfields",
                            "name": "localizedfields",
                            "children": [
                                {
                                    "fieldtype": "input",
                                    "name": "MANUFACTURER_NAME",
                                    "title": "Producent",
                                }
                            ],
                        },
                        {"fieldtype": "manyToManyObjectRelation", "name": "related"},
                    ]
                }
            }
        }

    def object_list(self, query_filter=None, object_class="", limit=100, offset=0):
        assert query_filter == {"type": "folder"}
        assert object_class == ""
        return {"data": [{"id": 6626, "type": "folder", "fullPath": "/Produkty"}]}


def test_discovery_normalizes_classes_fields_and_folders():
    client = DiscoveryClient()

    assert discover_classes(client) == [
        {"id": "3", "name": "category"},
        {"id": "7", "name": "product"},
    ]
    assert discover_fields(client, "7") == [
        {
            "name": "EAN",
            "label": "EAN",
            "type": "input",
            "language": None,
            "parser": "text",
            "supported": True,
            "unsupported_reason": "",
        },
        {
            "name": "MANUFACTURER_NAME",
            "label": "Producent [en]",
            "type": "input",
            "language": "en",
            "parser": "text",
            "supported": True,
            "unsupported_reason": "",
        },
        {
            "name": "MANUFACTURER_NAME",
            "label": "Producent [pl]",
            "type": "input",
            "language": "pl",
            "parser": "text",
            "supported": True,
            "unsupported_reason": "",
        },
        {
            "name": "related",
            "label": "related",
            "type": "manytomanyobjectrelation",
            "language": None,
            "parser": "",
            "supported": False,
            "unsupported_reason": "Typ manytomanyobjectrelation nie jest obslugiwany.",
        },
        {
            "name": "totalWeight",
            "label": "Waga",
            "type": "numeric",
            "language": None,
            "parser": "decimal_comma",
            "supported": True,
            "unsupported_reason": "",
        },
    ]
    assert discover_folders(client) == [
        {"id": 6626, "path": "/Produkty", "key": "Produkty"}
    ]


def test_folder_discovery_falls_back_to_unfiltered_list_after_server_error():
    client = Mock()
    client.object_list.side_effect = [
        PimcoreApiError("Pimcore zwrocil HTTP 500.", "/webservice/rest/object-list", 500),
        {
            "data": [
                {"id": 1, "type": "object", "fullPath": "/Produkt"},
                {"id": 6626, "type": "folder", "fullPath": "/Produkty"},
            ]
        },
    ]

    assert discover_folders(client) == [
        {"id": 6626, "path": "/Produkty", "key": "Produkty"}
    ]
    assert client.object_list.call_args_list[0].args == ({"type": "folder"},)
    assert client.object_list.call_args_list[1].args == ()


def test_folder_discovery_returns_empty_list_when_fallback_finds_nothing():
    original = PimcoreApiError(
        "Pimcore zwrocil HTTP 500.",
        "/webservice/rest/object-list",
        500,
        response_excerpt="folder filter failed",
    )
    client = Mock()
    client.object_list.side_effect = [
        original,
        {"data": [{"id": 1, "type": "object", "fullPath": "/Produkt"}]},
    ]

    assert discover_folders(client) == []


def test_extract_object_id_accepts_pimcore_response_variants():
    assert extract_object_id({"id": 44}) == 44
    assert extract_object_id({"data": {"id": "45"}}) == 45
    assert extract_object_id({"object": {"id": 46}}) == 46


def test_lookup_searches_whole_class_without_parent_filter():
    client = Mock()
    client.object_list.return_value = {
        "data": [{"id": 91, "fullPath": "/Other/5904804578169"}]
    }

    found = find_product_by_ean(
        PRODUCT_CONFIG,
        "5904804578169",
        client=client,
    )

    assert found["id"] == 91
    args, kwargs = client.object_list.call_args
    assert args == ({"EAN": "5904804578169"},)
    assert kwargs == {"object_class": "Product", "limit": 2}


@pytest.mark.parametrize(
    "record",
    [{"id": "91"}, {"o_id": "91"}, {"objectId": "91"}],
)
def test_object_identity_accepts_known_id_variants(record):
    assert normalize_object_identity(record)["id"] == 91


def test_lookup_rejects_match_without_positive_object_id():
    client = Mock()
    client.object_list.return_value = {
        "data": [{"fullPath": "/Products/broken"}]
    }

    with pytest.raises(ValueError, match="ID"):
        find_product_by_ean(
            PRODUCT_CONFIG,
            "5904804578169",
            client=client,
        )


class ProductClient:
    def __init__(self, existing=None):
        self.existing = existing or []
        self.created = []

    def object_list(self, query_filter=None, object_class="", limit=2, offset=0):
        return {"data": self.existing}

    def create_object(self, payload):
        self.created.append(payload)
        return {"data": {"id": 91}}

    def object_by_id(self, object_id):
        return {"data": {"id": object_id, "key": "ABC-1", "fullPath": "/Produkty/ABC-1"}}


PRODUCT_CONFIG = {
    "enabled": True,
    "class_name": "Product",
    "parent_id": "123",
    "published": True,
    "object_key_template": "{EAN}",
    "existence_fields": ["EAN", "Towar_powiazany_z_SKU"],
    "field_mappings": [
        {
            "source": "SKU",
            "pimcore_field": "SKU",
            "type": "input",
            "required": True,
            "parser": "text",
        },
        {
            "source": "EAN",
            "pimcore_field": "EAN",
            "type": "input",
            "required": True,
            "parser": "text",
        },
    ],
}


EDIT_OBJECT = {
    "id": 91,
    "parentId": 6626,
    "key": "5904804578169",
    "className": "product",
    "published": True,
    "modificationDate": 100,
    "elements": [
        {"type": "input", "name": "EAN", "value": "5904804578169", "language": None},
        {"type": "input", "name": "SKU", "value": "OLD", "language": None},
        {"type": "input", "name": "untouched", "value": "KEEP", "language": None},
    ],
}


def test_fetch_product_for_edit_returns_only_configured_values():
    client = Mock()
    client.object_by_id.return_value = {"data": EDIT_OBJECT}

    result = fetch_product_for_edit(PRODUCT_CONFIG, 91, client=client)

    assert result["object"]["id"] == 91
    assert result["marker"] == "100"
    assert result["values"] == {"SKU": "OLD", "EAN": "5904804578169"}


def test_merge_product_update_preserves_parent_and_unconfigured_elements():
    payload = merge_product_update_payload(
        PRODUCT_CONFIG,
        EDIT_OBJECT,
        {"SKU": "NEW", "EAN": "5904804578169"},
    )

    by_name = {item["name"]: item for item in payload["elements"]}
    assert payload["parentId"] == 6626
    assert payload["key"] == "5904804578169"
    assert payload["published"] is True
    assert by_name["SKU"]["value"] == "NEW"
    assert by_name["untouched"]["value"] == "KEEP"


def test_merge_product_update_replaces_nested_localized_value_only():
    config = json.loads(json.dumps(PRODUCT_CONFIG))
    config["field_mappings"].append(
        {
            "source": "NAME_EN",
            "label": "Nazwa EN",
            "pimcore_field": "name",
            "type": "input",
            "language": "en",
            "required": False,
            "default": "",
            "parser": "text",
        }
    )
    current = json.loads(json.dumps(EDIT_OBJECT))
    current["elements"].append(
        {
            "type": "localizedfields",
            "name": "localizedfields",
            "value": [
                {"type": "input", "name": "name", "language": "en", "value": "Old"},
                {"type": "input", "name": "name", "language": "pl", "value": "Bez zmian"},
            ],
        }
    )

    payload = merge_product_update_payload(
        config,
        current,
        {"SKU": "OLD", "EAN": "5904804578169", "NAME_EN": ""},
    )

    localized = next(item for item in payload["elements"] if item["name"] == "localizedfields")
    by_language = {item["language"]: item["value"] for item in localized["value"]}
    assert by_language == {"en": "", "pl": "Bez zmian"}


def test_merge_product_update_adds_missing_localized_value_under_container():
    config = json.loads(json.dumps(PRODUCT_CONFIG))
    config["field_mappings"].append(
        {
            "source": "MANUFACTURER_NAME_EN",
            "label": "Producent EN",
            "pimcore_field": "MANUFACTURER_NAME",
            "type": "input",
            "language": "en",
            "required": False,
            "default": "",
            "parser": "text",
        }
    )
    current = json.loads(json.dumps(EDIT_OBJECT))
    current["elements"].append(
        {
            "type": "localizedfields",
            "name": "localizedfields",
            "value": [
                {
                    "type": "input",
                    "name": "MANUFACTURER_NAME",
                    "language": "pl",
                    "value": "Stary producent",
                }
            ],
        }
    )

    payload = merge_product_update_payload(
        config,
        current,
        {
            "SKU": "OLD",
            "EAN": "5904804578169",
            "MANUFACTURER_NAME_EN": "New manufacturer",
        },
    )

    top_level_names = [
        item["name"]
        for item in payload["elements"]
        if item.get("name") == "MANUFACTURER_NAME"
    ]
    localized = next(item for item in payload["elements"] if item["name"] == "localizedfields")
    by_language = {item["language"]: item["value"] for item in localized["value"]}
    assert top_level_names == []
    assert by_language == {"pl": "Stary producent", "en": "New manufacturer"}


def test_update_product_rejects_changed_marker_before_put():
    client = Mock()
    changed = dict(EDIT_OBJECT, modificationDate=101)
    client.object_by_id.return_value = {"data": changed}

    with pytest.raises(PimcoreConflictError, match="zmieniony"):
        update_product(
            PRODUCT_CONFIG,
            91,
            "100",
            {"SKU": "NEW", "EAN": "5904804578169"},
            client=client,
            emit=lambda *args, **kwargs: None,
        )

    client.update_object.assert_not_called()


def test_update_product_uses_content_marker_when_timestamp_is_missing():
    original = {key: value for key, value in EDIT_OBJECT.items() if key != "modificationDate"}
    load_client = Mock()
    load_client.object_by_id.return_value = {"data": original}
    loaded = fetch_product_for_edit(PRODUCT_CONFIG, 91, client=load_client)

    changed = json.loads(json.dumps(original))
    changed["elements"][1]["value"] = "CHANGED"
    update_client = Mock()
    update_client.object_by_id.return_value = {"data": changed}
    with pytest.raises(PimcoreConflictError, match="zmieniony"):
        update_product(
            PRODUCT_CONFIG,
            91,
            loaded["marker"],
            {"SKU": "NEW", "EAN": "5904804578169"},
            client=update_client,
            emit=lambda *args, **kwargs: None,
        )

    update_client.update_object.assert_not_called()


def test_update_product_returns_only_verified_field_changes():
    verified = json.loads(json.dumps(EDIT_OBJECT))
    verified["modificationDate"] = 101
    next(item for item in verified["elements"] if item["name"] == "SKU")["value"] = "NEW"
    client = Mock()
    client.object_by_id.side_effect = [{"data": EDIT_OBJECT}, {"data": verified}]
    client.update_object.return_value = {"success": True}

    result = update_product(
        PRODUCT_CONFIG,
        91,
        "100",
        {"SKU": "NEW", "EAN": "5904804578169"},
        client=client,
        emit=lambda *args, **kwargs: None,
    )

    assert result["change_set"] == {
        "kind": "updated",
        "fields": [
            {"key": "SKU", "label": "SKU", "before": "OLD", "after": "NEW"}
        ],
    }


def test_update_product_classifies_verified_noop_as_synchronized():
    verified = json.loads(json.dumps(EDIT_OBJECT))
    verified["modificationDate"] = 101
    client = Mock()
    client.object_by_id.side_effect = [{"data": EDIT_OBJECT}, {"data": verified}]
    client.update_object.return_value = {"success": True}

    result = update_product(
        PRODUCT_CONFIG,
        91,
        "100",
        {"SKU": "OLD", "EAN": "5904804578169"},
        client=client,
        emit=lambda *args, **kwargs: None,
    )

    assert result["change_set"] == {"kind": "synchronized", "fields": []}


def test_find_product_by_ean_returns_normalized_identity():
    client = ProductClient(existing=[{"id": 51, "key": "ABC", "fullPath": "/Produkty/ABC"}])

    result = find_product_by_ean(PRODUCT_CONFIG, "5904804578169", client=client)

    assert result == {"id": 51, "key": "ABC", "path": "/Produkty/ABC"}


def test_find_product_rejects_ambiguous_ean_results():
    client = Mock()
    client.object_list.return_value = {
        "data": [
            {"id": 91, "key": "5904804578169", "fullPath": "/Produkty/5904804578169"},
            {"id": 92, "key": "duplicate", "fullPath": "/Produkty/duplicate"},
        ]
    }

    with pytest.raises(ValueError, match="wiele produktow"):
        find_product_by_ean(
            PRODUCT_CONFIG,
            "5904804578169",
            client=client,
        )


def test_create_product_rechecks_duplicate_before_post():
    client = ProductClient(existing=[{"id": 51, "key": "ABC", "fullPath": "/Produkty/ABC"}])

    result = create_product(
        PRODUCT_CONFIG,
        {"SKU": "ABC-1", "EAN": "5904804578169"},
        client=client,
        emit=lambda *args, **kwargs: None,
    )

    assert result["duplicate"] is True
    assert result["object"]["id"] == 51
    assert client.created == []


def test_create_product_reports_existing_duplicate_as_success_data():
    events = []
    result = create_product(
        PRODUCT_CONFIG,
        {"SKU": "ABC-1", "EAN": "5904804578169"},
        client=ProductClient(
            existing=[{"id": 51, "key": "ABC", "fullPath": "/Produkty/ABC"}]
        ),
        emit=lambda *args, **kwargs: events.append((args, kwargs)),
    )

    assert result["duplicate"] is True
    assert events[0][0][1] == "success"
    assert events[0][1]["status"] == "existing"


def test_create_product_posts_when_ean_is_missing():
    client = ProductClient()

    result = create_product(
        PRODUCT_CONFIG,
        {"SKU": "ABC-1", "EAN": "5904804578169"},
        client=client,
        emit=lambda *args, **kwargs: None,
    )

    assert result["created"] is True
    assert result["object"] == {"id": 91, "key": "ABC-1", "path": "/Produkty/ABC-1"}
    assert client.created[0]["published"] is True


def test_create_product_returns_initial_value_change_set():
    result = create_product(
        PRODUCT_CONFIG,
        {"SKU": "ABC-1", "EAN": "5904804578169"},
        client=ProductClient(),
        emit=lambda *args, **kwargs: None,
    )

    assert result["change_set"] == {
        "kind": "created",
        "fields": [
            {
                "key": "EAN",
                "label": "EAN",
                "before": None,
                "after": "5904804578169",
            },
            {"key": "SKU", "label": "SKU", "before": None, "after": "ABC-1"},
        ],
    }


def test_client_reports_status_endpoint_and_response_without_api_key():
    def opener(request, timeout, context):
        raise HTTPError(
            request.full_url,
            403,
            "Forbidden",
            {},
            BytesIO(b'{"message":"denied"}'),
        )

    client = PimcoreClient(
        {"base_url": "http://pimcore.example.test", "api_key": "secret-key"},
        opener=opener,
    )

    with pytest.raises(PimcoreApiError) as raised:
        client.server_info()

    assert raised.value.status_code == 403
    assert raised.value.endpoint == "/webservice/rest/server-info"
    assert "denied" in raised.value.response_excerpt
    assert "secret-key" not in str(raised.value.as_dict())


class DiagnosticClient:
    def server_info(self):
        return {"success": True, "data": {"version": "6.6.11"}}

    def classes(self):
        return {"data": [{"id": 1, "name": "Product"}]}

    def class_definition(self, class_id):
        assert class_id == 1
        return {
            "data": {
                "layoutDefinitions": {
                    "children": [
                        {"fieldtype": "input", "name": "SKU"},
                        {"fieldtype": "input", "name": "EAN"},
                    ]
                }
            }
        }

    def object_by_id(self, object_id):
        assert str(object_id) == "123"
        return {"success": True, "data": {"id": 123, "type": "folder"}}

    def object_list(self, query_filter=None, object_class="", limit=2, offset=0):
        assert object_class == "Product"
        assert query_filter == {"EAN": "0000000000000"}
        return {"data": []}


def test_settings_test_returns_individual_checks_and_missing_field_error():
    config = {
        "enabled": True,
        "base_url": "http://pimcore.example.test",
        "api_key": "secret",
        "class_name": "Product",
        "parent_id": "123",
        "object_key_template": "{SKU}",
        "existence_fields": ["EAN"],
        "field_mappings": [
            {
                "source": "EAN",
                "pimcore_field": "EAN",
                "type": "input",
                "required": True,
                "parser": "text",
            },
            {
                "source": "SKU",
                "pimcore_field": "SKU",
                "type": "input",
                "required": True,
                "parser": "text",
            },
            {
                "source": "WEIGHT",
                "pimcore_field": "MISSING_WEIGHT",
                "type": "numeric",
                "required": False,
                "parser": "decimal_comma",
            },
        ],
    }

    report = run_settings_test(config, client=DiagnosticClient())
    checks = {item["key"]: item for item in report["checks"]}

    assert report["ok"] is False
    assert checks["server_info"]["status"] == "ok"
    assert checks["class_exists"]["status"] == "ok"
    assert checks["mapping_fields"]["status"] == "error"
    assert "MISSING_WEIGHT" in checks["mapping_fields"]["message"]
    assert checks["create_permission"]["status"] == "info"
    assert report["total_ms"] >= 0


def test_settings_test_reports_all_local_errors_without_api_key():
    report = run_settings_test(
        {
            "base_url": "http://pimcore.example.test",
            "api_key": "",
            "parent_id": "",
            "object_key_template": "{SKU}",
            "field_mappings": [],
        }
    )
    checks = {item["key"]: item for item in report["checks"]}

    assert report["ok"] is False
    assert checks["api_key"]["status"] == "error"
    assert checks["mapping_local"]["status"] == "error"
    assert checks["parent"]["status"] == "error"
    assert checks["test_form_schema"]["status"] == "error"
    assert checks["create_permission"]["status"] == "info"


VALID_DIAGNOSTIC_CONFIG = {
    "enabled": True,
    "base_url": "http://pimcore.example.test",
    "api_key": "secret",
    "class_name": "Product",
    "parent_id": "123",
    "object_key_template": "{EAN}",
    "existence_fields": ["EAN"],
    "field_mappings": [
        {
            "source": "EAN",
            "pimcore_field": "EAN",
            "type": "input",
            "required": True,
            "parser": "text",
        }
    ],
}


@pytest.mark.parametrize(
    ("status_code", "expected_key"),
    [(401, "server_info"), (403, "server_info")],
)
def test_settings_test_preserves_auth_http_status(status_code, expected_key):
    error = PimcoreApiError(
        "Klucz API zostal odrzucony.",
        "/webservice/rest/server-info",
        status_code=status_code,
        kind="http",
    )
    client = Mock()
    client.server_info.side_effect = error

    report = run_settings_test(
        {"enabled": True, "base_url": "http://pimcore.example.test", "api_key": "secret"},
        client=client,
    )

    item = next(check for check in report["checks"] if check["key"] == expected_key)
    assert item["status"] == "error"
    assert item["status_code"] == status_code
    assert item["endpoint"] == "/webservice/rest/server-info"


def test_settings_test_reports_network_timeout():
    client = DiagnosticClient()
    client.server_info = Mock(
        side_effect=PimcoreApiError(
            "Przekroczono czas polaczenia.",
            "/webservice/rest/server-info",
            kind="network",
        )
    )

    report = run_settings_test(VALID_DIAGNOSTIC_CONFIG, client=client)

    item = next(check for check in report["checks"] if check["key"] == "server_info")
    assert item["status"] == "error"
    assert "czas" in item["message"]


def test_settings_test_reports_missing_class():
    class MissingClassClient(DiagnosticClient):
        def classes(self):
            return {"data": [{"id": 2, "name": "Other"}]}

    report = run_settings_test(VALID_DIAGNOSTIC_CONFIG, client=MissingClassClient())

    item = next(check for check in report["checks"] if check["key"] == "class_exists")
    assert item["status"] == "error"
    assert "Product" in item["message"]


def test_settings_test_skips_remote_dependents_after_missing_class():
    class MissingClassClient(DiagnosticClient):
        def classes(self):
            return {"data": [{"id": 2, "name": "other"}]}

        def object_list(self, *args, **kwargs):
            raise AssertionError("object-list must be skipped without a valid class")

    report = run_settings_test(VALID_DIAGNOSTIC_CONFIG, client=MissingClassClient())
    checks = {item["key"]: item for item in report["checks"]}

    assert checks["class_exists"]["status"] == "error"
    assert checks["mapping_fields"]["status"] == "skipped"
    assert checks["object_list"]["status"] == "skipped"


def test_settings_test_marks_empty_mapping_as_error_not_success():
    report = run_settings_test(
        {
            "base_url": "http://pimcore.example.test",
            "api_key": "secret",
            "class_name": "product",
            "parent_id": "6626",
            "field_mappings": [],
        },
        client=Mock(),
    )
    checks = {item["key"]: item for item in report["checks"]}

    assert checks["test_form_schema"]["status"] == "error"
    assert checks["mapping_fields"]["status"] == "skipped"


def test_api_error_keeps_sanitized_audit_detail_out_of_public_dict():
    secret = "api-secret-value"

    def opener(request, timeout, context):
        raise HTTPError(
            request.full_url,
            500,
            "failure",
            {},
            BytesIO(f"full trace {secret} final-line".encode("utf-8")),
        )

    client = PimcoreClient(
        {"base_url": "http://pimcore.example.test", "api_key": secret},
        opener=opener,
    )
    with pytest.raises(PimcoreApiError) as captured:
        client.server_info()

    error = captured.value
    assert "final-line" in error.response_detail
    assert secret not in error.response_detail
    assert "response_detail" not in error.as_dict()
    assert error.as_dict(include_detail=True)["response_detail"] == error.response_detail


def test_settings_test_reports_bad_parent_with_endpoint():
    class BadParentClient(DiagnosticClient):
        def object_by_id(self, object_id):
            raise PimcoreApiError(
                "Nie znaleziono parent_id.",
                f"/webservice/rest/object/id/{object_id}",
                status_code=404,
                kind="http",
            )

    report = run_settings_test(VALID_DIAGNOSTIC_CONFIG, client=BadParentClient())

    item = next(check for check in report["checks"] if check["key"] == "parent")
    assert item["status"] == "error"
    assert item["status_code"] == 404
    assert item["endpoint"].endswith("/123")


def test_client_reports_invalid_json_body():
    class RawResponse(FakeResponse):
        def __init__(self):
            self.status = 200
            self._body = b"not-json"

    client = PimcoreClient(
        {"base_url": "http://pimcore.example.test", "api_key": "secret"},
        opener=lambda request, timeout, context: RawResponse(),
    )

    with pytest.raises(PimcoreApiError) as raised:
        client.server_info()

    assert raised.value.kind == "json"
    assert raised.value.status_code == 200
    assert raised.value.response_excerpt == "not-json"
