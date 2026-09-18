"""Inject CI-configured Ed25519 public keys into an installed build tree."""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import re


_KEY_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


def write_keys(target: Path, raw: str) -> None:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("PICSYNCRA_RELEASE_PUBLIC_KEYS must be JSON.") from exc
    if not isinstance(payload, dict) or not payload:
        raise ValueError("At least one trusted release public key is required.")
    keys: dict[str, str] = {}
    for key_id, key in payload.items():
        if not isinstance(key_id, str) or _KEY_ID.fullmatch(key_id) is None or not isinstance(key, str):
            raise ValueError("Trusted release key mapping is invalid.")
        try:
            if len(base64.b64decode(key, validate=True)) != 32:
                raise ValueError
        except Exception as exc:
            raise ValueError("Trusted release public key is invalid.") from exc
        keys[key_id] = key
    Path(target).write_text(
        "from types import MappingProxyType\n\n_TRUSTED_RELEASE_KEYS = MappingProxyType("
        + repr(dict(sorted(keys.items()))) + ")\n\ndef trusted_release_keys():\n    return _TRUSTED_RELEASE_KEYS\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    write_keys(args.output, os.environ["PICSYNCRA_RELEASE_PUBLIC_KEYS"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
