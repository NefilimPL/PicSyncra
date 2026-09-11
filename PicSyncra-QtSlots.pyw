"""Standalone launcher for the PySide6 slot-scrolling prototype."""

import sys
import traceback

from picsyncra import brand
from picsyncra.bootstrap import initialize_application_runtime


def _show_boot_error(message):
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(f"{brand.APP_NAME} Qt preview", message)
        root.destroy()
    except Exception:
        print(message, file=sys.stderr)


def main():
    try:
        initialize_application_runtime(interactive=True)
        from picsyncra.qt_slots_preview import main as qt_main

        return qt_main()
    except ModuleNotFoundError as exc:
        message = (
            "Nie można uruchomić prototypu Qt.\n\n"
            f"{exc}\n\n"
            "Zainstaluj zależność: pip install PySide6"
        )
        _show_boot_error(message)
        return 1
    except Exception:
        trace = traceback.format_exc()
        _show_boot_error(f"Nie można uruchomić prototypu Qt.\n\n{trace}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
