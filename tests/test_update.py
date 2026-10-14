from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import pytest

from trade_router_studio.config import StudioPaths
from trade_router_studio.errors import StudioError
from trade_router_studio.update import RELEASE_ASSET, UpdateService


def paths(tmp_path: Path) -> StudioPaths:
    return StudioPaths(
        home=tmp_path,
        database=tmp_path / "studio.db",
        secrets=tmp_path / "secrets.dpapi",
        pid=tmp_path / "studio.pid",
        server_log=tmp_path / "studio.log",
        script_dir=tmp_path / "scripts",
        strategy_log_dir=tmp_path / "strategy-logs",
    )


async def test_github_release_is_downloaded_and_verified(tmp_path):
    archive = b"PK\x03\x04test-release"
    digest = hashlib.sha256(archive).hexdigest()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/releases/latest"):
            return httpx.Response(
                200,
                json={
                    "tag_name": "v0.2.0",
                    "draft": False,
                    "prerelease": False,
                    "html_url": "https://github.com/bhb414/trade-router-studio/releases/tag/v0.2.0",
                    "published_at": "2026-10-14T12:00:00Z",
                    "assets": [
                        {
                            "name": RELEASE_ASSET,
                            "browser_download_url": f"https://github.com/download/{RELEASE_ASSET}",
                        },
                        {
                            "name": f"{RELEASE_ASSET}.sha256",
                            "browser_download_url": f"https://github.com/download/{RELEASE_ASSET}.sha256",
                        },
                    ],
                },
            )
        if request.url.path.endswith(".sha256"):
            return httpx.Response(200, content=f"{digest}  {RELEASE_ASSET}\n".encode())
        return httpx.Response(200, content=archive)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = UpdateService(paths(tmp_path), client=client)
        checked = await service.check()
        assert checked["available"] is True
        assert checked["package_ready"] is True
        downloaded = await service.download()

    assert Path(downloaded["archive"]).read_bytes() == archive
    assert downloaded["sha256"] == digest
    assert (await service.check(refresh=False))["downloaded"] is True


async def test_checksum_mismatch_is_rejected(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/releases/latest"):
            return httpx.Response(
                200,
                json={
                    "tag_name": "v0.2.0",
                    "draft": False,
                    "prerelease": False,
                    "assets": [
                        {
                            "name": RELEASE_ASSET,
                            "browser_download_url": f"https://github.com/download/{RELEASE_ASSET}",
                        },
                        {
                            "name": f"{RELEASE_ASSET}.sha256",
                            "browser_download_url": f"https://github.com/download/{RELEASE_ASSET}.sha256",
                        },
                    ],
                },
            )
        if request.url.path.endswith(".sha256"):
            return httpx.Response(200, content=("0" * 64).encode())
        return httpx.Response(200, content=b"changed")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = UpdateService(paths(tmp_path), client=client)
        with pytest.raises(StudioError, match="SHA-256"):
            await service.download()

    assert not list(tmp_path.glob("updates/*.zip"))
