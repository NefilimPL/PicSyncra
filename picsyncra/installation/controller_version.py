"""Compatibility versions of the infrastructure replaced by full Setup."""

# Bump this when a release needs a controller feature that older installer
# packages cannot provide. Signed catalogs block incompatible releases before
# any asset download begins.
# Version 5 adds direct application entries and bounded/lazy OCR startup.
# The module updater never replaces these binaries, even if application modules
# already display a newer release tag.
CONTROLLER_VERSION = 5
LAUNCHER_VERSION = 5


__all__ = ["CONTROLLER_VERSION", "LAUNCHER_VERSION"]
