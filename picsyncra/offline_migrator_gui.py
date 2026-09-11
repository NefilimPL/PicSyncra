"""Tkinter front end for the standalone pre-rebrand SQLite migrator."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import sys
import threading

from .offline_legacy_sqlite_migrator import (
    MigrationPaths,
    MigrationProgress,
    OfflineMigrationError,
    OfflineMigrationReport,
    resolve_offline_migration_paths,
    run_offline_legacy_migration,
)
from .offline_legacy_profile_migrator import (
    OfflineLegacyProfileMigrationError,
    OfflineLegacyProfilePaths,
    OfflineLegacyProfileReport,
    resolve_offline_legacy_profile_paths,
    run_offline_legacy_profile_migration,
)


SQLITE_REBRAND_MODE = "sqlite_rebrand"
LEGACY_PROFILE_MODE = "legacy_profile"


def migration_confirmation_message(paths: MigrationPaths) -> str:
    """Describe the target and the post-activation legacy archive handover."""

    archive_root = paths.app_root / "BACKUP" / "legacy-import"
    return (
        f"Źródło:\n{paths.source}\n\n"
        f"Nowy plik docelowy:\n{paths.target}\n\n"
        "Po poprawnej aktywacji plik źródłowy SQLite i obecne pliki -wal/-shm "
        f"zostaną przeniesione do:\n{archive_root}\n\n"
        "Kontynuować?"
    )


def legacy_profile_confirmation_message(paths: OfflineLegacyProfilePaths) -> str:
    """Describe an explicitly selected profile import and its archive destination."""

    archive_root = paths.backup_root / "legacy-import"
    return (
        f"Źródło LEGACY:\n{paths.source_root}\n\n"
        f"Nowy plik docelowy SQLite PicSyncra:\n{paths.target}\n\n"
        "Po poprawnej aktywacji pliki wybranego profilu zostaną przeniesione do:\n"
        f"{archive_root}\n\n"
        "Kontynuować?"
    )


def legacy_profile_source_path(source_root: str) -> Path:
    """Return a source selected in the GUI; an empty field is never a path."""

    selected = str(source_root or "").strip()
    if not selected:
        raise OfflineLegacyProfileMigrationError(
            "source_missing",
            "Wybierz folder starej konfiguracji LEGACY.",
        )
    return Path(selected)


class OfflineMigratorController:
    """Marshal worker notifications through Tk's scheduler."""

    def __init__(
        self,
        after: Callable[[int, Callable[[], None]], object],
        on_progress: Callable[[MigrationProgress], None],
        on_status: Callable[[str], None],
    ) -> None:
        self._after = after
        self._on_progress = on_progress
        self._on_status = on_status

    def receive_progress(self, event: MigrationProgress) -> None:
        self._after(0, lambda: self._on_progress(event))

    def receive_success(
        self, report: OfflineMigrationReport | OfflineLegacyProfileReport
    ) -> None:
        archive_status = (
            f" Archiwum plików legacy: {report.archive_dir}."
            if report.archive_dir is not None
            else ""
        )
        warning_status = (
            f" Ostrzeżenie: {report.archive_warning}"
            if report.archive_warning
            else ""
        )
        if isinstance(report, OfflineMigrationReport):
            details = f"produkty: {report.product_count}, konta: {report.user_count}."
        else:
            counts = ", ".join(
                f"{name}: {count}"
                for name, count in sorted(report.component_counts.items())
            ) or "brak dodatkowych składników."
            details = f"źródło: {report.source_kind}; {counts}"
        self._after(
            0,
            lambda: self._on_status(
                f"Migracja zakończona. Nowa baza: {report.target}; {details}"
                f"{archive_status}{warning_status}"
            ),
        )

    def receive_failure(self, error: Exception) -> None:
        self._after(0, lambda: self._on_status(str(error)))


class OfflineMigratorWindow:
    """Confirmation-first GUI for explicit offline migration modes."""

    def __init__(self, root) -> None:
        import tkinter as tk
        from tkinter import ttk

        self.root = root
        root.title("PicSyncra — migrator")
        root.minsize(700, 410)
        self.tk = tk
        self.ttk = ttk
        default_root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path.cwd()
        self.mode = tk.StringVar(value=SQLITE_REBRAND_MODE)
        self.app_root = tk.StringVar(value=str(default_root))
        self.legacy_source_root = tk.StringVar()
        self.status = tk.StringVar(value="Wybierz tryb i katalog głównej aplikacji.")
        self.source = tk.StringVar(value="Źródło: —")
        self.target = tk.StringVar(value="Cel: —")
        self.progress = tk.IntVar(value=0)
        self.controller = OfflineMigratorController(root.after, self._apply_progress, self.status.set)
        frame = ttk.Frame(root, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Tryb migracji:").grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(
            frame,
            text="picorgftp_sql.sqlite → picsyncra.sqlite",
            variable=self.mode,
            value=SQLITE_REBRAND_MODE,
            command=self._refresh_mode,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 2))
        ttk.Radiobutton(
            frame,
            text="LEGACY → SQLite PicSyncra",
            variable=self.mode,
            value=LEGACY_PROFILE_MODE,
            command=self._refresh_mode,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 8))
        ttk.Label(frame, text="Katalog głównej aplikacji PicSyncra:").grid(row=3, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.app_root, width=76).grid(row=4, column=0, sticky="ew", pady=(2, 8))
        ttk.Button(frame, text="Wybierz…", command=self._browse_app_root).grid(row=4, column=1, padx=(8, 0))
        self.profile_source_label = ttk.Label(frame, text="Folder starej konfiguracji LEGACY:")
        self.profile_source_entry = ttk.Entry(frame, textvariable=self.legacy_source_root, width=76)
        self.profile_source_button = ttk.Button(frame, text="Wybierz…", command=self._browse_legacy_source)
        self.profile_source_label.grid(row=5, column=0, sticky="w")
        self.profile_source_entry.grid(row=6, column=0, sticky="ew", pady=(2, 8))
        self.profile_source_button.grid(row=6, column=1, padx=(8, 0))
        ttk.Label(frame, textvariable=self.source, wraplength=650).grid(row=7, column=0, columnspan=2, sticky="w", pady=4)
        ttk.Label(frame, textvariable=self.target, wraplength=650).grid(row=8, column=0, columnspan=2, sticky="w", pady=4)
        self.start_button = ttk.Button(frame, text="Rozpocznij migrację", command=self._confirm_and_start)
        self.start_button.grid(row=9, column=0, sticky="w", pady=(12, 6))
        ttk.Progressbar(frame, maximum=100, variable=self.progress).grid(row=10, column=0, columnspan=2, sticky="ew", pady=5)
        ttk.Label(frame, textvariable=self.status, wraplength=650).grid(row=11, column=0, columnspan=2, sticky="w", pady=4)
        frame.columnconfigure(0, weight=1)
        self._refresh_mode()

    def _refresh_mode(self) -> None:
        profile_mode = self.mode.get() == LEGACY_PROFILE_MODE
        for widget in (
            self.profile_source_label,
            self.profile_source_entry,
            self.profile_source_button,
        ):
            if profile_mode:
                widget.grid()
            else:
                widget.grid_remove()
        self.source.set("Źródło: —")
        self.target.set("Cel: —")

    def _browse_app_root(self) -> None:
        from tkinter import filedialog

        chosen = filedialog.askdirectory(initialdir=self.app_root.get() or str(Path.cwd()))
        if chosen:
            self.app_root.set(chosen)

    def _browse_legacy_source(self) -> None:
        from tkinter import filedialog

        chosen = filedialog.askdirectory(
            initialdir=self.legacy_source_root.get() or str(Path.cwd())
        )
        if chosen:
            self.legacy_source_root.set(chosen)

    def _confirm_and_start(self) -> None:
        from tkinter import messagebox

        try:
            if self.mode.get() == LEGACY_PROFILE_MODE:
                paths = resolve_offline_legacy_profile_paths(
                    Path(self.app_root.get()),
                    legacy_profile_source_path(self.legacy_source_root.get()),
                )
                confirmation = legacy_profile_confirmation_message(paths)
            else:
                paths = resolve_offline_migration_paths(Path(self.app_root.get()))
                confirmation = migration_confirmation_message(paths)
        except (OfflineMigrationError, OfflineLegacyProfileMigrationError) as error:
            messagebox.showerror("Migrator SQLite", str(error), parent=self.root)
            return
        source = paths.source_root if isinstance(paths, OfflineLegacyProfilePaths) else paths.source
        self.source.set(f"Źródło: {source}")
        self.target.set(f"Cel: {paths.target}")
        if not messagebox.askyesno(
            "Potwierdź migrację",
            confirmation,
            parent=self.root,
        ):
            return
        self.start_button.state(["disabled"])
        if isinstance(paths, OfflineLegacyProfilePaths):
            target = self._worker_legacy_profile
            args = (paths.app_root, paths.source_root)
        else:
            target = self._worker_legacy_sqlite
            args = (paths.app_root,)
        threading.Thread(target=target, args=args, daemon=True).start()

    def _worker_legacy_sqlite(self, app_root: Path) -> None:
        try:
            report = run_offline_legacy_migration(app_root, self.controller.receive_progress)
        except Exception as error:
            self.controller.receive_failure(error)
        else:
            self.controller.receive_success(report)
        finally:
            self.root.after(0, lambda: self.start_button.state(["!disabled"]))

    def _worker_legacy_profile(self, app_root: Path, source_root: Path) -> None:
        try:
            report = run_offline_legacy_profile_migration(
                app_root, source_root, self.controller.receive_progress
            )
        except Exception as error:
            self.controller.receive_failure(error)
        else:
            self.controller.receive_success(report)
        finally:
            self.root.after(0, lambda: self.start_button.state(["!disabled"]))

    def _apply_progress(self, event: MigrationProgress) -> None:
        self.status.set(event.message)
        if event.current is not None and event.total:
            self.progress.set(round(event.current * 100 / event.total))


def main() -> None:
    import tkinter as tk

    root = tk.Tk()
    OfflineMigratorWindow(root)
    root.mainloop()
