"""Public keys compiled into installed packages for release verification.

Release signing private keys never belong in this repository or in a client.
The release build injects the corresponding public key mapping into this
module before packaging. An empty mapping deliberately leaves every release
blocked, which is safer than accepting an unsigned update source.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping


# CI replaces this mapping in its isolated build directory from the protected
# ``PICSYNCRA_RELEASE_PUBLIC_KEYS`` configuration. Key IDs are published with
# each signed manifest and permit overlap during a key rotation.
_TRUSTED_RELEASE_KEYS: Mapping[str, str] = MappingProxyType({})


def trusted_release_keys() -> Mapping[str, str]:
    return _TRUSTED_RELEASE_KEYS


__all__ = ["trusted_release_keys"]
