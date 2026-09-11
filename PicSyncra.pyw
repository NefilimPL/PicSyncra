"""Application entry point."""

import json
import os
import sys
import traceback
from datetime import datetime

from picsyncra import brand
from picsyncra.runtime_lock import SingleInstanceGuard, acquire_single_instance_lock


def _resolve_boot_log_dir():
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(sys.executable) or os.getcwd()
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__)) or os.getcwd()
    return os.path.join(base_dir, "logs")


def _resolve_instance_lock_path():
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(sys.executable) or os.getcwd()
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__)) or os.getcwd()
    return os.path.join(base_dir, "PicSyncra.lock")


def _write_boot_log(message):
    log_dir = _resolve_boot_log_dir()
    try:
        os.makedirs(log_dir, exist_ok=True)
    except Exception:
        log_dir = os.getcwd()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_filename = f"error_log_boot_{timestamp}.txt"
    log_path = os.path.join(log_dir, log_filename)
    try:
        with open(log_path, "a", encoding="utf-8") as handle:
            handle.write("=" * 80 + "\n")
            handle.write(f"BOOT ERROR {timestamp}\n")
            handle.write("=" * 80 + "\n")
            handle.write(message + "\n")
    except Exception:
        pass
    return log_path


def _show_boot_error(message):
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Błąd aplikacji", message)
        root.destroy()
    except Exception:
        pass


def _show_boot_info(message):
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo(brand.APP_NAME, message)
        root.destroy()
    except Exception:
        pass


def _build_boot_hint(exc):
    if isinstance(exc, ModuleNotFoundError):
        missing = getattr(exc, "name", "") or ""
        if missing.startswith("picsyncra."):
            module_hint = missing.split(".", 1)[1] if "." in missing else missing
            return (
                "Wskazówka: brakuje modułu aplikacji. Sprawdź, czy plik "
                f"\"{module_hint}.py\" istnieje w folderze picsyncra oraz czy nie "
                "został zmieniony jego nazwą."
            )
        return (
            "Wskazówka: brakujący moduł Pythona. Sprawdź, czy zależność jest "
            "zainstalowana oraz czy uruchamiasz aplikację z właściwego środowiska."
        )
    if isinstance(exc, ImportError):
        return (
            "Wskazówka: błąd importu. Upewnij się, że wszystkie wymagane biblioteki są "
            "zainstalowane i wersje są zgodne."
        )
    if isinstance(exc, FileNotFoundError):
        return (
            "Wskazówka: brakujący plik. Sprawdź, czy wymagane pliki konfiguracyjne lub "
            "zasoby są na miejscu."
        )
    if isinstance(exc, PermissionError):
        return (
            "Wskazówka: brak uprawnień do pliku lub folderu. Sprawdź prawa dostępu "
            "lub uruchom aplikację z odpowiednimi uprawnieniami."
        )
    if isinstance(exc, json.JSONDecodeError):
        return (
            "Wskazówka: uszkodzony plik JSON. Sprawdź składnię w local_settings.json "
            "lub innych plikach konfiguracyjnych."
        )
    if isinstance(exc, OSError):
        return (
            "Wskazówka: błąd systemowy (OSError). Sprawdź dostęp do dysku, ścieżki i "
            "stan systemu plików."
        )
    if isinstance(exc, RuntimeError):
        return (
            "Wskazówka: błąd wykonania. Sprawdź ostatnie zmiany w kodzie i logi "
            "startowe, aby ustalić źródło problemu."
        )
    return (
        "Wskazówka: sprawdź treść wyjątku i pełny traceback w logu startowym, aby "
        "ustalić źródło błędu."
    )


def main():
    """Start the GUI application and warn about configuration issues."""

    instance_lock_path = _resolve_instance_lock_path()
    instance_lock = acquire_single_instance_lock(instance_lock_path)
    if instance_lock is None:
        notice_lock = SingleInstanceGuard(
            f"{brand.APP_NAME}-notice",
            scope=os.path.dirname(instance_lock_path),
        )
        if notice_lock.acquire():
            try:
                _show_boot_info(
                    "Aplikacja już się uruchamia albo jest już otwarta.\n"
                    "Poczekaj chwilę i sprawdź pasek zadań."
                )
            finally:
                notice_lock.release()
        return
    try:
        try:
            from picsyncra.bootstrap import initialize_application_runtime

            initialize_application_runtime(interactive=True)
            from picsyncra.app import App
            from picsyncra.common import O, SETTINGS_LABEL
            from picsyncra.settings import BASE_DIR_OVERRIDE_WARNING
        except Exception as exc:
            trace = traceback.format_exc()
            hint = _build_boot_hint(exc)
            boot_message = (
                "Krytyczny błąd podczas uruchamiania aplikacji.\n\n"
                f"{trace}\n\nSzczegóły zapisano w error_log_boot.txt."
            )
            log_path = _write_boot_log(f"{trace}\n{hint}".strip())
            hint_block = f"\n\n{hint}" if hint else ""
            _show_boot_error(f"{boot_message}{hint_block}\n\nPlik: {log_path}")
            raise

        try:
            app = App()
            try:
                from picsyncra.assets import set_tk_window_icon

                set_tk_window_icon(app, brand.LOCAL_ICON)
            except Exception:
                pass
            if BASE_DIR_OVERRIDE_WARNING:
                O.showwarning(SETTINGS_LABEL, BASE_DIR_OVERRIDE_WARNING)
            for combo in (
                app.combo_name,
                app.combo_type,
                app.combo_model,
                app.combo_color1,
                app.combo_color2,
                app.combo_color3,
                app.combo_extra,
            ):
                combo.configure(postcommand=lambda c=combo: app._style_combobox_list(c))
            app.mainloop()
        except Exception as exc:
            trace = traceback.format_exc()
            hint = _build_boot_hint(exc)
            boot_message = (
                "Krytyczny błąd podczas uruchamiania aplikacji.\n\n"
                f"{trace}\n\nSzczegóły zapisano w error_log_boot.txt."
            )
            log_path = _write_boot_log(f"{trace}\n{hint}".strip())
            hint_block = f"\n\n{hint}" if hint else ""
            _show_boot_error(f"{boot_message}{hint_block}\n\nPlik: {log_path}")
            raise
    finally:
        instance_lock.release()


if __name__ == "__main__":
    main()
