"""Compatibility version of the independently installed controller host."""

# Bump this when a release needs a controller feature that older installer
# packages cannot provide. Signed catalogs block incompatible releases before
# any asset download begins.
CONTROLLER_VERSION = 1


__all__ = ["CONTROLLER_VERSION"]
