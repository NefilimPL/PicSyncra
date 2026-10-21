from __future__ import annotations

import base64
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption


def test_signer_reads_private_key_only_from_environment_and_writes_raw_signature(tmp_path: Path, monkeypatch) -> None:
    from tools.sign_installed_release_manifest import SigningError, sign_manifest

    private = Ed25519PrivateKey.generate()
    raw_private = private.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    monkeypatch.setenv("PICSYNCRA_RELEASE_SIGNING_KEY", base64.b64encode(raw_private).decode())
    manifest = tmp_path / "manifest.json"
    signature = tmp_path / "manifest.sig"
    manifest.write_bytes(b'{"schema":1}')

    sign_manifest(manifest, signature)
    private.public_key().verify(signature.read_bytes(), manifest.read_bytes())

    monkeypatch.delenv("PICSYNCRA_RELEASE_SIGNING_KEY")
    with pytest.raises(SigningError):
        sign_manifest(manifest, signature)
