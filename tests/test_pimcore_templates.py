import pytest
from concurrent.futures import ThreadPoolExecutor
import threading
import time

from picsyncra.pimcore_templates import (
    SourceDefinition,
    TemplateError,
    build_source_catalog,
    generate_test_values,
    render_mapping_templates,
    render_template,
)


def resolver(values):
    return lambda source: values.get(source.casefold(), "")


@pytest.mark.parametrize(
    ("template", "values", "expected"),
    [
        (
            "{NAZWA} - {TYP} {KOLOR 1}(/{KOLOR 2})",
            {"nazwa": "Vivo", "typ": "sideboard", "kolor 1": "white", "kolor 2": "black"},
            "VIVO - SIDEBOARD WHITE/BLACK",
        ),
        (
            "{Nazwa} - {Typ} {kolor 1}(/{kolor 2})",
            {"nazwa": "VIVO", "typ": "SIDEBOARD", "kolor 1": "WHITE", "kolor 2": "BLACK"},
            "Vivo - Sideboard white/black",
        ),
        ("{KOLOR 1}(/{KOLOR 2})", {"kolor 1": "white", "kolor 2": ""}, "WHITE"),
        (r"\({NAZWA|keep}\)", {"nazwa": "Vivo"}, "(Vivo)"),
        ('{MODEL|trim|replace:"_"," "|upper}', {"model": "  ab_cd  "}, "AB CD"),
        ('{BRAK|default:"wartosc"|title}', {}, "Wartosc"),
        ('{TekSt|substring:1,3}', {"tekst": "abcdefgh"}, "bcd"),
        ('{TekSt|truncate:4,"..."}', {"tekst": "abcdefgh"}, "abcd..."),
        ('{TekSt|normalize_spaces}', {"tekst": "  a   b  "}, "a b"),
        ('{TekSt|strip_diacritics}', {"tekst": "żółć"}, "zolc"),
        ('{TekSt|slug}', {"tekst": "  Żółty   stół  "}, "zolty-stol"),
        ('{LICZBA|number:2,","," "}', {"liczba": "1234,5"}, "1 234,50"),
    ],
)
def test_render_template_supports_literals_groups_case_and_functions(template, values, expected):
    assert render_template(template, resolver(values)) == expected


def test_render_template_evaluates_math_expression_with_pimcore_placeholders():
    template = (
        "{PIMCORE:parcel_1_weight|keep}+"
        "({PIMCORE:parcel_1_width|keep}/"
        "{PIMCORE:parcel_1_depth|keep}/"
        "{PIMCORE:parcel_1_height|keep})*4"
    )

    assert render_template(
        template,
        resolver(
            {
                "pimcore:parcel_1_weight": "10",
                "pimcore:parcel_1_width": "8",
                "pimcore:parcel_1_depth": "2",
                "pimcore:parcel_1_height": "2",
            }
        ),
    ) == "18"


def test_render_template_keeps_math_parentheses_for_precedence():
    assert render_template(
        "({A|keep}+{B|keep})*{C|keep}",
        resolver({"a": "2", "b": "3", "c": "4"}),
    ) == "20"


def test_render_template_accepts_decimal_comma_in_math_expression():
    assert render_template(
        "{A|keep}+{B|keep}",
        resolver({"a": "1,5", "b": "2.25"}),
    ) == "3.75"


def test_render_template_leaves_non_math_text_with_operator_unchanged():
    assert render_template("Waga: {A|keep}+2", resolver({"a": "3"})) == "Waga: 3+2"


def test_render_template_rejects_math_division_by_zero():
    with pytest.raises(TemplateError) as captured:
        render_template("{A|keep}/{B|keep}", resolver({"a": "1", "b": "0"}))

    assert captured.value.code == "math_division_by_zero"


def test_render_template_calculates_oblicz_block_inside_mixed_text():
    template = (
        'oblicz(2*(5415413+{PIMCORE:parcel_11_weight|keep|default:"1110"})) '
        '(/{PRODUCT:model|keep})'
    )

    assert render_template(
        template,
        resolver(
            {
                "pimcore:parcel_11_weight": "",
                "product:model": "M-20",
            }
        ),
    ) == "10833046 /M-20"


def test_render_template_calculates_calc_alias():
    assert render_template(
        "calc(2*(2+{PIMCORE:parcel_11_weight|keep}))",
        resolver({"pimcore:parcel_11_weight": "3"}),
    ) == "10"


@pytest.mark.parametrize(
    ("template", "values", "expected"),
    [
        ("{WIDTH|filled}", {"width": "120"}, "1"),
        ("{WIDTH|filled}", {"width": " \t "}, "0"),
        (
            '{DEPTH|any_filled:"HEIGHT","WEIGHT","WIDTH"}',
            {"depth": "", "height": "", "weight": "4", "width": ""},
            "1",
        ),
        (
            '{DEPTH|count_filled:"HEIGHT","WEIGHT","WIDTH"}',
            {"depth": "10", "height": " ", "weight": "4", "width": "20"},
            "3",
        ),
        ('{WIDTH|if_filled:"TAK","NIE"}', {"width": "120"}, "TAK"),
        ('{WIDTH|if_filled:"TAK","NIE"}', {"width": ""}, "NIE"),
    ],
)
def test_render_template_supports_presence_functions(template, values, expected):
    assert render_template(template, resolver(values)) == expected


def test_render_template_counts_eleven_parcels_by_filled_width():
    template = "+".join(
        f"{{PIMCORE:parcel_{index}_width|filled}}" for index in range(1, 12)
    )
    values = {
        f"pimcore:parcel_{index}_width": "120" if index in {1, 2} else ""
        for index in range(1, 12)
    }

    assert render_template(template, resolver(values)) == "2"


@pytest.mark.parametrize(
    ("template", "code"),
    [
        ('{WIDTH|filled:"nie"}', "invalid_arguments"),
        ('{WIDTH|if_filled:"TAK"}', "invalid_arguments"),
    ],
)
def test_presence_functions_validate_arguments(template, code):
    with pytest.raises(TemplateError) as captured:
        render_template(template, resolver({"width": "120"}))

    assert captured.value.code == code


def test_render_template_rejects_text_inside_oblicz_block():
    with pytest.raises(TemplateError) as captured:
        render_template(
            "oblicz(2+{PRODUCT:model|keep})",
            resolver({"product:model": "M-20"}),
        )

    assert captured.value.code == "invalid_math_expression"


@pytest.mark.parametrize(
    ("template", "code"),
    [
        ("{NAZWA", "unclosed_placeholder"),
        ("({NAZWA}", "unclosed_group"),
        ("(tekst)", "condition_without_placeholder"),
        ("{NAZWA|unknown}", "unknown_function"),
        ("{NAZWA|substring:x,2}", "invalid_arguments"),
    ],
)
def test_invalid_templates_raise_structured_errors(template, code):
    with pytest.raises(TemplateError) as captured:
        render_template(template, resolver({"nazwa": "Vivo"}))

    assert captured.value.code == code
    assert captured.value.position >= 0


MAPPINGS = [
    {
        "source": "EAN",
        "label": "EAN",
        "type": "input",
        "parser": "text",
        "value_template": "",
    },
    {
        "source": "COLOR",
        "label": "Kolor",
        "type": "input",
        "parser": "text",
        "value_template": "{KOLOR 1}(/{KOLOR 2})",
    },
    {
        "source": "TITLE",
        "label": "Tytul",
        "type": "input",
        "parser": "text",
        "value_template": "{NAZWA} - {PIMCORE:COLOR}",
    },
]


def test_catalog_supports_friendly_technical_and_qualified_sources():
    catalog = build_source_catalog(MAPPINGS)

    assert catalog.resolve("NAZWA") == "PRODUCT:name"
    assert catalog.resolve("PIMCORE:TITLE") == "PIMCORE:TITLE"
    assert catalog.resolve("title") == "PIMCORE:TITLE"


def test_mapping_templates_render_in_dependency_order():
    result = render_mapping_templates(
        MAPPINGS,
        product_values={
            "name": "Vivo",
            "color1": "white",
            "color2": "black",
        },
        pimcore_values={"EAN": "5904804578169"},
    )

    assert result.values["COLOR"] == "WHITE/BLACK"
    assert result.values["TITLE"] == "VIVO - WHITE/BLACK"
    assert result.order == ("COLOR", "TITLE")


def test_mapping_templates_keep_submitted_dependency_values_during_edit():
    mappings = [
        {
            "source": "PARCEL_1_WIDTH",
            "type": "input",
            "value_template": "{PRODUCT:extra|keep}",
        },
        {
            "source": "PARCELS_QTY",
            "type": "input",
            "value_template": "{PIMCORE:PARCEL_1_WIDTH|filled}",
        },
    ]

    result = render_mapping_templates(
        mappings,
        product_values={"extra": ""},
        pimcore_values={"PARCEL_1_WIDTH": "120", "PARCELS_QTY": "4"},
        targets=["PARCELS_QTY"],
        preserve_submitted_dependencies=True,
    )

    assert result.values["PARCELS_QTY"] == "1"
    assert result.order == ("PARCELS_QTY",)


def test_mapping_cycle_is_rejected_with_sources():
    mappings = [
        {"source": "A", "type": "input", "value_template": "{PIMCORE:B}"},
        {"source": "B", "type": "input", "value_template": "{PIMCORE:A}"},
    ]

    with pytest.raises(TemplateError) as captured:
        render_mapping_templates(mappings, product_values={}, pimcore_values={})

    assert captured.value.code == "dependency_cycle"
    assert "A" in captured.value.message
    assert "B" in captured.value.message


def test_external_provider_can_register_source_without_template_changes():
    mappings = [
        {
            "source": "STOCK_TEXT",
            "type": "input",
            "value_template": "Stan: {SQL:STOCK}",
        }
    ]
    source = SourceDefinition("SQL:stock", "Stan SQL", "sql", ("SQL:STOCK",))

    result = render_mapping_templates(
        mappings,
        product_values={},
        pimcore_values={},
        extra_sources=[source],
        extra_values={"SQL:stock": "12"},
    )

    assert result.values["STOCK_TEXT"] == "Stan: 12"


def test_test_values_are_fresh_field_specific_and_type_compatible():
    mappings = MAPPINGS + [
        {"source": "WEIGHT", "type": "numeric", "parser": "decimal_comma"},
        {"source": "ACTIVE", "type": "checkbox", "parser": "boolean"},
    ]

    first = generate_test_values(mappings)
    second = generate_test_values(mappings)

    assert first["EAN"].isdigit()
    assert len(first["EAN"]) == 13
    assert first["EAN"] != second["EAN"]
    assert first["COLOR"] != first["TITLE"]
    assert "," in first["WEIGHT"]
    assert first["ACTIVE"] in {"tak", "nie"}


def test_test_values_keep_ean_fresh_when_clock_does_not_advance(monkeypatch):
    monkeypatch.setattr(
        "picsyncra.pimcore_templates.time.time_ns",
        lambda: 1234567890,
    )
    mappings = [{"source": "EAN", "type": "input", "parser": "text"}]

    first = generate_test_values(mappings)
    second = generate_test_values(mappings)

    assert first["EAN"].isdigit()
    assert len(first["EAN"]) == 13
    assert first["EAN"] != second["EAN"]


def test_template_operation_classification_uses_placeholder_dependencies():
    from picsyncra.services.template_execution import classify_template_operation

    assert classify_template_operation(
        {"sql_query": "SELECT {PRODUCT:ean}"}
    ).independent
    assert not classify_template_operation(
        {"sql_query": "SELECT {PIMCORE:title}"}
    ).independent


def test_independent_operations_are_bounded_and_keep_input_order():
    from picsyncra.services.template_execution import execute_independent_operations

    active = 0
    peak = 0
    lock = threading.Lock()

    def operation(index: int) -> int:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return index

    assert execute_independent_operations(
        [lambda index=index: operation(index) for index in range(8)],
        max_workers=4,
    ) == list(range(8))
    assert peak <= 4
