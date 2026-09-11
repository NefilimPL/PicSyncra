from picsyncra.history_changes import field_changes, file_changes, history_change_set


def test_field_changes_describe_created_fields_in_stable_order() -> None:
    assert field_changes(None, {"name": "Chair", "ean": "590"}, {"name": "Name"}) == [
        {"key": "ean", "label": "ean", "before": None, "after": "590"},
        {"key": "name", "label": "Name", "before": None, "after": "Chair"},
    ]


def test_field_changes_preserve_display_values_and_skip_normalized_matches() -> None:
    assert field_changes(
        {"name": " Chair ", "model": "Old", "extra": "same"},
        {"name": "chair", "model": "New", "extra": "same"},
        {"model": "Model"},
    ) == [
        {"key": "model", "label": "Model", "before": "Old", "after": "New"},
    ]


def test_file_changes_describe_replacement_with_sizes_and_time() -> None:
    result = file_changes(
        existing_photos=[
            {"prefix": "03", "filename": "old.png", "path": "old.png", "size_bytes": 900}
        ],
        saved_files=[
            {
                "prefix": "03",
                "source_name": "upload.jpg",
                "filename": "new.png",
                "source_size_bytes": 1200,
                "size_bytes": 800,
                "elapsed_ms": 42,
                "operation": "process_image",
                "content_fit": True,
            }
        ],
        delete_requests=[],
        migrated_prefixes=[],
    )
    assert result == [
        {
            "slot": "03",
            "operation": "replaced",
            "before_name": "old.png",
            "after_name": "new.png",
            "source_name": "upload.jpg",
            "before_size_bytes": 900,
            "source_size_bytes": 1200,
            "after_size_bytes": 800,
            "elapsed_ms": 42,
            "processing_operation": "process_image",
            "content_fit": True,
        }
    ]


def test_file_changes_cover_added_deleted_and_migrated_slots() -> None:
    result = file_changes(
        existing_photos=[
            {"prefix": "04", "ftp_filename": "old-ftp.jpg"},
            {"prefix": "05", "filename": "move.jpg", "size_bytes": 77},
        ],
        saved_files=[
            {
                "prefix": "03",
                "source_name": "new.jpg",
                "filename": "590_03.jpg",
                "source_size_bytes": 10,
                "size_bytes": 9,
                "elapsed_ms": 1,
                "operation": "copy",
                "content_fit": False,
                "preprocessed": True,
            },
            {
                "prefix": "05",
                "source_name": "move.jpg",
                "filename": "590_05.jpg",
                "source_size_bytes": 77,
                "size_bytes": 77,
                "elapsed_ms": 2,
                "operation": "copy",
                "content_fit": False,
            },
        ],
        delete_requests=[{"prefix": "04"}, {"prefix": "05", "migration": True}],
        migrated_prefixes=["05"],
    )

    assert result == [
        {
            "slot": "03",
            "operation": "added",
            "before_name": None,
            "after_name": "590_03.jpg",
            "source_name": "new.jpg",
            "before_size_bytes": None,
            "source_size_bytes": 10,
            "after_size_bytes": 9,
            "elapsed_ms": 1,
            "processing_operation": "copy",
            "content_fit": False,
            "preprocessed": True,
        },
        {
            "slot": "04",
            "operation": "deleted",
            "before_name": "old-ftp.jpg",
            "before_size_bytes": None,
        },
        {
            "slot": "05",
            "operation": "migrated",
            "before_name": "move.jpg",
            "after_name": "590_05.jpg",
            "source_name": "move.jpg",
            "before_size_bytes": 77,
            "source_size_bytes": 77,
            "after_size_bytes": 77,
            "elapsed_ms": 2,
            "processing_operation": "copy",
            "content_fit": False,
        },
    ]


def test_file_changes_preserve_deleted_ftp_name_for_replacement_without_scan_metadata() -> None:
    result = file_changes(
        existing_photos=[],
        saved_files=[{"prefix": "03", "filename": "new.jpg"}],
        delete_requests=[{"prefix": "03", "ftp_filename": "old-ftp.jpg"}],
        migrated_prefixes=[],
    )

    assert result[0]["operation"] == "replaced"
    assert result[0]["before_name"] == "old-ftp.jpg"
    assert result[0]["before_size_bytes"] is None


def test_history_change_set_attaches_server_slot_evidence_to_each_changed_file() -> None:
    result = history_change_set(
        existing_entry={"name": "Chair"},
        saved_entry={"name": "Chair"},
        existing_photos=[{"prefix": "03", "filename": "old.jpg"}],
        saved_files=[
            {"prefix": "03", "filename": "new.jpg", "elapsed_ms": 12}
        ],
        delete_requests=[{"prefix": "03", "ftp_filename": "590_03.jpg"}],
        migrated_prefixes=[],
        integrations={
            "local": {
                "slot_results": [
                    {"slot": "03", "status": "saved", "elapsed_ms": 12}
                ]
            },
            "ftp": {
                "slot_results": [
                    {
                        "slot": "03",
                        "upload_status": "uploaded",
                        "delete_status": "deleted",
                        "elapsed_ms": 44,
                    }
                ]
            },
            "sql": {
                "slot_results": [
                    {
                        "slot": "03",
                        "operation": "update",
                        "status": "updated",
                        "elapsed_ms": 7,
                    }
                ]
            },
        },
    )

    assert result["files"][0]["evidence"] == {
        "local": {"slot": "03", "status": "saved", "elapsed_ms": 12},
        "ftp": {
            "slot": "03",
            "upload_status": "uploaded",
            "delete_status": "deleted",
            "elapsed_ms": 44,
        },
        "sql": {
            "slot": "03",
            "operation": "update",
            "status": "updated",
            "elapsed_ms": 7,
        },
    }


def test_history_change_set_preserves_multiple_local_operations_for_replacement() -> None:
    result = history_change_set(
        existing_entry={"name": "Chair"},
        saved_entry={"name": "Chair"},
        existing_photos=[{"prefix": "03", "filename": "old.jpg"}],
        saved_files=[{"prefix": "03", "filename": "new.jpg", "elapsed_ms": 12}],
        delete_requests=[{"prefix": "03", "local_path": "old.jpg"}],
        migrated_prefixes=[],
        integrations={
            "local": {
                "slot_results": [
                    {"slot": "03", "operation": "save", "status": "saved", "elapsed_ms": 12},
                    {"slot": "03", "operation": "delete", "status": "error", "elapsed_ms": 4},
                ]
            }
        },
    )

    assert result["files"][0]["evidence"]["local"] == [
        {"slot": "03", "operation": "save", "status": "saved", "elapsed_ms": 12},
        {"slot": "03", "operation": "delete", "status": "error", "elapsed_ms": 4},
    ]


def test_history_change_set_keeps_each_slot_operation_for_all_integrations() -> None:
    result = history_change_set(
        existing_entry={"name": "Chair"},
        saved_entry={"name": "Chair"},
        existing_photos=[{"prefix": "03", "filename": "old.jpg"}],
        saved_files=[{"prefix": "03", "filename": "new.jpg"}],
        delete_requests=[{"prefix": "03", "ftp_filename": "old.jpg"}],
        migrated_prefixes=[],
        integrations={
            "local": {"slot_results": [
                {"slot": "03", "operation": "save", "status": "saved", "elapsed_ms": 12},
                {"slot": "03", "operation": "delete", "status": "deleted", "elapsed_ms": 4},
            ]},
            "ftp": {"slot_results": [
                {"slot": "03", "operation": "upload", "status": "uploaded", "elapsed_ms": 16},
                {"slot": "03", "operation": "delete", "status": "deleted", "elapsed_ms": 8},
            ]},
            "sql": {"slot_results": [
                {"slot": "03", "operation": "update", "status": "updated", "elapsed_ms": 3},
            ]},
        },
    )

    assert result["files"][0]["evidence"] == {
        "local": [
            {"slot": "03", "operation": "save", "status": "saved", "elapsed_ms": 12},
            {"slot": "03", "operation": "delete", "status": "deleted", "elapsed_ms": 4},
        ],
        "ftp": [
            {"slot": "03", "operation": "upload", "status": "uploaded", "elapsed_ms": 16},
            {"slot": "03", "operation": "delete", "status": "deleted", "elapsed_ms": 8},
        ],
        "sql": {"slot": "03", "operation": "update", "status": "updated", "elapsed_ms": 3},
    }


def test_history_change_set_classifies_created_updated_and_synchronized() -> None:
    created = history_change_set(
        existing_entry=None,
        saved_entry={"name": "Chair"},
        existing_photos=[],
        saved_files=[],
        delete_requests=[],
        migrated_prefixes=[],
        integrations={"sql": {"status": "ok"}},
    )
    updated = history_change_set(
        existing_entry={"name": "Old"},
        saved_entry={"name": "New"},
        existing_photos=[],
        saved_files=[],
        delete_requests=[],
        migrated_prefixes=[],
        integrations={},
        pimcore={"kind": "updated"},
    )
    synchronized = history_change_set(
        existing_entry={"name": "Same"},
        saved_entry={"name": "same"},
        existing_photos=[],
        saved_files=[],
        delete_requests=[],
        migrated_prefixes=[],
        integrations={},
    )

    assert created == {
        "kind": "created",
        "fields": [{"key": "name", "label": "name", "before": None, "after": "Chair"}],
        "files": [],
        "integrations": {"sql": {"status": "ok"}},
        "pimcore": {},
    }
    assert updated["kind"] == "updated"
    assert updated["fields"] == [
        {"key": "name", "label": "name", "before": "Old", "after": "New"}
    ]
    assert updated["pimcore"] == {"kind": "updated"}
    assert synchronized["kind"] == "synchronized"
    assert synchronized["fields"] == []
    assert synchronized["files"] == []


def test_history_change_set_ignores_derived_fields_absent_from_saved_product_shape() -> None:
    existing = {
        "product_id": "PRD-1",
        "ean": "5901234567890",
        "name": "Chair",
        "type_name": "Armchair",
        "model": "A1",
        "color1": "Blue",
        "color2": "",
        "color3": "",
        "extra": "",
        "label": "Chair | Armchair | A1 | Blue - 5901234567890",
    }
    saved = {key: value for key, value in existing.items() if key != "label"}

    result = history_change_set(
        existing_entry=existing,
        saved_entry=saved,
        existing_photos=[],
        saved_files=[],
        delete_requests=[],
        migrated_prefixes=[],
        integrations={},
    )

    assert result["kind"] == "synchronized"
    assert result["fields"] == []
