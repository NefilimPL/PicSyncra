from __future__ import annotations

from unittest.mock import patch

from picsyncra import github_status


def test_dev_version_is_older_than_latest_release() -> None:
    assert github_status.github_update_available("dev", "v1.2.3") is True


def test_semantic_release_comparison_detects_newer_release() -> None:
    assert github_status.github_update_available("v1.2.2", "v1.2.3") is True
    assert github_status.github_update_available("v1.2.3", "v1.2.3") is False
    assert github_status.github_update_available("v1.3.0", "v1.2.3") is False


def test_non_semantic_versions_do_not_claim_update() -> None:
    assert github_status.github_update_available("build-local", "release-latest") is False


def test_public_repository_payload_is_normalized() -> None:
    responses = {
        "/repos/NefilimPL/PicSyncra": {
            "full_name": "NefilimPL/PicSyncra",
            "html_url": "https://github.com/NefilimPL/PicSyncra",
            "private": False,
            "description": "Panel",
            "license": {"spdx_id": "MIT", "name": "MIT License"},
            "owner": {
                "login": "NefilimPL",
                "html_url": "https://github.com/NefilimPL",
                "type": "User",
            },
        },
        "/repos/NefilimPL/PicSyncra/releases/latest": {
            "tag_name": "v1.2.3",
            "name": "v1.2.3",
            "html_url": "https://github.com/NefilimPL/PicSyncra/releases/tag/v1.2.3",
            "published_at": "2026-07-01T12:00:00Z",
            "prerelease": False,
            "draft": False,
        },
        "/repos/NefilimPL/PicSyncra/contributors": [
            {"login": "NefilimPL", "html_url": "https://github.com/NefilimPL", "contributions": 10},
            {"login": "Contributor", "html_url": "https://github.com/Contributor", "contributions": 3},
        ],
    }

    def fake_fetch(path: str) -> object:
        return responses[path]

    with patch.object(github_status, "_github_fetch_json", side_effect=fake_fetch):
        payload = github_status.github_repository_status("dev", force_refresh=True)

    assert payload["available"] is True
    assert payload["private"] is False
    assert payload["update_available"] is True
    assert payload["repository"]["full_name"] == "NefilimPL/PicSyncra"
    assert payload["latest_release"]["tag_name"] == "v1.2.3"
    assert payload["license"]["spdx_id"] == "MIT"
    assert payload["owner"]["login"] == "NefilimPL"
    assert [item["login"] for item in payload["contributors"]] == ["Contributor"]


def test_not_found_reports_private_or_unavailable() -> None:
    def fake_fetch(path: str) -> object:
        raise github_status.GitHubStatusError(404, "missing")

    with patch.object(github_status, "_github_fetch_json", side_effect=fake_fetch):
        payload = github_status.github_repository_status("v1.0.0", force_refresh=True)

    assert payload["available"] is False
    assert payload["private"] is True
    assert payload["message"] == "Repozytorium jest prywatne albo niedostepne."
    assert payload["update_available"] is False
