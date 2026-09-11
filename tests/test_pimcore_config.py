from picsyncra.pimcore_config import (
    PIMCORE_API_KEY,
    PIMCORE_SETTINGS_KEY,
    field_mapping_issues,
    infer_field_mapping,
    normalize_field_mapping,
    normalize_pimcore_settings,
    parse_mapping_value,
)


def test_normalize_pimcore_settings_preserves_configured_base_url_without_metadata():
    configured_url = "http://pimcore.example.test"

    result = normalize_pimcore_settings({"base_url": configured_url})

    assert result["base_url"] == configured_url


def test_normalize_pimcore_settings_cleans_mappings_and_bounds_timeout():
    result = normalize_pimcore_settings(
        {
            "enabled": 1,
            "base_url": " http://pimcore.example.test/ ",
            PIMCORE_API_KEY: "secret-key",
            "class_name": " Product ",
            "parent_id": "123",
            "timeout_seconds": 999,
            "existence_fields": ["EAN", "EAN", "Bad field", "Towar_powiazany_z_SKU"],
            "field_mappings": [
                {
                    "source": "EAN",
                    "label": "Kod EAN",
                    "pimcore_field": "EAN",
                    "type": "input",
                    "required": True,
                    "parser": "text",
                },
                {"source": "", "pimcore_field": "ignored"},
            ],
        }
    )

    assert result["base_url"] == "http://pimcore.example.test"
    assert result["timeout_seconds"] == 120
    assert result["existence_fields"] == ["EAN"]
    assert result["field_mappings"] == [
        {
            "source": "EAN",
            "label": "Kod EAN",
            "pimcore_field": "EAN",
            "type": "input",
            "language": None,
            "required": True,
            "default": "",
            "parser": "text",
            "value_template": "",
            "sql_query": "",
            "sql_profile_id": "",
            "translate": False,
            "target_language": None,
            "ocr_validation": False,
            "layout_group": "",
            "layout_order": 0,
        }
    ]


def test_normalize_pimcore_settings_builds_export_columns_from_mappings():
    result = normalize_pimcore_settings(
        {
            "field_mappings": [
                {"source": "EAN", "pimcore_field": "ean", "type": "input"},
                {"source": "STOCK", "pimcore_field": "stock", "type": "numeric"},
            ]
        }
    )

    assert result["export_columns"] == [
        {"type": "field", "pimcore_field": "ean", "header": "ean"},
        {"type": "field", "pimcore_field": "stock", "header": "stock"},
    ]


def test_normalize_mapping_discards_legacy_dimension_property():
    mapping = normalize_field_mapping(
        {
            "source": "WIDTH",
            "pimcore_field": "width",
            "image_dimension": {"slot": "15", "dimension": "width"},
        }
    )

    assert mapping["ocr_validation"] is False
    assert "image_dimension" not in mapping


def test_mapping_validation_rejects_unconfigured_image_source():
    issues = field_mapping_issues(
        [
            {
                "source": "WIDTH",
                "pimcore_field": "width",
                "type": "input",
                "value_template": "{IMAGE_DIMENSION:15:WIDTH|keep}",
            }
        ]
    )

    assert any("Nieznane zrodlo IMAGE_DIMENSION:15:WIDTH" in issue for issue in issues)


def test_normalize_pimcore_settings_treats_empty_export_columns_as_default_layout():
    result = normalize_pimcore_settings(
        {
            "field_mappings": [
                {"source": "EAN", "pimcore_field": "ean", "type": "input"}
            ],
            "export_columns": [],
        }
    )

    assert result["export_columns"] == [
        {"type": "field", "pimcore_field": "ean", "header": "ean"}
    ]


def test_normalize_pimcore_settings_keeps_custom_export_headers_and_blank_columns():
    result = normalize_pimcore_settings(
        {
            "field_mappings": [
                {"source": "EAN", "pimcore_field": "ean", "type": "input"}
            ],
            "export_columns": [
                {"type": "blank", "header": "parentId"},
                {"type": "field", "pimcore_field": "ean", "header": "kod"},
            ],
        }
    )

    assert result["export_columns"] == [
        {"type": "blank", "header": "parentId"},
        {"type": "field", "pimcore_field": "ean", "header": "kod"},
    ]


def test_normalize_pimcore_settings_discards_invalid_export_field_positions():
    result = normalize_pimcore_settings(
        {
            "field_mappings": [
                {"source": "EAN", "pimcore_field": "ean", "type": "input"}
            ],
            "export_columns": [
                {"type": "field", "pimcore_field": "missing", "header": "missing"},
                {"type": "field", "pimcore_field": "ean", "header": "ean"},
                {"type": "field", "pimcore_field": "ean", "header": "duplicate"},
                {"type": "unexpected", "header": "ignored"},
                {"type": "blank", "header": ""},
            ],
        }
    )

    assert result["export_columns"] == [
        {"type": "field", "pimcore_field": "ean", "header": "ean"},
        {"type": "blank", "header": ""},
    ]


def test_mapping_parsers_accept_polish_csv_values():
    assert parse_mapping_value(" 62,5 ", "decimal_comma") == 62.5
    assert parse_mapping_value("12", "integer") == 12
    assert parse_mapping_value("tak", "boolean") is True
    assert parse_mapping_value("nie", "boolean") is False
    assert parse_mapping_value("  ", "empty_to_null") is None


def test_default_section_keeps_integration_disabled():
    result = normalize_pimcore_settings(None)
    assert result[PIMCORE_API_KEY] == ""
    assert result["enabled"] is False
    assert result["base_url"] == ""
    assert result["class_name"] == ""
    assert PIMCORE_SETTINGS_KEY == "pimcore"


def test_guided_setup_defaults_hide_technical_choices():
    result = normalize_pimcore_settings({})

    assert result["setup_complete"] is False
    assert result["class_id"] == ""
    assert result["class_name"] == ""
    assert result["parent_path"] == ""
    assert result["object_key_template"] == "{EAN}"
    assert result["timeout_seconds"] == 30


def test_complete_legacy_configuration_infers_setup_complete():
    result = normalize_pimcore_settings(
        {
            "base_url": "http://pimcore.example.test",
            "api_key": "secret",
            "class_name": "product",
            "parent_id": "6626",
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
    )

    assert result["setup_complete"] is True
    assert result["existence_fields"] == ["EAN"]
    assert result["object_key_template"] == "{EAN}"


def test_explicit_disabled_complete_setup_stays_complete():
    result = normalize_pimcore_settings(
        {
            "setup_complete": True,
            "enabled": False,
            "class_name": "product",
            "parent_id": "6626",
            "field_mappings": [],
        }
    )

    assert result["setup_complete"] is True
    assert result["enabled"] is False


def test_infer_field_mapping_uses_class_type_and_locks_ean():
    ean = infer_field_mapping(
        source="EAN",
        label="EAN",
        pimcore_field="eanCode",
        field_type="input",
        required=False,
    )
    weight = infer_field_mapping(
        source="TOTAL WEIGHT",
        label="Waga calkowita",
        pimcore_field="totalWeight",
        field_type="numeric",
        required=False,
    )

    assert ean == {
        "source": "EAN",
        "label": "EAN",
        "pimcore_field": "eanCode",
        "type": "input",
        "language": None,
        "required": True,
        "default": "",
        "parser": "text",
        "value_template": "",
        "sql_query": "",
        "sql_profile_id": "",
        "translate": False,
        "target_language": None,
        "ocr_validation": False,
        "layout_group": "",
        "layout_order": 0,
    }
    assert weight["parser"] == "decimal_comma"


def test_mapping_layout_options_round_trip_and_ignore_obsolete_width():
    result = normalize_pimcore_settings(
        {
            "field_mappings": [
                {
                    "source": "TITLE",
                    "label": "Tytul",
                    "pimcore_field": "title",
                    "type": "input",
                    "parser": "text",
                    "layout_group": " Dane podstawowe*: ",
                    "layout_order": "2",
                    "layout_width": "half",
                },
                {
                    "source": "DESCRIPTION",
                    "label": "Opis",
                    "pimcore_field": "description",
                    "type": "textarea",
                    "parser": "text",
                    "layout_order": "bledna",
                    "layout_width": "wide",
                },
            ]
        }
    )

    assert result["field_mappings"][0]["layout_group"] == "Dane podstawowe"
    assert result["field_mappings"][0]["layout_order"] == 2
    assert "layout_width" not in result["field_mappings"][0]
    assert result["field_mappings"][1]["layout_group"] == ""
    assert result["field_mappings"][1]["layout_order"] == 1
    assert "layout_width" not in result["field_mappings"][1]


def test_field_mapping_issues_report_exact_row_and_problem():
    issues = field_mapping_issues(
        [
            {"source": "", "pimcore_field": "EAN", "type": "input", "parser": "text"},
            {
                "source": "WEIGHT",
                "pimcore_field": "TOTAL_WEIGHT",
                "type": "input",
                "parser": "decimal_comma",
            },
            {
                "source": "WEIGHT",
                "pimcore_field": "OTHER_WEIGHT",
                "type": "numeric",
                "parser": "decimal_comma",
            },
        ]
    )
    assert issues == [
        "Mapowanie 1: brak kolumny zrodlowej.",
        "Mapowanie 2: parser decimal_comma nie pasuje do typu input.",
        "Mapowanie 3: zduplikowana kolumna zrodlowa WEIGHT.",
    ]


def test_mapping_template_options_round_trip():
    result = normalize_pimcore_settings(
        {
            "field_mappings": [
                {
                    "source": "TITLE",
                    "label": "Tytul",
                    "pimcore_field": "title",
                    "type": "input",
                    "parser": "text",
                    "value_template": "{NAZWA} - {TYP}",
                    "translate": True,
                    "target_language": "en",
                }
            ]
        }
    )

    mapping = result["field_mappings"][0]
    assert mapping["value_template"] == "{NAZWA} - {TYP}"
    assert mapping["sql_query"] == ""
    assert mapping["sql_profile_id"] == ""
    assert mapping["translate"] is True
    assert mapping["target_language"] == "en"


def test_sql_mapping_options_round_trip():
    result = normalize_pimcore_settings(
        {
            "field_mappings": [
                {
                    "source": "STOCK",
                    "label": "Stan",
                    "pimcore_field": "stock",
                    "type": "input",
                    "parser": "text",
                    "value_template": " SQL ",
                    "sql_query": " SELECT qty FROM stock WHERE ean = {ean} ",
                    "sql_profile_id": " stock-db ",
                }
            ]
        }
    )

    mapping = result["field_mappings"][0]
    assert mapping["value_template"] == "SQL"
    assert mapping["sql_query"] == "SELECT qty FROM stock WHERE ean = {ean}"
    assert mapping["sql_profile_id"] == "stock-db"


def test_field_mapping_issues_validate_sql_mode_and_skip_template_parser():
    issues = field_mapping_issues(
        [
            {
                "source": "STOCK",
                "pimcore_field": "stock",
                "type": "input",
                "parser": "text",
                "value_template": "SQL",
                "sql_query": "SELECT qty FROM stock WHERE ean = {ean}",
                "sql_profile_id": "stock-db",
            }
        ],
        sql_profiles=[{"id": "stock-db"}],
    )

    assert issues == []
def test_field_mapping_issues_require_sql_query_and_profile_for_sql_mode():
    issues = field_mapping_issues(
        [
            {
                "source": "STOCK",
                "pimcore_field": "stock",
                "type": "input",
                "parser": "text",
                "value_template": "SQL",
                "sql_query": "",
                "sql_profile_id": "missing",
            }
        ],
        sql_profiles=[{"id": "stock-db"}],
    )

    assert issues == [
        "Mapowanie 1: SQL wymaga zapytania.",
        "Mapowanie 1: nieznany profil SQL missing.",
    ]


def test_field_mapping_issues_require_sql_query_and_profile_for_sql_placeholder():
    issues = field_mapping_issues(
        [
            {
                "source": "STOCK",
                "pimcore_field": "stock",
                "type": "input",
                "parser": "text",
                "value_template": "Stan: {SQL|number:0}",
                "sql_query": "",
                "sql_profile_id": "",
            }
        ],
        sql_profiles=[{"id": "stock-db"}],
    )

    assert issues == [
        "Mapowanie 1: SQL wymaga zapytania.",
        "Mapowanie 1: wybierz profil SQL.",
    ]


def test_field_mapping_issues_accept_sql_placeholder_as_template_source():
    issues = field_mapping_issues(
        [
            {
                "source": "STOCK",
                "pimcore_field": "stock",
                "type": "input",
                "parser": "text",
                "value_template": "Stan: {SQL|number:0}",
                "sql_query": "SELECT qty FROM stock WHERE ean = {ean}",
                "sql_profile_id": "stock-db",
            }
        ],
        sql_profiles=[{"id": "stock-db"}],
    )

    assert issues == []
def test_invalid_template_is_reported_by_mapping_validation():
    issues = field_mapping_issues(
        [
            {
                "source": "TITLE",
                "pimcore_field": "title",
                "type": "input",
                "parser": "text",
                "value_template": "{NAZWA",
            }
        ]
    )

    assert issues == ["Mapowanie 1: Niezamkniety placeholder."]


def test_translation_requires_template_and_target_language():
    issues = field_mapping_issues(
        [
            {
                "source": "TITLE",
                "pimcore_field": "title",
                "type": "input",
                "parser": "text",
                "value_template": "{NAZWA}",
                "translate": True,
                "target_language": "",
            }
        ]
    )

    assert issues == ["Mapowanie 1: wybierz jezyk docelowy tlumaczenia."]


def test_field_mapping_issues_allow_same_target_for_different_languages():
    issues = field_mapping_issues(
        [
            {
                "source": "NAME_EN",
                "pimcore_field": "name",
                "type": "input",
                "parser": "text",
                "language": "en",
            },
            {
                "source": "NAME_PL",
                "pimcore_field": "name",
                "type": "input",
                "parser": "text",
                "language": "pl",
            },
        ]
    )

    assert issues == []
