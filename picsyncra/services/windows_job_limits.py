"""Best-effort Windows Job Object controls for an isolated OCR worker."""

from __future__ import annotations

from dataclasses import dataclass
import ctypes
from ctypes import wintypes
import os
from typing import Protocol


_JOB_OBJECT_CPU_RATE_CONTROL_INFORMATION = 15
_JOB_OBJECT_CPU_RATE_CONTROL_ENABLE = 0x1
_JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP = 0x4
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_TERMINATE = 0x0001


class _CpuRateControlInformation(ctypes.Structure):
    _fields_ = [
        ("ControlFlags", wintypes.DWORD),
        ("CpuRate", wintypes.DWORD),
    ]


class WindowsJobApi(Protocol):
    def create_job(self) -> int: ...

    def assign_process(self, job_handle: int, pid: int) -> None: ...

    def set_cpu_hard_cap(self, job_handle: int, cpu_rate: int) -> None: ...

    def close_handle(self, handle: int) -> None: ...


@dataclass(frozen=True)
class JobLimitCapability:
    available: bool
    cpu_percent: int
    message: str = ""


class _NativeWindowsJobApi:
    def __init__(self) -> None:
        if os.name != "nt":
            raise OSError("Windows Job Object is unavailable on this system.")
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
        self._kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        self._kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        self._kernel32.OpenProcess.restype = wintypes.HANDLE
        self._kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        self._kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        self._kernel32.SetInformationJobObject.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
        )
        self._kernel32.SetInformationJobObject.restype = wintypes.BOOL
        self._kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        self._kernel32.CloseHandle.restype = wintypes.BOOL

    @staticmethod
    def _check(handle: int | None, operation: str) -> int:
        if not handle:
            raise OSError(ctypes.get_last_error(), operation)
        return int(handle)

    def create_job(self) -> int:
        return self._check(self._kernel32.CreateJobObjectW(None, None), "CreateJobObjectW")

    def assign_process(self, job_handle: int, pid: int) -> None:
        process = self._check(
            self._kernel32.OpenProcess(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, pid),
            "OpenProcess",
        )
        try:
            if not self._kernel32.AssignProcessToJobObject(job_handle, process):
                raise OSError(ctypes.get_last_error(), "AssignProcessToJobObject")
        finally:
            self.close_handle(process)

    def set_cpu_hard_cap(self, job_handle: int, cpu_rate: int) -> None:
        information = _CpuRateControlInformation(
            _JOB_OBJECT_CPU_RATE_CONTROL_ENABLE | _JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP,
            cpu_rate,
        )
        if not self._kernel32.SetInformationJobObject(
            job_handle,
            _JOB_OBJECT_CPU_RATE_CONTROL_INFORMATION,
            ctypes.byref(information),
            ctypes.sizeof(information),
        ):
            raise OSError(ctypes.get_last_error(), "SetInformationJobObject")

    def close_handle(self, handle: int) -> None:
        if handle and not self._kernel32.CloseHandle(handle):
            raise OSError(ctypes.get_last_error(), "CloseHandle")


class WindowsJobLimits:
    """Hold one Job Object handle for the lifetime of an OCR worker process."""

    def __init__(self, *, api: WindowsJobApi | None = None) -> None:
        self._api = api
        self._handle: int | None = None

    def apply_to_process(self, *, pid: int, cpu_percent: int) -> JobLimitCapability:
        """Assign the worker to a hard-capped Job Object without raising on fallback."""

        target = max(1, min(100, int(cpu_percent)))
        try:
            api = self._api or _NativeWindowsJobApi()
            if self._handle is None:
                self._handle = api.create_job()
            api.assign_process(self._handle, int(pid))
            api.set_cpu_hard_cap(self._handle, target * 100)
        except (OSError, TypeError, ValueError) as exc:
            return JobLimitCapability(False, target, str(exc) or "CPU limit unavailable.")
        return JobLimitCapability(True, target, "Windows Job Object CPU hard cap active.")

    def close(self) -> None:
        """Release the Job Object after the worker has stopped."""

        if self._handle is None:
            return
        handle, self._handle = self._handle, None
        try:
            (self._api or _NativeWindowsJobApi()).close_handle(handle)
        except OSError:
            pass
