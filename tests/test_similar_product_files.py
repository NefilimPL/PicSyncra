from picsyncra import similar_product_files
from picsyncra.similar_product_files import (
    _merged_names,
    find_similar_file_candidates,
    normalize_similar_file_settings,
)
from picsyncra import common, config
from copy import deepcopy
from unittest.mock import patch


def slot_defs():
    return [
        {"prefix": "01", "label": "Instrukcja"},
        {"prefix": "02", "label": "Detal"},
        {"prefix": "03", "label": "Zblizenie"},
        {"prefix": "04", "label": "Nie do wykrywania"},
    ]


def enabled_slots():
    return {"enabled": True, "slot_prefixes": ["01", "02", "03"]}


def white_product():
    return {
        "name": "Maggiori",
        "type_name": "Komoda",
        "model": "MA01",
        "color1": "White",
        "color2": "",
        "color3": "",
        "extra": "",
    }


def _write_product_file(tmp_path, color, prefix, content, filename=None, extra="NO-LED"):
    folder = tmp_path / "MAGGIORI" / "KOMODA" / "MA01" / color / extra
    folder.mkdir(parents=True, exist_ok=True)
    (folder / (filename or f"5901234567890_{prefix}_MAIN.jpg")).write_bytes(content)


def test_other_color_candidate_stays_in_its_source_slot(tmp_path):
    _write_product_file(tmp_path, "BLACK", "01", b"black")

    candidates = find_similar_file_candidates(
        str(tmp_path), white_product(), slot_defs(), enabled_slots()
    )

    assert [(item.source_prefix, item.target_prefix) for item in candidates] == [("01", "01")]


def test_distinct_same_slot_files_overflow_and_duplicate_digest_is_skipped(tmp_path):
    _write_product_file(tmp_path, "BLACK", "01", b"black")
    _write_product_file(tmp_path, "OAK", "01", b"oak")
    _write_product_file(tmp_path, "GREY", "01", b"black")

    candidates = find_similar_file_candidates(
        str(tmp_path), white_product(), slot_defs(), enabled_slots()
    )

    assert [(item.source_color_segment, item.target_prefix) for item in candidates] == [
        ("BLACK", "01"),
        ("OAK", "02"),
    ]


def test_occupied_or_non_permitted_slots_are_not_used(tmp_path):
    _write_product_file(tmp_path, "BLACK", "01", b"black")
    _write_product_file(tmp_path, "BLACK", "04", b"not-selected")

    candidates = find_similar_file_candidates(
        str(tmp_path),
        white_product(),
        slot_defs(),
        enabled_slots(),
        occupied_prefixes={"01", "02"},
    )

    assert [item.target_prefix for item in candidates] == ["03"]


def test_color_order_does_not_turn_the_same_multicolor_variant_into_a_candidate(tmp_path):
    _write_product_file(tmp_path, "WHITE-BLACK", "01", b"same-colors")
    product = {**white_product(), "color1": "Black", "color2": "White"}

    candidates = find_similar_file_candidates(
        str(tmp_path), product, slot_defs(), enabled_slots()
    )

    assert candidates == []


def test_base_identity_finds_candidates_before_colour_and_extra_are_chosen(tmp_path):
    _write_product_file(tmp_path, "BLACK", "01", b"black")
    _write_product_file(tmp_path, "WHITE", "01", b"white")
    product = {**white_product(), "color1": "", "extra": ""}

    candidates = find_similar_file_candidates(
        str(tmp_path), product, slot_defs(), enabled_slots()
    )

    assert [item.source_color_segment for item in candidates] == ["BLACK", "WHITE"]


def test_explicit_extra_keeps_led_and_no_led_separate(tmp_path):
    _write_product_file(tmp_path, "BLACK", "01", b"led", extra="LED")
    _write_product_file(tmp_path, "WHITE", "01", b"no-led", extra="NO-LED")
    product = {**white_product(), "color1": "OAK", "extra": "LED"}

    candidates = find_similar_file_candidates(
        str(tmp_path), product, slot_defs(), enabled_slots()
    )

    assert [item.source_color_segment for item in candidates] == ["BLACK"]


def test_unchanged_candidate_uses_cached_digest(tmp_path, monkeypatch):
    _write_product_file(tmp_path, "BLACK", "01", b"black")
    calls = 0
    original = similar_product_files._read_digest

    def count_reads(path):
        nonlocal calls
        calls += 1
        return original(path)

    monkeypatch.setattr(similar_product_files, "_read_digest", count_reads)
    find_similar_file_candidates(str(tmp_path), white_product(), slot_defs(), enabled_slots())
    find_similar_file_candidates(str(tmp_path), white_product(), slot_defs(), enabled_slots())

    assert calls == 1


def test_normalize_similar_settings_defaults_disabled_and_removes_unknown_slots():
    slots = [{"prefix": "01", "label": "Instrukcja"}, {"prefix": "02", "label": "Detal"}]

    assert normalize_similar_file_settings(
        {"enabled": True, "slot_prefixes": ["1", "99", "02", "02"]}, slots
    ) == {"enabled": True, "slot_prefixes": ["01", "02"]}
    assert normalize_similar_file_settings(None, slots) == {
        "enabled": False,
        "slot_prefixes": [],
    }


def test_config_save_normalizes_similar_settings_after_slot_definitions():
    payload = deepcopy(common.DEFAULT_CONFIG)
    payload[common.SLOT_DEFS_KEY] = [{"prefix": "01", "label": "Instrukcja"}]
    payload[common.SIMILAR_FILE_DETECTION_KEY] = {
        "enabled": True,
        "slot_prefixes": ["1", "99"],
    }

    with (
        patch.object(config, "_active_sqlite_store", return_value=None),
        patch.object(config, "_write_json_atomic") as write_atomic,
    ):
        config.save_config(payload)

    assert write_atomic.call_args.args[1][common.SIMILAR_FILE_DETECTION_KEY] == {
        "enabled": True,
        "slot_prefixes": ["01"],
    }


def test_stale_index_segments_cannot_escape_the_product_identity_directory(tmp_path):
    outside = tmp_path / "MAGGIORI" / "KOMODA" / "OTHER" / "NO-LED"
    outside.mkdir(parents=True)
    (outside / "5901234567890_01_MAIN.jpg").write_bytes(b"outside")

    class StaleIndex:
        def get_colors(self, *_args):
            return ["../OTHER"]

        def get_extras(self, *_args):
            return ["NO-LED"]

        def get_product_files(self, *_args):
            return ["5901234567890_01_MAIN.jpg"]

    candidates = find_similar_file_candidates(
        str(tmp_path), white_product(), slot_defs(), enabled_slots(), file_index=StaleIndex()
    )

    assert candidates == []


def test_live_scandir_spelling_wins_over_case_colliding_index_spelling():
    assert _merged_names(["black"], ["BLACK"]) == ["BLACK"]
