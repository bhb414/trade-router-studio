from __future__ import annotations

from typing import Any

import httpx
from trade_router.core.config import RouterPaths, daemon_base_url
from trade_router.core.secrets import DpapiSecretStore

from .errors import StudioError


def _validation_message(detail: Any) -> str | None:
    if not isinstance(detail, list) or not detail:
        return None
    first = detail[0]
    if not isinstance(first, dict):
        return None
    field = ".".join(str(item) for item in first.get("loc", [])[1:])
    message = str(first.get("msg") or "입력값을 확인하세요.")
    return f"{field}: {message}" if field else message


class RouterAdminClient:
    def __init__(self, *, base_url: str | None = None) -> None:
        self.base_url = (base_url or daemon_base_url()).rstrip("/")
        self._token: str | None = None
        self._client: httpx.AsyncClient | None = None

    @property
    def token(self) -> str:
        if self._token is None:
            self._token = DpapiSecretStore(
                RouterPaths.discover().secrets
            ).installation_token()
        return self._token

    async def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        timeout: float = 15,
    ) -> Any:
        try:
            if self._client is None:
                self._client = httpx.AsyncClient(
                    base_url=self.base_url,
                    headers={"authorization": f"Bearer {self.token}"},
                    timeout=15,
                    trust_env=False,
                )
            response = await self._client.request(
                method, path, json=json_body, timeout=timeout
            )
        except httpx.RequestError as exc:
            raise StudioError(
                "ROUTER_UNAVAILABLE",
                "Trade Router 데몬에 연결할 수 없습니다.",
                status_code=503,
            ) from exc
        if response.status_code >= 400:
            try:
                body = response.json()
                code = body.get("code", "ROUTER_ERROR")
                message = body.get("message") or _validation_message(body.get("detail"))
                if not message:
                    message = (
                        f"Trade Router 요청이 실패했습니다. (HTTP {response.status_code})"
                    )
            except ValueError:
                code = "ROUTER_HTTP_ERROR"
                message = f"Trade Router returned HTTP {response.status_code}."
            raise StudioError(code, message, status_code=response.status_code)
        return None if response.status_code == 204 else response.json()

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def health(self) -> dict[str, Any]:
        return await self.request("GET", "/v1/system/health", timeout=3)

    async def shutdown(self) -> dict[str, Any] | None:
        return await self.request("POST", "/v1/system/shutdown", timeout=10)

    async def profiles(self) -> list[dict[str, Any]]:
        return await self.request("GET", "/v1/profiles")

    async def capabilities(self) -> list[dict[str, Any]]:
        return await self.request("GET", "/v1/system/capabilities")

    async def register_profile(self, body: dict[str, Any]) -> dict[str, Any]:
        return await self.request("POST", "/v1/profiles", json_body=body)

    async def delete_profile(self, profile_id: str) -> None:
        await self.request("DELETE", f"/v1/profiles/{profile_id}")

    async def check_profile(
        self, profile_id: str, environment: str | None = None
    ) -> dict[str, Any]:
        suffix = f"?environment={environment}" if environment else ""
        return await self.request(
            "POST", f"/v1/profiles/{profile_id}/check{suffix}"
        )

    async def accounts(self) -> list[dict[str, Any]]:
        return await self.request("GET", "/v1/accounts")

    async def register_account(self, body: dict[str, Any]) -> dict[str, Any]:
        return await self.request("POST", "/v1/accounts", json_body=body)

    async def set_account_armed(self, alias: str, armed: bool) -> dict[str, Any]:
        action = "arm" if armed else "disarm"
        return await self.request("POST", f"/v1/accounts/{alias}/{action}")

    async def strategies(self) -> list[dict[str, Any]]:
        return await self.request("GET", "/v1/strategies")

    async def strategy(self, strategy_id: str) -> dict[str, Any]:
        return await self.request("GET", f"/v1/strategies/{strategy_id}")

    async def set_strategy_armed(self, strategy_id: str, armed: bool) -> dict[str, Any]:
        action = "arm" if armed else "disarm"
        return await self.request("POST", f"/v1/strategies/{strategy_id}/{action}")

    async def register_strategy(
        self,
        strategy_id: str,
        trading_account: str,
        market_data: str,
        market_environment: Any = None,
    ) -> dict[str, Any]:
        return await self.request(
            "POST",
            "/v1/strategies",
            json_body={
                "config": {
                    "id": strategy_id,
                    "trading_account": trading_account,
                    "market_data": market_data,
                    "market_environment": (
                        market_environment.value
                        if hasattr(market_environment, "value")
                        else market_environment
                    ),
                    "risk": {},
                }
            },
        )
