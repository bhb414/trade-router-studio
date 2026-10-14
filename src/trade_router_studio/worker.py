from __future__ import annotations

import asyncio
import importlib.util
import inspect
import os
import sys
from pathlib import Path

from trade_router import AsyncTradeRouter, StrategyConfig


async def run(source_path: Path) -> None:
    spec = importlib.util.spec_from_file_location(
        "trade_studio_user_strategy", source_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("전략 모듈을 불러올 수 없습니다.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    entrypoint = getattr(module, "main", None)
    if entrypoint is None or not inspect.iscoroutinefunction(entrypoint):
        raise RuntimeError("전략에 async def main(router)가 필요합니다.")
    config = StrategyConfig(
        id=os.environ["TRADE_STUDIO_STRATEGY_ID"],
        trading_account=os.environ["TRADE_STUDIO_ACCOUNT"],
        market_data=os.environ["TRADE_STUDIO_MARKET_DATA"],
        market_environment=os.environ["TRADE_STUDIO_MARKET_ENVIRONMENT"],
    )
    async with AsyncTradeRouter(
        strategy=config,
        base_url=os.environ["TRADE_STUDIO_ROUTER_URL"],
        token=os.environ["TRADE_STUDIO_ROUTER_TOKEN"],
    ) as router:
        await entrypoint(router)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m trade_router_studio.worker SCRIPT_PATH")
    asyncio.run(run(Path(sys.argv[1]).resolve()))


if __name__ == "__main__":
    main()
