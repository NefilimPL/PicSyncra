"""PicSyncra package."""

import importlib

__all__ = ["App", "config", "localization"]


def __getattr__(name):
    if name == "App":
        module = importlib.import_module(f"{__name__}.app")
        value = module.App
        globals()[name] = value
        return value
    if name in {"config", "localization"}:
        module = importlib.import_module(f"{__name__}.{name}")
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(globals())
