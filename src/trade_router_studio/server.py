from __future__ import annotations

import os

import uvicorn

from .app import create_app
from .config import STUDIO_HOST, STUDIO_PORT


def main() -> None:
    port = int(os.environ.get("TRADE_ROUTER_STUDIO_PORT", str(STUDIO_PORT)))
    app = create_app()
    config = uvicorn.Config(
        app, host=STUDIO_HOST, port=port, log_level="info", access_log=False
    )
    server = uvicorn.Server(config)
    app.state.server = server
    server.run()


if __name__ == "__main__":
    main()
