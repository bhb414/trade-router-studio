from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import secrets
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from trade_router.core.secrets import DpapiSecretStore

from .config import StudioPaths
from .database import StudioStore
from .errors import StudioError
from .models import (
    AccountRegistration,
    ProfileRegistration,
    ScriptUpdate,
    StrategyRegistration,
)
from .router_api import RouterAdminClient
from .runner import ScriptSupervisor, validate_source
from .update import UpdateService
from .version import __version__

_WEB_DIR = Path(__file__).resolve().parent / "web"
_UI_SESSION_SECONDS = 30 * 24 * 60 * 60
_TEMPLATE = '''"""Trade Router Studio strategy.

The strategy runs in its own process. Quotes, account data, and orders are always
requested through the central Trade Router daemon.
"""

import asyncio
from datetime import datetime


async def main(router):
    while True:
        quote = await router.market.quote(code="005930", venue="INTEGRATED")
        print(datetime.now().isoformat(timespec="seconds"), quote.instrument.code, quote.last)

        # Orders remain subject to central account and strategy arming and risk limits.
        # await router.orders.market_buy(
        #     code="005930",
        #     quantity=1,
        #     client_order_id=f"sample-{datetime.now():%Y%m%d-%H%M%S}",
        # )

        await asyncio.sleep(30)
'''


def _ui_session_cookie(token: str, *, expires_at: int | None = None) -> str:
    expires = expires_at or int(time.time()) + _UI_SESSION_SECONDS
    payload = f"v1:{expires}"
    signature = hmac.new(
        token.encode("utf-8"), payload.encode("ascii"), hashlib.sha256
    ).digest()
    encoded = base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
    return f"v1.{expires}.{encoded}"


def _valid_ui_session(cookie: str, token: str) -> bool:
    try:
        version, raw_expires, supplied_signature = cookie.split(".", 2)
        expires = int(raw_expires)
    except (TypeError, ValueError):
        return False
    if version != "v1" or expires <= int(time.time()):
        return False
    expected = _ui_session_cookie(token, expires_at=expires).rsplit(".", 1)[1]
    return secrets.compare_digest(supplied_signature, expected)


def create_app(
    *,
    paths: StudioPaths | None = None,
    store: StudioStore | None = None,
    router: RouterAdminClient | None = None,
    studio_token: str | None = None,
    updates: UpdateService | None = None,
) -> FastAPI:
    active_paths = paths or StudioPaths.discover()
    active_paths.ensure()
    active_store = store or StudioStore(active_paths.database)
    active_router = router or RouterAdminClient()
    supervisor = ScriptSupervisor(active_paths, active_store, active_router)
    update_service = updates or UpdateService(active_paths)
    token = studio_token or DpapiSecretStore(active_paths.secrets).installation_token()
    ui_codes: dict[str, float] = {}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await active_store.open()
        app.state.store = active_store
        app.state.router = active_router
        app.state.supervisor = supervisor
        app.state.updates = update_service
        await supervisor.restore()
        try:
            yield
        finally:
            await supervisor.close()
            await active_store.close()

    app = FastAPI(title="Trade Router Studio", version=__version__, lifespan=lifespan)

    @app.exception_handler(StudioError)
    async def studio_error(_: Request, exc: StudioError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "message": exc.message},
        )

    @app.exception_handler(KeyError)
    async def missing_record(_: Request, exc: KeyError):
        return JSONResponse(
            status_code=404,
            content={
                "code": "NOT_FOUND",
                "message": f"항목을 찾을 수 없습니다: {exc.args[0]}",
            },
        )

    def authorize(
        request: Request, authorization: Annotated[str | None, Header()] = None
    ) -> None:
        supplied = (
            authorization.removeprefix("Bearer ").strip() if authorization else ""
        )
        session = request.cookies.get("trade_studio_ui", "")
        session_ok = bool(session and _valid_ui_session(session, token))
        token_ok = bool(supplied and secrets.compare_digest(supplied, token))
        if not session_ok and not token_ok:
            raise StudioError(
                "STUDIO_AUTH_REQUIRED",
                "trade-studio open 명령으로 웹 화면을 여세요.",
                status_code=401,
            )

    secured = [Depends(authorize)]

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(_WEB_DIR / "index.html")

    app.mount("/assets", StaticFiles(directory=_WEB_DIR), name="assets")

    @app.post("/api/ui-session", dependencies=secured)
    async def create_ui_session():
        code = secrets.token_urlsafe(32)
        ui_codes[code] = time.monotonic() + 60
        return {"path": f"/auth?code={code}", "expires_in": 60}

    @app.get("/auth", include_in_schema=False)
    async def exchange_ui_code(code: str):
        if ui_codes.pop(code, 0) <= time.monotonic():
            return JSONResponse(
                status_code=401, content={"message": "웹 실행 주소가 만료되었습니다."}
            )
        session = _ui_session_cookie(token)
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            "trade_studio_ui",
            session,
            max_age=_UI_SESSION_SECONDS,
            httponly=True,
            samesite="strict",
            path="/",
        )
        return response

    @app.get("/api/health", dependencies=secured)
    async def health():
        try:
            router_health = await active_router.health()
            router_connected = True
        except StudioError as exc:
            router_health = {"status": "unavailable", "message": exc.message}
            router_connected = False
        statuses = await supervisor.statuses()
        return {
            "status": "ready" if router_connected else "degraded",
            "version": __version__,
            "router": router_health,
            "running_scripts": sum(
                item.state == "running" for item in statuses.values()
            ),
        }

    @app.get("/api/app/update", dependencies=secured)
    async def check_update(refresh: bool = Query(True)):
        return await update_service.check(refresh=refresh)

    @app.post("/api/app/update/download", dependencies=secured)
    async def download_update():
        return await update_service.download()

    async def stop_everything(request: Request) -> None:
        await asyncio.sleep(0.5)
        with suppress(StudioError):
            await active_router.shutdown()
        server = getattr(request.app.state, "server", None)
        if server is not None:
            server.should_exit = True

    @app.post("/api/app/update/apply", dependencies=secured)
    async def apply_update(request: Request, version: str = Query(..., min_length=1)):
        result = update_service.launch_installer(version)
        asyncio.create_task(stop_everything(request))
        return result

    @app.post("/api/app/stop", dependencies=secured)
    async def stop_app(request: Request):
        asyncio.create_task(stop_everything(request))
        return {"stopping": True}

    @app.get("/api/snapshot", dependencies=secured)
    async def snapshot():
        profiles, accounts, strategies = await asyncio.gather(
            active_router.profiles(),
            active_router.accounts(),
            active_router.strategies(),
        )
        scripts = {item.strategy_id: item for item in await active_store.list_scripts()}
        statuses = await supervisor.statuses()
        return {
            "profiles": profiles,
            "accounts": accounts,
            "strategies": [
                {
                    "strategy": strategy,
                    "script": scripts.get(strategy["id"]),
                    "process": statuses.get(strategy["id"]),
                }
                for strategy in strategies
            ],
        }

    @app.post("/api/strategies", dependencies=secured)
    async def register_strategy(body: StrategyRegistration):
        return await active_router.register_strategy(
            body.id, body.trading_account, body.market_data
        )

    @app.post("/api/profiles", dependencies=secured)
    async def register_profile(body: ProfileRegistration):
        return await active_router.register_profile(body.model_dump(mode="json"))

    @app.post("/api/profiles/{profile_id}/check", dependencies=secured)
    async def check_profile(profile_id: str):
        return await active_router.check_profile(profile_id)

    @app.post("/api/accounts", dependencies=secured)
    async def register_account(body: AccountRegistration):
        return await active_router.register_account(body.model_dump(mode="json"))

    @app.post("/api/accounts/{alias}/arm", dependencies=secured)
    async def arm_account(alias: str):
        return await active_router.set_account_armed(alias, True)

    @app.post("/api/accounts/{alias}/disarm", dependencies=secured)
    async def disarm_account(alias: str):
        return await active_router.set_account_armed(alias, False)

    @app.post("/api/strategies/{strategy_id}/arm", dependencies=secured)
    async def arm_strategy(strategy_id: str):
        return await active_router.set_strategy_armed(strategy_id, True)

    @app.post("/api/strategies/{strategy_id}/disarm", dependencies=secured)
    async def disarm_strategy(strategy_id: str):
        return await active_router.set_strategy_armed(strategy_id, False)

    @app.get("/api/strategies/{strategy_id}/script", dependencies=secured)
    async def get_script(strategy_id: str):
        return await active_store.get_script(strategy_id)

    @app.put("/api/strategies/{strategy_id}/script", dependencies=secured)
    async def save_script(strategy_id: str, body: ScriptUpdate):
        validation = validate_source(body.source)
        script = await supervisor.save(strategy_id, body.source)
        return {"script": script, "validation": validation}

    @app.post("/api/strategies/{strategy_id}/script/validate", dependencies=secured)
    async def validate_script(strategy_id: str, body: ScriptUpdate):
        await active_router.strategy(strategy_id)
        return validate_source(body.source)

    @app.get("/api/strategies/{strategy_id}/script/template", dependencies=secured)
    async def script_template(strategy_id: str):
        await active_router.strategy(strategy_id)
        return {"source": _TEMPLATE}

    @app.post("/api/strategies/{strategy_id}/start", dependencies=secured)
    async def start_script(strategy_id: str):
        return await supervisor.start(strategy_id)

    @app.post("/api/strategies/{strategy_id}/stop", dependencies=secured)
    async def stop_script(strategy_id: str):
        return await supervisor.stop(strategy_id)

    @app.get("/api/strategies/{strategy_id}/status", dependencies=secured)
    async def process_status(strategy_id: str):
        await active_router.strategy(strategy_id)
        return await supervisor.status(strategy_id)

    @app.get("/api/strategies/{strategy_id}/logs", dependencies=secured)
    async def process_logs(
        strategy_id: str, max_bytes: int = Query(65_536, ge=1_024, le=262_144)
    ):
        await active_router.strategy(strategy_id)
        return {"logs": supervisor.logs(strategy_id, max_bytes)}

    @app.post("/api/shutdown", dependencies=secured)
    async def shutdown(request: Request):
        server = getattr(request.app.state, "server", None)
        if server is not None:
            asyncio.get_running_loop().call_soon(setattr, server, "should_exit", True)
        return {"stopping": True}

    return app
