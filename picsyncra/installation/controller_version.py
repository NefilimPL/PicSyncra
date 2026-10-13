"""Compatibility versions of the infrastructure replaced by full Setup."""

# Bump this when a release needs a controller feature that older installer
# packages cannot provide. Signed catalogs block incompatible releases before
# any asset download begins.
# Version 4 requires range batching and the corrected backend startup checks.
# The module updater never replaces these binaries, even if application modules
# already display a newer release tag.
CONTROLLER_VERSION = 4
LAUNCHER_VERSION = 4


__all__ = ["CONTROLLER_VERSION", "LAUNCHER_VERSION"]
