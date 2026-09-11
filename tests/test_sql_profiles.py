from __future__ import annotations

from copy import deepcopy

from picsyncra import common
from picsyncra.sql_profiles import (
    DEFAULT_SQL_PROFILE_ID,
    SQL_PROFILES_KEY,
    normalize_sql_profiles,
    public_sql_profiles,
    resolve_sql_profile,
)


def test_default_profile_is_derived_from_existing_sql_config():
    cfg = deepcopy(common.DEFAULT_CONFIG)
    cfg[common.p] = common.K
    cfg[common.K][common.c] = "mysql.local"
    cfg[common.K][common.b] = "catalog"
    cfg[common.K][common.N] = "writer"
    cfg[common.K][common.M] = "secret"

    profiles = normalize_sql_profiles(cfg)
    default = profiles[0]

    assert default["id"] == DEFAULT_SQL_PROFILE_ID
    assert default["label"] == "Domyslny"
    assert default["usage"] == "slots"
    assert default["locked"] is True
    assert default["type"] == "mysql"
    assert default["host"] == "mysql.local"
    assert default["database"] == "catalog"
    assert default["user"] == "writer"
    assert default["password"] == "secret"


def test_additional_profiles_are_cleaned_and_public_view_hides_passwords():
    cfg = deepcopy(common.DEFAULT_CONFIG)
    cfg[SQL_PROFILES_KEY] = [
        {
            "id": " Stock DB ",
            "label": " Stock ",
            "type": "mssql",
            "host": "sql.local",
            "database": "erp",
            "user": "reader",
            "password": "secret",
            "enabled": True,
        },
        {"id": "default", "label": "bad", "host": "ignored"},
        {"id": "", "label": "empty"},
    ]

    profiles = normalize_sql_profiles(cfg)
    stock = resolve_sql_profile(profiles, "stock-db")
    public = public_sql_profiles(profiles)

    assert stock["usage"] == "pimcore_sql"
    assert stock["locked"] is False
    assert stock["enabled"] is True
    assert public[1]["id"] == "stock-db"
    assert public[1]["user_set"] is True
    assert public[1]["password_set"] is True
    assert "reader" not in str(public[1])
    assert "user" not in public[1]
    assert "password" not in public[1]
