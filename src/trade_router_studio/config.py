from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_path


@dataclass(frozen=True, slots=True)
class StudioPaths:
    home: Path
    database: Path
    secrets: Path
    pid: Path
    server_log: Path
    script_dir: Path
    strategy_log_dir: Path

    @classmethod
    def discover(cls) -> StudioPaths:
        override = os.environ.get("TRADE_ROUTER_STUDIO_HOME", "").strip()
        home = (
            Path(override).expanduser().resolve()
            if override
            else user_data_path(
                appname="TradeRouterStudio",
                appauthor="bhb414",
                roaming=False,
                ensure_exists=False,
            )
        )
        return cls(
            home=home,
            database=home / "studio.db",
            secrets=home / "secrets.dpapi",
            pid=home / "studio.pid",
            server_log=home / "studio.log",
            script_dir=home / "scripts",
            strategy_log_dir=home / "strategy-logs",
        )

    def ensure(self) -> None:
        for path in (self.home, self.script_dir, self.strategy_log_dir):
            path.mkdir(parents=True, exist_ok=True)


STUDIO_HOST = "127.0.0.1"
STUDIO_PORT = 8890


def studio_base_url() -> str:
    port = int(os.environ.get("TRADE_ROUTER_STUDIO_PORT", str(STUDIO_PORT)))
    return f"http://{STUDIO_HOST}:{port}"
