from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest

from picsyncra import common, config, email_settings, web_data
from picsyncra.email_settings import (
    EMAIL_CLIENT_SECRET,
    EMAIL_SETTINGS_KEY,
    EMAIL_SMTP_PASSWORD,
    default_email_settings,
    normalize_email_address,
    normalize_email_settings,
    public_email_settings,
)


def test_normalize_email_address_preserves_local_case_and_lowercases_domain() -> None:
    assert (
        normalize_email_address(" User.Name+tag@Example.COM ")
        == "User.Name+tag@example.com"
    )


@pytest.mark.parametrize(
    "local",
    [
        "name+tag",
        "x!$%&'*+/=?^_`{|}~-",
    ],
)
def test_normalize_email_address_accepts_existing_ascii_atom_characters(
    local: str,
) -> None:
    assert normalize_email_address(f"{local}@Example.COM") == f"{local}@example.com"


def test_normalize_email_address_rejects_very_long_untrusted_input() -> None:
    with pytest.raises(ValueError, match="Niepoprawny adres e-mail"):
        normalize_email_address(f"{'!' * 1_000_000}@example.com")


def test_email_settings_has_no_local_part_regular_expression() -> None:
    source = Path(email_settings.__file__).read_text(encoding="utf-8")

    assert "_EMAIL_LOCAL_RE" not in source


@pytest.mark.parametrize(
    "value",
    [
        "\x00a@example.com",
        "a@exam\x1fple.com",
        "a@example.com\x7f",
        "a@example.com\r\nBcc: victim@example.com",
        "a@.com",
        "a@example.",
        "a@foo..com",
        "a@-foo.com",
        "a@foo-.com",
        "a@foo_bar.com",
        f"a@{'x' * 64}.com",
        f"a@{'.'.join(['x' * 63] * 4)}",
        ".a@example.com",
        "a.@example.com",
        "a..b@example.com",
        "a b@example.com",
        f"{'a' * 65}@example.com",
        f"{'a' * 64}@{'.'.join(['x' * 63] * 3)}",
    ],
)
def test_normalize_email_address_rejects_unsafe_or_malformed_address(
    value: str,
) -> None:
    with pytest.raises(ValueError, match="Niepoprawny adres e-mail"):
        normalize_email_address(value)


@pytest.mark.parametrize("value", [False, "false", "0", "off", "no", ""])
def test_normalize_email_settings_parses_false_like_boolean_values(value: object) -> None:
    result = normalize_email_settings(
        {
            "fallback_enabled": value,
            "rules": {
                "error": {
                    "enabled": value,
                    "include_actor": value,
                }
            },
        }
    )

    assert result["fallback_enabled"] is False
    assert result["rules"]["error"]["enabled"] is False
    assert result["rules"]["error"]["include_actor"] is False


@pytest.mark.parametrize("value", [True, "true", "1", "on", "yes"])
def test_normalize_email_settings_parses_true_like_boolean_values(value: object) -> None:
    result = normalize_email_settings(
        {
            "fallback_enabled": value,
            "rules": {
                "warning": {
                    "enabled": value,
                    "include_actor": value,
                }
            },
        }
    )

    assert result["fallback_enabled"] is True
    assert result["rules"]["warning"]["enabled"] is True
    assert result["rules"]["warning"]["include_actor"] is True


def test_normalize_email_settings_builds_both_channels_and_rules() -> None:
    result = normalize_email_settings(
        {
            "primary_channel": "smtp",
            "fallback_enabled": True,
            "smtp": {
                "host": "smtp.example",
                "port": "587",
                "security": "starttls",
            },
            "rules": {
                "error": {
                    "enabled": True,
                    "recipients": "a@example.com, b@example.com",
                    "include_actor": True,
                }
            },
        }
    )

    assert result["primary_channel"] == "smtp"
    assert result["fallback_enabled"] is True
    assert result["smtp"]["port"] == 587
    assert result["smtp"]["host"] == "smtp.example"
    assert result["rules"]["error"]["recipients"] == [
        "a@example.com",
        "b@example.com",
    ]
    assert result["rules"]["error"]["enabled"] is True
    assert result["rules"]["error"]["include_actor"] is True
    assert set(result["rules"]) == {"info", "warning", "error", "critical"}


def test_normalize_email_settings_uses_a_safe_configurable_daily_summary_time() -> None:
    assert default_email_settings()["daily_summary_time"] == "16:00"
    assert normalize_email_settings({})["daily_summary_time"] == "16:00"
    assert normalize_email_settings({"daily_summary_time": "09:05"})[
        "daily_summary_time"
    ] == "09:05"
    assert normalize_email_settings({"daily_summary_time": "9:5"})[
        "daily_summary_time"
    ] == "16:00"
    # Europe/Warsaw skips 02:00–02:59 during the spring DST transition.
    assert normalize_email_settings({"daily_summary_time": "02:30"})[
        "daily_summary_time"
    ] == "16:00"


def test_normalize_email_settings_bounds_enums_port_and_recipient_lists() -> None:
    result = normalize_email_settings(
        {
            "primary_channel": "invalid",
            "smtp": {
                "port": 999_999,
                "security": "invalid",
                "username": 123,
            },
            "rules": {
                "warning": {
                    "recipients": [" first@example.com ", "", 12],
                }
            },
        }
    )

    assert result["primary_channel"] == "entra"
    assert result["smtp"]["security"] == "starttls"
    assert result["smtp"]["port"] == 65_535
    assert result["smtp"]["username"] == "123"
    assert result["rules"]["warning"]["recipients"] == [
        "first@example.com",
    ]
    assert normalize_email_settings({"smtp": {"port": 0}})["smtp"]["port"] == 1
    assert normalize_email_settings({"smtp": {"port": "bad"}})["smtp"]["port"] == 587


def test_normalize_email_settings_validates_and_casefold_deduplicates_recipients() -> None:
    result = normalize_email_settings(
        {
            "rules": {
                "critical": {
                    "enabled": True,
                    "recipients": [
                        " First.User@Example.COM ",
                        "first.user@example.com",
                        "SECOND@example.com",
                        " second@EXAMPLE.COM ",
                        "bad address",
                    ],
                    "include_actor": True,
                }
            }
        }
    )

    assert result["rules"]["critical"] == {
        "enabled": True,
        "recipients": ["First.User@example.com", "SECOND@example.com"],
        "include_actor": True,
    }


def test_web_settings_update_and_snapshot_canonicalize_crafted_recipient_list() -> None:
    current = deepcopy(common.DEFAULT_CONFIG)
    current[EMAIL_SETTINGS_KEY] = default_email_settings()
    submitted = default_email_settings()
    submitted["rules"]["error"] = {
        "enabled": True,
        "recipients": [
            " Admin@Example.COM ",
            "admin@example.com",
            "",
            "Ops@example.com",
        ],
        "include_actor": True,
    }

    with (
        patch.object(config, "CONFIG", current),
        patch.object(web_data.config, "CONFIG", current),
        patch.object(web_data, "save_config"),
        patch.object(web_data.config, "initialize_config"),
        patch.object(
            web_data,
            "settings_snapshot",
            side_effect=lambda: {
                EMAIL_SETTINGS_KEY: public_email_settings(
                    current[EMAIL_SETTINGS_KEY]
                )
            },
        ),
    ):
        snapshot = web_data.update_settings({EMAIL_SETTINGS_KEY: submitted})

    expected = ["Admin@example.com", "Ops@example.com"]
    assert current[EMAIL_SETTINGS_KEY]["rules"]["error"]["recipients"] == expected
    assert snapshot[EMAIL_SETTINGS_KEY]["rules"]["error"] == {
        "enabled": True,
        "recipients": expected,
        "include_actor": True,
    }


def test_web_settings_update_rejects_non_empty_invalid_rule_recipient() -> None:
    current = deepcopy(common.DEFAULT_CONFIG)
    current[EMAIL_SETTINGS_KEY] = default_email_settings()
    submitted = default_email_settings()
    submitted["rules"]["warning"] = {
        "enabled": True,
        "recipients": "valid@example.com, bad address",
        "include_actor": False,
    }

    with (
        patch.object(config, "CONFIG", current),
        patch.object(web_data.config, "CONFIG", current),
        patch.object(web_data, "save_config") as save,
    ):
        with pytest.raises(ValueError, match="warning"):
            web_data.update_settings({EMAIL_SETTINGS_KEY: submitted})

    save.assert_not_called()
    assert current[EMAIL_SETTINGS_KEY]["rules"]["warning"]["recipients"] == []


def test_public_email_settings_masks_both_secrets() -> None:
    raw = default_email_settings()
    raw["entra"][EMAIL_CLIENT_SECRET] = "entra-secret"
    raw["smtp"][EMAIL_SMTP_PASSWORD] = "smtp-secret"

    result = public_email_settings(raw)

    assert EMAIL_CLIENT_SECRET not in result["entra"]
    assert EMAIL_SMTP_PASSWORD not in result["smtp"]
    assert result["entra"]["client_secret_set"] is True
    assert result["smtp"]["password_set"] is True


def test_web_settings_update_preserves_blank_mail_secrets_and_snapshot_masks_them() -> None:
    current = deepcopy(common.DEFAULT_CONFIG)
    current[EMAIL_SETTINGS_KEY] = default_email_settings()
    current[EMAIL_SETTINGS_KEY]["entra"][EMAIL_CLIENT_SECRET] = "saved-entra"
    current[EMAIL_SETTINGS_KEY]["smtp"][EMAIL_SMTP_PASSWORD] = "saved-smtp"
    submitted = default_email_settings()
    submitted["primary_channel"] = "smtp"

    with (
        patch.object(config, "CONFIG", current),
        patch.object(web_data.config, "CONFIG", current),
        patch.object(web_data, "save_config") as save,
        patch.object(web_data.config, "initialize_config"),
        patch.object(web_data, "settings_snapshot", return_value={"saved": True}),
    ):
        result = web_data.update_settings({EMAIL_SETTINGS_KEY: submitted})

    assert result == {"saved": True}
    assert current[EMAIL_SETTINGS_KEY]["primary_channel"] == "smtp"
    assert current[EMAIL_SETTINGS_KEY]["entra"][EMAIL_CLIENT_SECRET] == "saved-entra"
    assert current[EMAIL_SETTINGS_KEY]["smtp"][EMAIL_SMTP_PASSWORD] == "saved-smtp"
    preserve = save.call_args.kwargs["preserve_secrets"]
    assert preserve[EMAIL_SETTINGS_KEY] == {
        "entra.client_secret",
        "smtp.password",
    }


def test_settings_snapshot_exposes_only_public_mail_settings() -> None:
    current = deepcopy(common.DEFAULT_CONFIG)
    current[EMAIL_SETTINGS_KEY] = default_email_settings()
    current[EMAIL_SETTINGS_KEY]["entra"][EMAIL_CLIENT_SECRET] = "saved-entra"
    current[EMAIL_SETTINGS_KEY]["smtp"][EMAIL_SMTP_PASSWORD] = "saved-smtp"

    with (
        patch.object(web_data.config, "CONFIG", current),
        patch.object(web_data, "load_users", return_value=[]),
    ):
        snapshot = web_data.settings_snapshot()

    email = snapshot[EMAIL_SETTINGS_KEY]
    assert EMAIL_CLIENT_SECRET not in email["entra"]
    assert EMAIL_SMTP_PASSWORD not in email["smtp"]
    assert email["entra"]["client_secret_set"] is True
    assert email["smtp"]["password_set"] is True
    assert EMAIL_SETTINGS_KEY not in web_data.settings_secret_values()
