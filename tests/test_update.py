from __future__ import annotations

import hashlib
import os
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


def test_installer_waits_for_console_studio_and_router(tmp_path, monkeypatch):
    active_paths = paths(tmp_path / "studio-home")
    service = UpdateService(active_paths)
    install_dir = tmp_path / "install"
    install_dir.mkdir()
    executable = install_dir / "TradeRouterStudio.exe"
    executable.write_bytes(b"studio")
    (install_dir / "TradeRouterUpdater.exe").write_bytes(b"updater")

    archive = service._download_path("0.1.6")
    archive.write_bytes(b"archive")
    archive.with_suffix(".sha256").write_text(
        hashlib.sha256(b"archive").hexdigest(), encoding="ascii"
    )
    router_home = active_paths.home.parent / "TradeRouter"
    router_home.mkdir(parents=True)
    (router_home / "daemon.pid").write_text("222", encoding="ascii")

    launched = []
    monkeypatch.setattr("trade_router_studio.update.sys.frozen", True, raising=False)
    monkeypatch.setattr("trade_router_studio.update.sys.executable", str(executable))
    monkeypatch.setenv("TRADE_STUDIO_HOST_PID", "111")
    monkeypatch.setattr(
        "trade_router_studio.update.subprocess.Popen",
        lambda *args, **kwargs: launched.append((args, kwargs)),
    )

    service.launch_installer("0.1.6")

    arguments = launched[0][0][0]
    waited = {
        int(arguments[index + 1])
        for index, value in enumerate(arguments)
        if value == "--wait-pid"
    }
    assert waited == {os.getpid(), 111, 222}
    assert launched[0][1]["creationflags"] & 0x01000000
