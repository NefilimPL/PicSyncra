"""Tests for the web panel manager process launcher."""

from __future__ import annotations

import ast
import builtins
import json
import multiprocessing
import os
from pathlib import Path
import runpy
import subprocess
import sys
import types
from unittest.mock import patch

import pytest

from picsyncra import brand, web_manager


ROOT = Path(__file__).resolve().parents[1]
WEB_ENTRYPOINT = ROOT / "PicSyncra-WEB.pyw"
START_WEB_SCRIPT = ROOT / "tools" / "web" / "start_web.ps1"
STOP_WEB_SCRIPT = ROOT / "tools" / "web" / "stop_web.ps1"
POWERSHELL_HARNESS_TIMEOUT_SECONDS = 60


def _run_powershell_harness(path: Path) -> list[str]:
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(path),
        ],
        capture_output=True,
        text=True,
        # GitHub-hosted Windows runners can take longer than 20 seconds to
        # start a fresh Windows PowerShell process while the suite is busy.
        timeout=POWERSHELL_HARNESS_TIMEOUT_SECONDS,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return [line for line in result.stdout.splitlines() if line.strip()]


def test_web_entrypoint_calls_freeze_support_before_importing_manager() -> None:
    tree = ast.parse(WEB_ENTRYPOINT.read_text(encoding="utf-8"))
    freeze_guard = next(
        node
        for node in tree.body
        if isinstance(node, ast.If)
        and any(
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and isinstance(child.func.value, ast.Name)
            and child.func.value.id == "multiprocessing"
            and child.func.attr == "freeze_support"
            for child in ast.walk(node)
        )
    )
    manager_import = next(
        node
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        and node.module == "picsyncra.web_manager"
    )

    assert tree.body.index(freeze_guard) < tree.body.index(manager_import)


def test_web_entrypoint_runs_freeze_support_before_loading_manager(
    monkeypatch,
) -> None:
    calls: list[str] = []
    fake_manager = types.ModuleType("picsyncra.web_manager")
    fake_manager.main = lambda: calls.append("main")
    monkeypatch.setitem(sys.modules, "picsyncra.web_manager", fake_manager)
    original_import = builtins.__import__

    def track_manager_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "picsyncra.web_manager":
            calls.append("web_manager_import")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", track_manager_import)
    monkeypatch.setattr(
        multiprocessing, "freeze_support", lambda: calls.append("freeze_support")
    )

    runpy.run_path(str(WEB_ENTRYPOINT), run_name="__main__")

    assert calls == ["freeze_support", "web_manager_import", "main"]


@pytest.mark.skipif(os.name != "nt", reason="PowerShell starter scripts are Windows-only")
def test_start_web_script_records_its_own_launcher_pid(tmp_path) -> None:
    """Catches the starter writing only the child server PID to runtime metadata."""
    source = START_WEB_SCRIPT.read_text(encoding="utf-8")
    start = source.index("function Write-RunMetadata")
    end = source.index("\nfunction Test-WebDeps", start)
    write_metadata_function = source[start:end]
    harness_path = tmp_path / "tools" / "web" / "start_web_harness.ps1"
    harness_path.parent.mkdir(parents=True)
    harness_path.write_text(
        """
$Port = 8010
$HostAddress = "0.0.0.0"
$PidFile = Join-Path $PSScriptRoot "..\\..\\.picsyncra_web.pid"
"""
        + write_metadata_function
        + """
$firewallState = [pscustomobject]@{
    rule_name = ""
    created = $false
    remove_on_stop = $false
}
Write-RunMetadata 4242 $firewallState
[pscustomobject]@{
    metadata = Get-Content -Path $PidFile -Raw | ConvertFrom-Json
    launcher_process_id = [int]$PID
} | ConvertTo-Json -Compress
""",
        encoding="utf-8",
    )

    payload = json.loads(_run_powershell_harness(harness_path)[-1])

    assert payload["metadata"]["pid"] == 4242
    assert payload["metadata"]["launcher"] == "start_web.ps1"
    assert payload["metadata"]["launcher_pid"] == payload["launcher_process_id"]


@pytest.mark.skipif(os.name != "nt", reason="PowerShell starter scripts are Windows-only")
def test_stop_web_script_terminates_recorded_launcher_tree_first(tmp_path) -> None:
    """Catches STOP_WEB terminating only the server child instead of its launcher tree."""
    source = STOP_WEB_SCRIPT.read_text(encoding="utf-8")
    prefix, separator, suffix = source.partition("\n$stopped = $false\n")
    assert separator
    harness_path = tmp_path / "tools" / "web" / "stop_web_harness.ps1"
    harness_path.parent.mkdir(parents=True)
    harness_path.write_text(
        prefix
        + """
$script:stop_calls = @()
function Read-RunMetadata {
    return [pscustomobject]@{
        pid = 102
        launcher_pid = 101
        launcher = "start_web.ps1"
        port = 8010
        firewall_rule_created = $false
        firewall_remove_on_stop = $false
        firewall_rule_name = ""
    }
}
function Stop-WebPid($PidValue, [switch]$AllowRecordedLauncher) {
    $script:stop_calls += [int]$PidValue
    return [pscustomobject]@{ ok = $true; attempted = $true; message = "" }
}
function Get-PortListenerPids { return @(103) }
function Wait-WebPortRelease { return $true }
function Remove-FirewallRuleFromMetadata($Metadata) { }
"""
        + separator
        + suffix
        + "\n$script:stop_calls | ConvertTo-Json -Compress\n",
        encoding="utf-8",
    )

    calls = json.loads(_run_powershell_harness(harness_path)[-1])

    assert calls == 101


@pytest.mark.skipif(os.name != "nt", reason="PowerShell starter scripts are Windows-only")
def test_stop_web_script_uses_taskkill_tree_option(tmp_path) -> None:
    """Catches replacing tree shutdown with a single-process Stop-Process call."""
    source = STOP_WEB_SCRIPT.read_text(encoding="utf-8")
    start = source.index("function Stop-WebPid")
    end = source.index("\nfunction Read-RunMetadata", start)
    stop_process_function = source[start:end]
    harness_path = tmp_path / "stop_web_tree_harness.ps1"
    harness_path.write_text(
        """
$script:taskkill_args = $null
function Get-Process { return [pscustomobject]@{ ProcessName = "powershell" } }
function Test-WebProcess($PidValue) { return $true }
function Stop-Process { }
function taskkill {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    $script:taskkill_args = $Arguments
    $global:LASTEXITCODE = 0
}
"""
        + stop_process_function
        + """
$result = Stop-WebPid 101
[pscustomobject]@{
    ok = $result.ok
    arguments = @($script:taskkill_args)
} | ConvertTo-Json -Compress
""",
        encoding="utf-8",
    )

    payload = json.loads(_run_powershell_harness(harness_path)[-1])

    assert payload["ok"] is True
    assert payload["arguments"] == ["/PID", "101", "/T", "/F"]


class _FakeRoot:
    def __init__(self) -> None:
        self.destroyed = False
        self.after_calls = []

    def destroy(self) -> None:
        self.destroyed = True

    def after(self, delay_ms: int, callback=None) -> None:
        self.after_calls.append(delay_ms)
        if callback is not None:
            callback()


class _FakeStringVar:
    def __init__(self) -> None:
        self.value = ""

    def set(self, value: str) -> None:
        self.value = value


class _FakeProgressbar:
    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0

    def start(self, _interval_ms: int = 50) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1


def _app_without_tk() -> web_manager.WebManagerApp:
    app = object.__new__(web_manager.WebManagerApp)
    app.root = _FakeRoot()
    app.tray_icon = None
    app.status_var = _FakeStringVar()
    app.close_progress = _FakeProgressbar()
    app.closing = False
    app.close_check_in_progress = False
    app._port = lambda: 8010
    return app


def test_web_manager_tray_uses_the_picsyncra_web_icon(monkeypatch) -> None:
    app = _app_without_tk()
    app.root.withdraw = lambda: None
    requested_assets: list[str] = []

    class FakeImage:
        @staticmethod
        def open(path):
            return path

    class FakeIcon:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def run_detached(self) -> None:
            pass

    fake_pystray = types.SimpleNamespace(
        Icon=FakeIcon,
        Menu=lambda *items: items,
        MenuItem=lambda *item: item,
    )
    monkeypatch.setitem(sys.modules, "pystray", fake_pystray)
    monkeypatch.setitem(sys.modules, "PIL", types.SimpleNamespace(Image=FakeImage))
    monkeypatch.setattr(
        web_manager,
        "pic_asset_path",
        lambda filename: requested_assets.append(filename) or Path("icon.png"),
    )

    app.minimize_to_tray()

    assert requested_assets == [brand.WEB_ICON]


def test_service_environment_resets_pyinstaller_for_frozen_child_process() -> None:
    with (
        patch.object(web_manager.sys, "frozen", True, create=True),
        patch.dict(web_manager.os.environ, {"_PYI_APPLICATION_HOME_DIR": "C:/Temp/_MEI123"}, clear=True),
    ):
        env = web_manager.service_environment(8010, "0.0.0.0")

    assert env["PICSYNCRA_HEADLESS"] == "1"
    assert env["PICSYNCRA_WEB_PORT"] == "8010"
    assert env["PICSYNCRA_WEB_HOST"] == "0.0.0.0"
    assert env["PYINSTALLER_RESET_ENVIRONMENT"] == "1"


def test_write_metadata_records_explicit_launcher_pid(tmp_path, monkeypatch) -> None:
    """Catches dropping the PID that owns the controlled runtime tree."""
    monkeypatch.setattr(web_manager, "app_root", lambda: tmp_path)

    web_manager.write_metadata(
        8010,
        "0.0.0.0",
        launcher="service-run",
        launcher_pid=101,
    )

    metadata = web_manager.read_metadata(tmp_path)
    assert metadata["pid"] == os.getpid()
    assert metadata["launcher_pid"] == 101


def test_stop_web_terminates_launcher_tree_after_port_release(tmp_path, monkeypatch) -> None:
    """Catches stopping only the server child and leaving its launcher alive."""
    (tmp_path / ".picsyncra_web.pid").write_text(
        json.dumps({"pid": 102, "launcher_pid": 101}),
        encoding="ascii",
    )
    commands: list[list[str]] = []
    monkeypatch.setattr(web_manager, "app_root", lambda: tmp_path)
    monkeypatch.setattr(
        web_manager,
        "end_system_service",
        lambda: web_manager.ActionResult(True, ""),
    )
    monkeypatch.setattr(
        web_manager,
        "get_process_command_line",
        lambda _pid: "PicSyncra-WEB --service-run",
    )
    monkeypatch.setattr(web_manager, "get_port_listeners", lambda _port: [])
    monkeypatch.setattr(
        web_manager,
        "_run_command",
        lambda args, **_kwargs: commands.append(args)
        or subprocess.CompletedProcess(args, 0, "", ""),
    )

    result = web_manager.stop_web(8010)

    assert result.ok
    assert commands[0] == ["taskkill", "/PID", "101", "/T", "/F"]
    assert not (tmp_path / ".picsyncra_web.pid").exists()


def test_stop_web_terminates_recorded_launcher_when_cim_hides_command_line(
    tmp_path, monkeypatch
) -> None:
    """Catches leaving the launcher alive when Windows denies CIM command-line access."""
    (tmp_path / ".picsyncra_web.pid").write_text(
        json.dumps({"pid": 102, "launcher_pid": 101, "launcher": "start_web.ps1"}),
        encoding="ascii",
    )
    commands: list[list[str]] = []
    monkeypatch.setattr(web_manager, "app_root", lambda: tmp_path)
    monkeypatch.setattr(
        web_manager,
        "end_system_service",
        lambda: web_manager.ActionResult(True, ""),
    )
    monkeypatch.setattr(web_manager, "get_process_command_line", lambda _pid: "")
    monkeypatch.setattr(web_manager, "get_port_listeners", lambda _port: [])
    monkeypatch.setattr(
        web_manager,
        "_run_command",
        lambda args, **_kwargs: commands.append(args)
        or subprocess.CompletedProcess(args, 0, "", ""),
    )

    assert web_manager.stop_web(8010).ok

    assert commands == [["taskkill", "/PID", "101", "/T", "/F"]]


def test_stop_web_terminates_recorded_server_when_cim_hides_command_line(
    tmp_path, monkeypatch
) -> None:
    """Catches leaving a non-frozen service process alive after CIM access fails."""
    (tmp_path / ".picsyncra_web.pid").write_text(
        json.dumps({"pid": 102, "launcher": "service-run"}),
        encoding="ascii",
    )
    commands: list[list[str]] = []
    monkeypatch.setattr(web_manager, "app_root", lambda: tmp_path)
    monkeypatch.setattr(
        web_manager,
        "end_system_service",
        lambda: web_manager.ActionResult(True, ""),
    )
    monkeypatch.setattr(web_manager, "get_process_command_line", lambda _pid: "")
    monkeypatch.setattr(web_manager, "get_port_listeners", lambda _port: [])
    monkeypatch.setattr(
        web_manager,
        "_run_command",
        lambda args, **_kwargs: commands.append(args)
        or subprocess.CompletedProcess(args, 0, "", ""),
    )

    assert web_manager.stop_web(8010).ok

    assert commands == [["taskkill", "/PID", "102", "/T", "/F"]]


def test_stop_web_kills_the_listener_before_ending_the_system_task(tmp_path, monkeypatch) -> None:
    """Catches blocking on schtasks /End while Uvicorn still owns the panel port."""

    (tmp_path / ".picsyncra_web.pid").write_text(
        json.dumps({"pid": 102, "launcher": "service-run"}), encoding="ascii"
    )
    events: list[str] = []
    listener = {
        "Pid": 102,
        "ProcessName": "PicSyncra-WEB",
        "CommandLine": "PicSyncra-WEB --service-run",
    }
    listener_queries = 0

    def listeners(_port: int):
        nonlocal listener_queries
        listener_queries += 1
        return [listener] if listener_queries == 1 else []

    monkeypatch.setattr(web_manager, "app_root", lambda: tmp_path)
    monkeypatch.setattr(web_manager, "get_port_listeners", listeners)
    monkeypatch.setattr(
        web_manager,
        "get_process_command_line",
        lambda _pid: "PicSyncra-WEB --service-run",
    )
    monkeypatch.setattr(
        web_manager,
        "end_system_service",
        lambda: events.append("end") or web_manager.ActionResult(True, ""),
    )
    monkeypatch.setattr(
        web_manager,
        "_run_command",
        lambda args, **_kwargs: events.append("kill")
        or subprocess.CompletedProcess(args, 0, "", ""),
    )

    result = web_manager.stop_web(8010)

    assert result.ok
    assert events == ["kill", "end"]


def test_stop_web_kills_a_listener_identified_only_by_process_name(tmp_path, monkeypatch) -> None:
    """Catches leaving the panel alive when CIM hides its command line."""

    events: list[str] = []
    listener = {"Pid": 102, "ProcessName": "PicSyncra-WEB", "CommandLine": ""}
    listener_queries = 0

    def listeners(_port: int):
        nonlocal listener_queries
        listener_queries += 1
        return [listener] if listener_queries == 1 else []

    monkeypatch.setattr(web_manager, "app_root", lambda: tmp_path)
    monkeypatch.setattr(web_manager, "get_port_listeners", listeners)
    monkeypatch.setattr(web_manager, "get_process_command_line", lambda _pid: "")
    monkeypatch.setattr(
        web_manager,
        "end_system_service",
        lambda: events.append("end") or web_manager.ActionResult(True, ""),
    )
    monkeypatch.setattr(
        web_manager,
        "_run_command",
        lambda args, **_kwargs: events.append("kill")
        or subprocess.CompletedProcess(args, 0, "", ""),
    )

    result = web_manager.stop_web(8010)

    assert result.ok
    assert events == ["kill", "end"]


def test_frozen_service_records_its_pyinstaller_parent_as_launcher(tmp_path, monkeypatch) -> None:
    """Catches a frozen server persisting only its child PID."""
    metadata_calls = []
    fake_uvicorn = types.ModuleType("uvicorn")
    fake_uvicorn.run = lambda *_args, **_kwargs: None
    fake_web_app = types.ModuleType("picsyncra.web.app")
    fake_web_app.app = object()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(web_manager, "app_root", lambda: tmp_path)
    monkeypatch.setattr(web_manager.os, "getppid", lambda: 123)
    monkeypatch.setattr(
        web_manager,
        "write_metadata",
        lambda _port, _host, **kwargs: metadata_calls.append(kwargs),
    )
    monkeypatch.setattr(web_manager, "remove_metadata_for_current_process", lambda: None)
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)
    monkeypatch.setitem(sys.modules, "picsyncra.web.app", fake_web_app)
    monkeypatch.setattr(web_manager.sys, "frozen", True, raising=False)

    assert web_manager.run_service_mode(8010, "0.0.0.0") == 0

    assert metadata_calls == [{"launcher": "service-run", "launcher_pid": 123}]


def test_stop_web_keeps_metadata_when_taskkill_fails(tmp_path, monkeypatch) -> None:
    """Catches reporting shutdown success after Windows rejected taskkill."""
    pid_path = tmp_path / ".picsyncra_web.pid"
    pid_path.write_text(json.dumps({"pid": 102}), encoding="ascii")
    monkeypatch.setattr(web_manager, "app_root", lambda: tmp_path)
    monkeypatch.setattr(
        web_manager,
        "end_system_service",
        lambda: web_manager.ActionResult(True, ""),
    )
    monkeypatch.setattr(
        web_manager,
        "get_process_command_line",
        lambda _pid: "PicSyncra-WEB --service-run",
    )
    monkeypatch.setattr(web_manager, "get_port_listeners", lambda _port: [])
    monkeypatch.setattr(
        web_manager,
        "_run_command",
        lambda args, **_kwargs: subprocess.CompletedProcess(args, 5, "", "Access denied"),
    )

    result = web_manager.stop_web(8010)

    assert not result.ok
    assert "Access denied" in result.message
    assert pid_path.exists()


def test_end_system_service_reports_scheduler_error(monkeypatch) -> None:
    """Catches silently discarding a failed request to stop the SYSTEM task."""
    monkeypatch.setattr(web_manager, "task_exists", lambda: True)
    monkeypatch.setattr(
        web_manager,
        "_run_command",
        lambda args, **_kwargs: subprocess.CompletedProcess(args, 1, "", "Access denied"),
    )

    result = web_manager.end_system_service()

    assert not result.ok
    assert "Access denied" in result.message


def test_end_legacy_system_service_disables_old_autostart_before_stopping_it(monkeypatch) -> None:
    """Catches the old PicOrgFTP service reclaiming port 8010 after a reboot."""

    commands: list[list[str]] = []
    monkeypatch.setattr(web_manager, "legacy_task_exists", lambda: True)
    monkeypatch.setattr(
        web_manager,
        "_run_command",
        lambda args, **_kwargs: commands.append(args)
        or subprocess.CompletedProcess(args, 0, "", ""),
    )

    result = web_manager.end_legacy_system_service()

    assert result.ok
    assert commands == [
        ["schtasks", "/Change", "/TN", "PicOrgFTP-SQL Web", "/DISABLE"],
        ["schtasks", "/End", "/TN", "PicOrgFTP-SQL Web"],
    ]


def test_stop_web_returns_system_service_failure_without_claiming_success(
    tmp_path, monkeypatch
) -> None:
    """Catches discarding an access error from schtasks /End."""
    monkeypatch.setattr(web_manager, "app_root", lambda: tmp_path)
    monkeypatch.setattr(
        web_manager,
        "end_system_service",
        lambda: web_manager.ActionResult(False, "Access denied"),
    )

    result = web_manager.stop_web(8010)

    assert not result.ok
    assert "Access denied" in result.message


def test_start_web_reclaims_an_unhealthy_picsyncra_listener_before_restart(monkeypatch) -> None:
    """Catches starting a second Uvicorn process while the first owns the port."""

    events: list[str] = []
    listener = {
        "Pid": 102,
        "ProcessName": "PicSyncra-WEB",
        "CommandLine": "PicSyncra-WEB --service-run",
    }
    listener_queries = 0

    def listeners(_port: int):
        nonlocal listener_queries
        listener_queries += 1
        return [listener] if listener_queries == 1 else []

    monkeypatch.setattr(web_manager, "get_port_listeners", listeners)
    monkeypatch.setattr(web_manager, "check_http_health", lambda _port: {"ok": False})
    monkeypatch.setattr(
        web_manager,
        "stop_web",
        lambda _port: events.append("stop") or web_manager.ActionResult(True, "Zatrzymano."),
    )
    monkeypatch.setattr(web_manager, "task_exists", lambda: False)
    monkeypatch.setattr(
        web_manager,
        "start_user_web",
        lambda _port, _host, **_kwargs: events.append("start")
        or web_manager.ActionResult(True, "Uruchomiono."),
    )

    result = web_manager.start_web(8010, "0.0.0.0")

    assert result.ok
    assert events == ["stop", "start"]


def test_start_web_refuses_to_start_on_a_busy_non_picsyncra_port(monkeypatch) -> None:
    """Catches launching Uvicorn against an unrelated process that owns the configured port."""

    listener = {"Pid": 102, "ProcessName": "nginx", "CommandLine": "nginx: master process"}
    monkeypatch.setattr(web_manager, "get_port_listeners", lambda _port: [listener])
    monkeypatch.setattr(web_manager, "task_exists", lambda: False)
    monkeypatch.setattr(web_manager, "start_user_web", lambda *_args: pytest.fail("must not start"))

    result = web_manager.start_web(8010, "0.0.0.0")

    assert not result.ok
    assert "8010" in result.message


def test_start_web_replaces_a_legacy_picorgftp_service_on_the_shared_port(monkeypatch) -> None:
    """Catches opening the old PicOrgFTP backend after the PicSyncra rebrand."""

    legacy_stopped = False
    legacy_listener = {
        "Pid": 102,
        "ProcessName": "PicOrgFTP-SQL-WEB",
        "CommandLine": "PicOrgFTP-SQL-WEB.exe --service-run --port 8010",
    }

    def listeners(_port: int):
        return [] if legacy_stopped else [legacy_listener]

    def stop_legacy(_port: int) -> web_manager.ActionResult:
        nonlocal legacy_stopped
        legacy_stopped = True
        return web_manager.ActionResult(True, "Zatrzymano stary panel.")

    monkeypatch.setattr(web_manager, "get_port_listeners", listeners)
    monkeypatch.setattr(web_manager, "check_http_health", lambda _port: {"ok": True})
    monkeypatch.setattr(web_manager, "stop_legacy_web", stop_legacy)
    monkeypatch.setattr(web_manager, "task_exists", lambda: False)
    monkeypatch.setattr(
        web_manager,
        "start_user_web",
        lambda _port, _host, **_kwargs: web_manager.ActionResult(True, "Uruchomiono PicSyncra."),
    )

    result = web_manager.start_web(8010, "0.0.0.0")

    assert result.ok
    assert result.message == "Uruchomiono PicSyncra."
    assert legacy_stopped


def test_stop_legacy_web_accepts_a_service_process_ended_by_the_scheduler(monkeypatch) -> None:
    """Catches failing takeover after schtasks /End already stopped the old process."""

    listeners = [
        {
            "Pid": 102,
            "ProcessName": "PicOrgFTP-SQL-WEB",
            "CommandLine": "PicOrgFTP-SQL-WEB.exe --service-run --port 8010",
        }
    ]

    def end_legacy_service() -> web_manager.ActionResult:
        listeners.clear()
        return web_manager.ActionResult(True, "")

    monkeypatch.setattr(web_manager, "get_port_listeners", lambda _port: listeners)
    monkeypatch.setattr(web_manager, "end_legacy_system_service", end_legacy_service)
    monkeypatch.setattr(
        web_manager,
        "_taskkill_process_tree",
        lambda _pid: pytest.fail("scheduler already ended the legacy process"),
    )

    result = web_manager.stop_legacy_web(8010)

    assert result.ok


def test_start_web_refuses_a_mismatched_backend_identity(monkeypatch) -> None:
    """Catches accepting another product just because its process name looks similar."""

    listener = {
        "Pid": 102,
        "ProcessName": "PicSyncra-WEB",
        "CommandLine": "PicSyncra-WEB.exe --service-run --port 8010",
    }
    monkeypatch.setattr(web_manager, "get_port_listeners", lambda _port: [listener])
    monkeypatch.setattr(
        web_manager,
        "check_http_health",
        lambda _port: {"ok": True, "application": "picorgftp_sql"},
    )
    monkeypatch.setattr(web_manager, "start_user_web", lambda *_args, **_kwargs: pytest.fail("must not start"))

    result = web_manager.start_web(8010, "0.0.0.0")

    assert not result.ok
    assert "inna aplikacja" in result.message


def test_wait_web_ready_reports_each_startup_probe(monkeypatch) -> None:
    """The manager must show progress instead of appearing frozen during startup."""
    checks = iter([{"ok": False}, {"ok": True}])
    messages: list[str] = []
    monkeypatch.setattr(web_manager, "check_http_health", lambda *_args, **_kwargs: next(checks))
    monkeypatch.setattr(web_manager.time, "sleep", lambda _seconds: None)

    assert web_manager.wait_web_ready(8010, timeout=2, progress=messages.append)
    assert messages == ["Oczekiwanie na backend WWW (proba 1)...", "Backend WWW odpowiada."]


def test_wait_web_ready_requires_picsyncra_identity_for_a_new_process(monkeypatch) -> None:
    """Catches a new launch accepting a legacy backend that reclaimed its port."""

    checks = iter(
        [
            {"ok": True, "application": "picorgftp_sql"},
            {"ok": True, "application": "picsyncra"},
        ]
    )
    monkeypatch.setattr(web_manager, "check_http_health", lambda *_args, **_kwargs: next(checks))
    monkeypatch.setattr(web_manager.time, "sleep", lambda _seconds: None)

    assert web_manager.wait_web_ready(8010, timeout=2, expected_application="picsyncra")


def test_manager_stop_requests_an_elevated_stop_for_a_system_service(monkeypatch) -> None:
    """Catches a non-admin manager trying to taskkill a SYSTEM-owned process."""
    app = _app_without_tk()
    normal_actions = []
    elevated_ports = []
    app._run_action = lambda action: normal_actions.append(action)
    monkeypatch.setattr(web_manager, "task_exists", lambda: True)
    monkeypatch.setattr(web_manager, "is_admin", lambda: False)
    monkeypatch.setattr(
        web_manager,
        "stop_web_as_admin",
        lambda port: elevated_ports.append(port)
        or web_manager.ActionResult(True, "Potwierdz UAC."),
        raising=False,
    )

    app.stop()

    assert elevated_ports == [8010]
    assert normal_actions == []
    assert app.status_var.value == "Potwierdz UAC."


def test_main_stop_panel_mode_stops_the_panel_without_opening_the_gui(monkeypatch) -> None:
    """Catches an elevated EXE opening a second manager instead of stopping the task."""
    stopped_ports = []
    monkeypatch.setattr(
        web_manager,
        "stop_web",
        lambda port: stopped_ports.append(port) or web_manager.ActionResult(True, ""),
    )
    try:
        exit_code = web_manager.main(["--stop-panel", "--port", "8123"])
    except SystemExit:
        exit_code = None

    assert exit_code == 0
    assert stopped_ports == [8123]


def test_main_falls_back_to_browser_service_when_tkinter_is_unavailable(monkeypatch) -> None:
    """A frozen EXE must still open the web panel if PyInstaller omitted Tk."""
    started = []
    opened_urls = []

    class MissingTkManager:
        def __init__(self) -> None:
            raise ModuleNotFoundError("No module named 'tkinter'", name="tkinter")

    class ImmediateTimer:
        def __init__(self, _delay, callback) -> None:
            self.callback = callback
            self.daemon = False

        def start(self) -> None:
            self.callback()

    monkeypatch.setattr(web_manager, "WebManagerApp", MissingTkManager)
    monkeypatch.setattr(web_manager.threading, "Timer", ImmediateTimer)
    monkeypatch.setattr(
        web_manager.webbrowser, "open", lambda url, **_kwargs: opened_urls.append(url)
    )
    monkeypatch.setattr(
        web_manager,
        "run_service_mode",
        lambda port, host: started.append((port, host)) or 0,
    )

    assert web_manager.main(["--port", "8123", "--host", "0.0.0.0"]) == 0
    assert started == [(8123, "0.0.0.0")]
    assert opened_urls == ["http://127.0.0.1:8123"]


def test_stop_web_keeps_metadata_when_panel_port_stays_open(tmp_path, monkeypatch) -> None:
    """Catches removing runtime metadata before the web listener actually exits."""
    pid_path = tmp_path / ".picsyncra_web.pid"
    pid_path.write_text(json.dumps({"pid": 102}), encoding="ascii")
    listener = {
        "Pid": 102,
        "ProcessName": "PicSyncra-WEB",
        "CommandLine": "PicSyncra-WEB --service-run",
    }
    listener_queries = 0
    slept = []

    def listeners(_port: int):
        nonlocal listener_queries
        listener_queries += 1
        return [] if listener_queries == 1 else [listener]

    monkeypatch.setattr(web_manager, "app_root", lambda: tmp_path)
    monkeypatch.setattr(
        web_manager,
        "end_system_service",
        lambda: web_manager.ActionResult(True, ""),
    )
    monkeypatch.setattr(
        web_manager,
        "get_process_command_line",
        lambda _pid: "PicSyncra-WEB --service-run",
    )
    monkeypatch.setattr(web_manager, "get_port_listeners", listeners)
    monkeypatch.setattr(
        web_manager,
        "_run_command",
        lambda args, **_kwargs: subprocess.CompletedProcess(args, 0, "", ""),
    )
    monkeypatch.setattr(web_manager.time, "monotonic", lambda: 0 if not slept else 10)
    monkeypatch.setattr(web_manager.time, "sleep", lambda seconds: slept.append(seconds))

    result = web_manager.stop_web(8010)

    assert not result.ok
    assert "8010" in result.message
    assert slept == [0.2]
    assert pid_path.exists()


def test_finish_close_stop_keeps_gui_open_when_server_stop_fails() -> None:
    """Catches closing the manager after an unconfirmed server shutdown."""
    app = _app_without_tk()

    app._finish_close_stop(web_manager.ActionResult(False, "Port 8010 nadal dziala."))

    assert not app.root.destroyed
    assert app.status_var.value == "Port 8010 nadal dziala."


def test_close_window_starts_background_check_and_shows_spinner(monkeypatch) -> None:
    app = _app_without_tk()
    thread_targets = []
    thread_starts = []

    class FakeThread:
        def __init__(self, *, target, daemon: bool) -> None:
            thread_targets.append((target, daemon))

        def start(self) -> None:
            thread_starts.append(True)

    monkeypatch.setattr(web_manager.threading, "Thread", FakeThread)

    app.close_window()

    assert app.close_check_in_progress
    assert app.close_progress.started == 1
    assert app.status_var.value == "Sprawdzam, czy panel WWW dziala..."
    assert len(thread_targets) == 1
    assert thread_targets[0][1] is True
    assert thread_starts == [True]
    assert not app.root.destroyed


def test_finish_close_check_keeps_running_web_panel_accessible_in_tray(monkeypatch) -> None:
    app = _app_without_tk()
    hidden = []
    stopped = []
    app.minimize_to_tray = lambda: hidden.append(True)

    monkeypatch.setattr(web_manager, "confirm_close_running_web_panel", lambda: False, raising=False)
    monkeypatch.setattr(
        web_manager,
        "stop_web",
        lambda port: stopped.append(port) or web_manager.ActionResult(True, "Zatrzymano."),
    )
    app.close_check_in_progress = True
    app.close_progress.start()

    app._finish_close_check(True)

    assert hidden == [True]
    assert stopped == []
    assert not app.root.destroyed
    assert not app.close_check_in_progress
    assert app.close_progress.stopped == 1


def test_finish_close_check_stops_running_web_panel_in_background_when_user_confirms(monkeypatch) -> None:
    app = _app_without_tk()
    hidden = []
    stopped = []
    thread_targets = []
    thread_starts = []
    app.minimize_to_tray = lambda: hidden.append(True)

    class FakeThread:
        def __init__(self, *, target, daemon: bool) -> None:
            thread_targets.append((target, daemon))

        def start(self) -> None:
            thread_starts.append(True)

    monkeypatch.setattr(web_manager.threading, "Thread", FakeThread)
    monkeypatch.setattr(web_manager, "confirm_close_running_web_panel", lambda: True, raising=False)
    monkeypatch.setattr(web_manager, "task_exists", lambda: False)
    monkeypatch.setattr(
        web_manager,
        "stop_web",
        lambda port: stopped.append(port) or web_manager.ActionResult(True, "Zatrzymano."),
    )
    app.close_check_in_progress = True
    app.close_progress.start()

    app._finish_close_check(True)

    assert stopped == []
    assert hidden == []
    assert not app.root.destroyed
    assert app.close_check_in_progress
    assert app.status_var.value == "Zatrzymuje panel WWW..."
    assert len(thread_targets) == 1
    assert thread_targets[0][1] is True
    assert thread_starts == [True]

    thread_targets[0][0]()

    assert stopped == [8010]
    assert app.root.destroyed
    assert not app.close_check_in_progress
    assert app.close_progress.stopped == 2


def test_close_stop_requests_elevation_for_a_system_service(monkeypatch) -> None:
    app = _app_without_tk()
    elevated_ports = []
    normal_ports = []

    monkeypatch.setattr(web_manager, "task_exists", lambda: True)
    monkeypatch.setattr(web_manager, "is_admin", lambda: False)
    monkeypatch.setattr(
        web_manager,
        "stop_web_as_admin",
        lambda port: elevated_ports.append(port) or web_manager.ActionResult(True, "Potwierdz UAC."),
    )
    monkeypatch.setattr(web_manager, "stop_web", lambda port: normal_ports.append(port))
    monkeypatch.setattr(web_manager, "_wait_for_port_release", lambda _port, **_kwargs: True)

    app._stop_web_for_close_worker(8010)

    assert elevated_ports == [8010]
    assert normal_ports == []
    assert app.root.destroyed


def test_close_stop_limits_wait_for_elevated_process_termination(monkeypatch) -> None:
    """Catches keeping the manager open for 45 seconds after an elevated force-stop."""

    app = _app_without_tk()
    wait_timeouts: list[float] = []
    monkeypatch.setattr(web_manager, "task_exists", lambda: True)
    monkeypatch.setattr(web_manager, "is_admin", lambda: False)
    monkeypatch.setattr(
        web_manager,
        "stop_web_as_admin",
        lambda _port: web_manager.ActionResult(True, "Potwierdz UAC."),
    )
    monkeypatch.setattr(
        web_manager,
        "_wait_for_port_release",
        lambda _port, *, timeout: wait_timeouts.append(timeout) or True,
    )

    app._stop_web_for_close_worker(8010)

    assert wait_timeouts == [8.0]
    assert app.root.destroyed


def test_status_refresh_does_not_replace_stopping_feedback_while_close_is_active():
    app = _app_without_tk()
    app._refresh_account_rows = lambda: None
    app._set_rows = lambda *_args: None
    app.service_var = _FakeStringVar()
    app.autostart_var = _FakeStringVar()
    app.urls_list = types.SimpleNamespace(delete=lambda *_args: None, insert=lambda *_args: None)
    app.listeners_tree = object()
    app.users_tree = object()
    app.refreshing = True
    app.pending_refresh = False
    app.close_check_in_progress = True
    app.status_override_until = 0
    app.status_var.set("Zatrzymuje panel WWW...")

    app._apply_status(
        {
            "running": True,
            "listeners": [],
            "task_exists": True,
            "task_enabled": True,
            "admin": False,
            "urls": [],
            "clients": [],
            "connections": [],
        }
    )

    assert app.status_var.value == "Zatrzymuje panel WWW..."


def test_status_refresh_error_does_not_replace_stopping_feedback_while_close_is_active():
    app = _app_without_tk()
    app._refresh_account_rows = lambda: None
    app.refreshing = True
    app.pending_refresh = False
    app.close_check_in_progress = True
    app.status_override_until = 0
    app.status_var.set("Zatrzymuje panel WWW...")

    app._apply_status({"error": "connection reset"})

    assert app.status_var.value == "Zatrzymuje panel WWW..."
