"""Runtime asset lookup helpers."""

from __future__ import annotations

from pathlib import Path
import sys


def resource_path(*parts: str) -> Path:
    """Return the best runtime path for a bundled or source-tree asset."""

    candidates: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        candidates.append(Path(meipass).joinpath(*parts))
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent.joinpath(*parts))
    source_root = Path(__file__).resolve().parents[1]
    candidates.append(source_root.joinpath(*parts))
    package_root = Path(__file__).resolve().parent
    candidates.append(package_root.joinpath(*parts))
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0] if candidates else Path(*parts)


def pic_asset_path(filename: str) -> Path:
    """Return a path to an image from the repository ``pic`` directory."""

    return resource_path("pic", filename)


def set_tk_window_icon(window: object, filename: str) -> bool:
    """Apply a PNG icon to a Tk window when the asset is available."""

    try:
        import tkinter as tk

        path = pic_asset_path(filename)
        if not path.is_file():
            return False
        image = tk.PhotoImage(file=str(path))
        window.iconphoto(True, image)
        setattr(window, "_picsyncra_window_icon", image)
        return True
    except Exception:
        return False
