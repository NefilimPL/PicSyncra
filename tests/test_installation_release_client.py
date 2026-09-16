from __future__ import annotations

import pytest


def test_release_client_uses_compiled_key_mapping_and_fixed_catalog(monkeypatch) -> None:
    from picsyncra.installation import release_client

    captured: dict[str, object] = {}

    def fake_list(channel, *, fetch_json, fetch_asset, trusted_keys):
        captured.update({"channel": channel, "fetch_json": fetch_json, "fetch_asset": fetch_asset, "keys": trusted_keys})
        return ("release",)

    monkeypatch.setattr(release_client, "list_signed_releases", fake_list)
    monkeypatch.setattr(release_client, "trusted_release_keys", lambda: {"key-1": "public"})

    assert release_client.list_installed_releases("stable") == ("release",)
    assert captured["channel"] == "stable"
    assert captured["keys"] == {"key-1": "public"}


def test_release_client_rejects_an_unknown_channel_without_network() -> None:
    from picsyncra.installation.release_client import list_installed_releases

    with pytest.raises(ValueError):
        list_installed_releases("preview")
