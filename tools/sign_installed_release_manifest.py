"""Sign an installed-release manifest with a CI-only Ed25519 private key."""

from __future__ import annotations

import argparse
import base64
import binascii
import os
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


class SigningError(RuntimeError):
    """The protected release signing key is unavailable or invalid."""


def _private_key() -> Ed25519PrivateKey:
    try:
        raw = base64.b64decode(os.environ["PICSYNCRA_RELEASE_SIGNING_KEY"], validate=True)
        if len(raw) != 32:
            raise ValueError
        return Ed25519PrivateKey.from_private_bytes(raw)
    except (KeyError, ValueError, TypeError, binascii.Error) as exc:
        raise SigningError("The release signing key is unavailable or invalid.") from exc


def sign_manifest(manifest: Path, signature: Path) -> None:
    raw = Path(manifest).read_bytes()
    if not raw:
        raise SigningError("The release manifest is empty.")
    target = Path(signature)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_private_key().sign(raw))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    sign_manifest(args.input, args.output)
    return 0


if __name__ == "__main__": raise SystemExit(main())
