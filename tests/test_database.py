from __future__ import annotations

from trade_router_studio.database import StudioStore


async def test_script_round_trip(tmp_path):
    store = StudioStore(tmp_path / "studio.db")
    await store.open()
    try:
        saved = await store.save_script(
            strategy_id="sample",
            source="async def main(router):\n    pass\n",
            source_hash="abc",
        )
        assert saved.strategy_id == "sample"
        assert saved.desired_running is False
        running = await store.set_desired_running("sample", True)
        assert running.desired_running is True
        assert (await store.get_script("sample")).source_hash == "abc"
    finally:
        await store.close()
