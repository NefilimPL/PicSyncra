from picsyncra.services.ocr_values import (
    comparison_key,
    normalize_entered_ocr_value,
    ocr_values_match,
)


def test_comparison_preserves_decimals_and_special_character_kind():
    assert normalize_entered_ocr_value("120,9/140.1") == "120.9/140.1"
    assert comparison_key("120,9/140.1") == "120.9?140.1"
    assert comparison_key("120-140") == "120?140"
    assert ocr_values_match("120,9/140.1", "120.9/140,1")


def test_comparison_preserves_special_character_count():
    assert comparison_key("120--140") == "120??140"
    assert not ocr_values_match("120--140", "120-140")


def test_ocr_letters_are_removed_but_structure_is_retained():
    assert comparison_key("W 120/140 mm") == "120?140"
    assert comparison_key("brak") == ""


def test_comparison_preserves_decimal_digits_but_unifies_separator():
    assert comparison_key("23,4") == "23.4"
    assert comparison_key("23.4") == "23.4"
    assert not ocr_values_match("23,4", "23")
