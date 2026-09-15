from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from picsyncra.installation.contracts import ComponentRef, ReleaseChoice


def choice(*, asset_name: str, payload: bytes) -> ReleaseChoice:
    return ReleaseChoice(
        release_id=42,
        tag="v1.2.3",
        commit="a" * 40,
        channel="stable",
        source_branch="main",
        manifest_sha256="b" * 64,
        components=(
            ComponentRef(
                name="web",
                component_id="web-42",
                asset_name=asset_name,
                sha256=hashlib.sha256(payload).hexdigest(),
                size=len(payload),
            ),
        ),
        can_install=True,
        blocked_reason=None,
    )


def release(asset_name: str, payload: bytes, *, release_id: int = 42) -> dict[str, object]:
    return {
        "id": release_id,
        "assets": [
            {
                "name": asset_name,
                "size": len(payload),
                "browser_download_url": "https://github.com/NefilimPL/PicSyncra/releases/download/v1.2.3/" + asset_name,
            }
        ],
    }


class Response:
    def __init__(self, payload: bytes, url: str = "https://release-assets.githubusercontent.com/package") -> None:
        self._payload = payload
        self._offset = 0
        self.url = url

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self._payload) - self._offset
        result = self._payload[self._offset : self._offset + size]
        self._offset += len(result)
        return result

    def close(self) -> None:
        pass


def test_download_publishes_only_hash_and_size_verified_asset(tmp_path: Path) -> None:
    from picsyncra.installation.downloads import download_release

    payload = b"installed build"
    result = download_release(
        choice(asset_name="web.zip", payload=payload),
        release("web.zip", payload),
        tmp_path / "staging",
        open_url=lambda _url: Response(payload),
    )

    assert result == {"web": tmp_path / "staging" / "web.zip"}
    assert result["web"].read_bytes() == payload
    assert not list((tmp_path / "staging").glob("*.part"))


def test_download_rejects_release_id_mismatch_before_network_access(tmp_path: Path) -> None:
    from picsyncra.installation.downloads import DownloadError, download_release

    with pytest.raises(DownloadError, match="release"):
        download_release(
            choice(asset_name="web.zip", payload=b"data"),
            release("web.zip", b"data", release_id=43),
            tmp_path / "staging",
            open_url=lambda _url: pytest.fail("network access is forbidden"),
        )


@pytest.mark.parametrize("asset_name", ["../web.zip", "web/../../payload.zip", "web\\payload.zip"])
def test_download_rejects_asset_traversal_from_verified_choice(tmp_path: Path, asset_name: str) -> None:
    from picsyncra.installation.downloads import DownloadError, download_release

    with pytest.raises(DownloadError, match="file name"):
        download_release(
            choice(asset_name=asset_name, payload=b"data"),
            release(asset_name, b"data"),
            tmp_path / "staging",
            open_url=lambda _url: pytest.fail("network access is forbidden"),
        )
    assert not (tmp_path / "payload.zip").exists()


def test_download_rejects_hash_mismatch_without_publishing(tmp_path: Path) -> None:
    from picsyncra.installation.downloads import DownloadError, download_release

    with pytest.raises(DownloadError, match="checksum"):
        download_release(
            choice(asset_name="web.zip", payload=b"expected"),
            release("web.zip", b"expected"),
            tmp_path / "staging",
            open_url=lambda _url: Response(b"tampered"),
        )
    assert not (tmp_path / "staging" / "web.zip").exists()


def test_download_rejects_untrusted_final_host_and_keeps_staging_empty(tmp_path: Path) -> None:
    from picsyncra.installation.downloads import DownloadError, download_release

    payload = b"installed build"
    with pytest.raises(DownloadError, match="host"):
        download_release(
            choice(asset_name="web.zip", payload=payload),
            release("web.zip", payload),
            tmp_path / "staging",
            open_url=lambda _url: Response(payload, "https://attacker.invalid/payload"),
        )
    assert not (tmp_path / "staging" / "web.zip").exists()


def test_download_refuses_existing_file_or_link_in_staging(tmp_path: Path) -> None:
    from picsyncra.installation.downloads import DownloadError, download_release

    payload = b"installed build"
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "web.zip").write_bytes(b"older package")

    with pytest.raises(DownloadError, match="already exists"):
        download_release(
            choice(asset_name="web.zip", payload=payload),
            release("web.zip", payload),
            staging,
            open_url=lambda _url: Response(payload),
        )
    assert (staging / "web.zip").read_bytes() == b"older package"
