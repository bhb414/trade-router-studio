from __future__ import annotations

import httpx

from trade_router_studio.app import create_app
from trade_router_studio.config import StudioPaths
from trade_router_studio.database import StudioStore


class StubRouter:
    base_url = "http://router.test"
    token = "router-token"

    async def health(self):
        return {"status": "ready", "accepting_orders": True}

    async def profiles(self):
        return [{"id": "simulated-main", "provider": "simulated"}]

    async def accounts(self):
        return [{"alias": "paper-main", "profile_id": "simulated-main"}]

    async def strategies(self):
        return [
            {
                "id": "sample",
                "trading_account": "paper-main",
                "market_data": "simulated-main",
            }
        ]

    async def strategy(self, strategy_id):
        return (await self.strategies())[0] | {"id": strategy_id}

    async def register_strategy(self, strategy_id, trading_account, market_data):
        return {
            "id": strategy_id,
            "trading_account": trading_account,
            "market_data": market_data,
        }


def paths(tmp_path):
    return StudioPaths(
        home=tmp_path,
        database=tmp_path / "studio.db",
        secrets=tmp_path / "secrets.dpapi",
        pid=tmp_path / "studio.pid",
        server_log=tmp_path / "studio.log",
        script_dir=tmp_path / "scripts",
        strategy_log_dir=tmp_path / "strategy-logs",
    )


async def test_web_auth_and_script_save(tmp_path):
    active_paths = paths(tmp_path)
    active_paths.ensure()
    app = create_app(
        paths=active_paths,
        store=StudioStore(active_paths.database),
        router=StubRouter(),
        studio_token="studio-token",
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://studio.test"
        ) as client:
            assert (await client.get("/api/health")).status_code == 401
            headers = {"authorization": "Bearer studio-token"}
            session = await client.post("/api/ui-session", headers=headers)
            auth = await client.get(session.json()["path"], follow_redirects=False)
            assert auth.status_code == 303
            assert "trade_studio_ui" in auth.cookies
            client.cookies.update(auth.cookies)
            assert (await client.get("/api/health")).status_code == 200
            saved = await client.put(
                "/api/strategies/sample/script",
                json={"source": "async def main(router):\n    return None\n"},
            )
            assert saved.status_code == 200
            assert saved.json()["validation"]["valid"] is True
