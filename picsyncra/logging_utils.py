"""Convenience helpers for writing to the UI and rotating log files."""

from .common import *  # noqa: F401,F403 - reuse shared helpers
from . import settings
from . import localization
from .redaction import sanitize_free_text

AG = None


def _summarize_for_ui(message):
    """Return a compact, human friendly summary suitable for the GUI log."""

    if not message:
        return message

    summary = str(message).splitlines()[0].strip()
    separators = (":", " - ", " — ", " -> ", " | ", "; ")
    for sep in separators:
        if sep in summary:
            head = summary.split(sep, 1)[0].strip()
            if head:
                summary = head if head.endswith("…") else f"{head}…"
                break
    max_length = 140
    if len(summary) > max_length:
        summary = summary[: max_length - 1].rstrip() + "…"
    return summary


def set_app(app):
    """Register the Tk ``app`` instance so log messages can reach the GUI."""

    global AG
    AG = app


def rotate_log(path, max_bytes=1073741824, backups=3):
    """Rotate log files when they exceed ``max_bytes`` in size."""

    target = path
    try:
        if A.path.exists(target) and A.path.getsize(target) >= max_bytes:
            # Shift existing files up one index, pruning the oldest backup.
            for index in Ax(backups, 0, -1):
                src = f"{target}.{index}" if index > 1 else target
                dst = f"{target}.{index + 1}"
                if A.path.exists(src):
                    try:
                        if A.path.exists(dst):
                            A.remove(dst)
                    except Exception:
                        pass
                    try:
                        A.rename(src, dst)
                    except Exception:
                        pass
            with x(target, T, encoding=k) as handle:
                handle.write(f"[{A9.now().strftime(A6)}] Log rotated\n")
    except E:
        pass


def _ensure_log_parent(path):
    """Ensure the parent directory for ``path`` exists."""

    try:
        directory = A.path.dirname(path)
        if directory:
            A.makedirs(directory, exist_ok=J)
    except E:
        pass


def log_error(message, ui_message=None):
    """Write an error entry to the log files and optionally the UI."""

    safe_message = sanitize_free_text(message, limit=32 * 1024)
    try:
        path = settings.AM
        _ensure_log_parent(path)
        rotate_log(path)
        timestamp = A9.now().strftime(A6)
        with x(path, "a", encoding=k) as handle:
            handle.write(
                f"[{timestamp}] [USER: {AO}] [PC: {AF}] ERROR: {safe_message}\n"
            )
    except E:
        pass
    try:
        if AG:
            ui_text = (
                sanitize_free_text(ui_message)
                if ui_message is not None
                else _summarize_for_ui(safe_message)
            )
            if ui_text:
                if threading.current_thread() != threading.main_thread():
                    AG.after(0, lambda msg=ui_text: AG._ui_log(f"❗ {msg}"))
                else:
                    AG._ui_log(f"❗ {ui_text}")
    except E:
        pass


def log_info(message, ui_message=None):
    """Write an informational log entry and mirror it to the UI."""

    safe_message = sanitize_free_text(message)
    try:
        path = settings.BM
        _ensure_log_parent(path)
        rotate_log(path)
        timestamp = A9.now().strftime(A6)
        with x(path, "a", encoding=k) as handle:
            handle.write(f"[{timestamp}] [USER: {AO}] [PC: {AF}] {safe_message}\n")
    except E:
        pass
    try:
        if AG:
            ui_text = (
                sanitize_free_text(ui_message)
                if ui_message is not None
                else _summarize_for_ui(safe_message)
            )
            if ui_text:
                if threading.current_thread() != threading.main_thread():
                    AG.after(0, lambda msg=ui_text: AG._ui_log(f"• {msg}"))
                else:
                    AG._ui_log(f"• {ui_text}")
    except E:
        pass


def log_error_loc(key, **kwargs):
    """Log a translated error message based on a localization key."""

    file_msg = localization.LANG_EN.get(key, key).format(**kwargs)
    ui_msg = localization.LANG.get(key, file_msg).format(**kwargs)
    log_error(file_msg, ui_msg)


def log_info_loc(key, **kwargs):
    """Log a translated info message based on a localization key."""

    file_msg = localization.LANG_EN.get(key, key).format(**kwargs)
    ui_msg = localization.LANG.get(key, file_msg).format(**kwargs)
    log_info(file_msg, ui_msg)
