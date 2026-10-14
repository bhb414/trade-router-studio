from __future__ import annotations

import multiprocessing
import os
import sys
import time

_WINDOWS_CONTROL_HANDLER = None


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


def _run_console_host() -> None:
    from trade_router_studio.cli import (
        _router_alive,
        _studio_alive,
        start,
        stop_all,
    )

    _install_windows_close_handler()
    start(foreground=False, no_browser=False)
    print()
    print("Trade Router Studio가 실행 중입니다.")
    print("이 창을 닫거나 Ctrl+C를 누르면 Studio와 Router가 종료됩니다.")
    try:
        while _studio_alive() or _router_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        stop_all()


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
