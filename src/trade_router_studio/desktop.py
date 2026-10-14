from __future__ import annotations

import multiprocessing
import sys


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

    from trade_router_studio.cli import start

    start(foreground=False, no_browser=False)


if __name__ == "__main__":
    main()
