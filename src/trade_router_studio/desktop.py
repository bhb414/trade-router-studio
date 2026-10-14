from __future__ import annotations

import multiprocessing
import os
import sys
import time

_WINDOWS_CONTROL_HANDLER = None
_WINDOWS_JOB_HANDLE = None


def _pid_file_alive(path) -> bool:
    try:
        pid = int(path.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.windll.kernel32
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x00100000, False, pid)
    if not handle:
        return False
    try:
        return kernel.WaitForSingleObject(handle, 0) == 0x00000102
    finally:
        kernel.CloseHandle(handle)


def _install_windows_close_handler() -> None:
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes

    handler_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)

    @handler_type
    def handler(control_type: int) -> bool:
        # CTRL_CLOSE_EVENT, CTRL_LOGOFF_EVENT, CTRL_SHUTDOWN_EVENT. Let Python's
        # normal Ctrl+C handler raise KeyboardInterrupt for CTRL_C_EVENT.
        if control_type not in {2, 5, 6}:
            return False
        from trade_router_studio.cli import request_all_shutdowns

        request_all_shutdowns()
        return True

    global _WINDOWS_CONTROL_HANDLER
    _WINDOWS_CONTROL_HANDLER = handler
    ctypes.windll.kernel32.SetConsoleCtrlHandler(handler, True)


def _create_shutdown_job() -> None:
    """Keep child services tied to the console host as an abrupt-close fallback."""
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes

    class BasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class ExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BasicLimitInformation),
            ("IoInfo", IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel = ctypes.windll.kernel32
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        return
    information = ExtendedLimitInformation()
    # Keep services tied to the console while allowing the updater to request a
    # deliberate breakaway so it survives the console job closing.
    information.BasicLimitInformation.LimitFlags = 0x00002000 | 0x00000800
    if not kernel.SetInformationJobObject(
        job, 9, ctypes.byref(information), ctypes.sizeof(information)
    ):
        kernel.CloseHandle(job)
        return
    global _WINDOWS_JOB_HANDLE
    _WINDOWS_JOB_HANDLE = job


def _attach_service_processes_to_job() -> None:
    if os.name != "nt" or not _WINDOWS_JOB_HANDLE:
        return
    import ctypes
    from ctypes import wintypes

    from trade_router.core.config import RouterPaths

    from trade_router_studio.config import StudioPaths

    kernel = ctypes.windll.kernel32
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    for path in (RouterPaths.discover().pid, StudioPaths.discover().pid):
        try:
            pid = int(path.read_text(encoding="ascii").strip())
        except (OSError, ValueError):
            continue
        process = kernel.OpenProcess(0x0001 | 0x0100, False, pid)
        if not process:
            continue
        try:
            kernel.AssignProcessToJobObject(_WINDOWS_JOB_HANDLE, process)
        finally:
            kernel.CloseHandle(process)


def _close_shutdown_job() -> None:
    global _WINDOWS_JOB_HANDLE
    if os.name == "nt" and _WINDOWS_JOB_HANDLE:
        import ctypes

        ctypes.windll.kernel32.CloseHandle(_WINDOWS_JOB_HANDLE)
        _WINDOWS_JOB_HANDLE = None


def _run_console_host() -> None:
    from trade_router.core.config import RouterPaths

    from trade_router_studio.cli import start, stop_all
    from trade_router_studio.config import StudioPaths

    _install_windows_close_handler()
    _create_shutdown_job()
    start(foreground=False, no_browser=False)
    _attach_service_processes_to_job()
    print()
    print("Trade Router Studio가 실행 중입니다.")
    print("이 창을 닫거나 Ctrl+C를 누르면 Studio와 Router가 종료됩니다.")
    try:
        while _pid_file_alive(StudioPaths.discover().pid) or _pid_file_alive(
            RouterPaths.discover().pid
        ):
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        stop_all()
        _close_shutdown_job()


def main() -> None:
    """Dispatch the packaged desktop executable and its hidden child roles."""
    multiprocessing.freeze_support()
    role = sys.argv[1] if len(sys.argv) > 1 else ""
    if role == "--router-server":
        sys.argv = [sys.argv[0], *sys.argv[2:]]
        from trade_router.server.run import main as router_main

        router_main()
        return
    if role == "--studio-server":
        sys.argv = [sys.argv[0], *sys.argv[2:]]
        from trade_router_studio.server import main as server_main

        server_main()
        return
    if role == "--strategy-worker":
        sys.argv = [sys.argv[0], *sys.argv[2:]]
        from trade_router_studio.worker import main as worker_main

        worker_main()
        return
    if role == "--stop":
        from trade_router_studio.cli import stop_all

        stop_all()
        return

    _run_console_host()


if __name__ == "__main__":
    main()
