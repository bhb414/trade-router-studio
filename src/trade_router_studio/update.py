from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from packaging.version import InvalidVersion, Version

from .config import StudioPaths
from .errors import StudioError
from .version import __version__

DEFAULT_UPDATE_REPOSITORY = "bhb414/trade-router-studio"
RELEASE_ASSET = "TradeRouterStudio-windows-x64.zip"
MAX_RELEASE_BYTES = 500 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class DownloadedUpdate:
    version: str
    archive: Path
    sha256: str


class UpdateService:
    def __init__(
        self,
        paths: StudioPaths,
        *,
        repository: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.paths = paths
        self.repository = (
            repository
            or os.environ.get("TRADE_ROUTER_STUDIO_UPDATE_REPOSITORY", "").strip()
            or DEFAULT_UPDATE_REPOSITORY
        )
        self._client = client
        self._latest: dict[str, Any] | None = None

    @property
    def update_dir(self) -> Path:
        path = self.paths.home / "updates"
        path.mkdir(parents=True, exist_ok=True)
        return path

    async def check(self, *, refresh: bool = True) -> dict[str, Any]:
        release = await self._release(refresh=refresh)
        latest = self._tag_version(release.get("tag_name", ""))
        try:
            available = Version(latest) > Version(__version__)
        except InvalidVersion as exc:
            raise StudioError(
                "UPDATE_VERSION_INVALID",
                "GitHub 배포 버전 형식이 올바르지 않습니다.",
                status_code=502,
            ) from exc
        assets = {item.get("name"): item for item in release.get("assets", [])}
        package_ready = RELEASE_ASSET in assets and f"{RELEASE_ASSET}.sha256" in assets
        downloaded = self._download_path(latest).is_file()
        return {
            "current_version": __version__,
            "latest_version": latest,
            "available": available,
            "package_ready": package_ready,
            "downloaded": downloaded,
            "can_apply": bool(getattr(sys, "frozen", False)),
            "release_url": release.get("html_url"),
            "published_at": release.get("published_at"),
        }

    async def download(self) -> dict[str, Any]:
        release = await self._release(refresh=True)
        version = self._tag_version(release.get("tag_name", ""))
        assets = {item.get("name"): item for item in release.get("assets", [])}
        package = assets.get(RELEASE_ASSET)
        checksum = assets.get(f"{RELEASE_ASSET}.sha256")
        if not package or not checksum:
            raise StudioError(
                "UPDATE_ASSET_MISSING",
                "GitHub 배포에 Windows ZIP 또는 SHA-256 파일이 없습니다.",
                status_code=502,
            )
        archive_path = self._download_path(version)
        checksum_text = (
            await self._get_bytes(checksum["browser_download_url"], max_bytes=4096)
        ).decode("ascii", errors="strict")
        expected = checksum_text.strip().split()[0].lower()
        if len(expected) != 64 or any(ch not in "0123456789abcdef" for ch in expected):
            raise StudioError(
                "UPDATE_CHECKSUM_INVALID",
                "배포 SHA-256 파일 형식이 올바르지 않습니다.",
                status_code=502,
            )
        temporary = archive_path.with_suffix(".download")
        temporary.unlink(missing_ok=True)
        digest = hashlib.sha256()
        size = 0
        client = self._client or httpx.AsyncClient(
            follow_redirects=True,
            headers={"user-agent": f"TradeRouterStudio/{__version__}"},
            timeout=httpx.Timeout(30, read=120),
        )
        close_client = self._client is None
        try:
            self._validate_download_url(package["browser_download_url"])
            async with client.stream("GET", package["browser_download_url"]) as response:
                response.raise_for_status()
                with temporary.open("wb") as handle:
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_RELEASE_BYTES:
                            raise StudioError(
                                "UPDATE_TOO_LARGE",
                                "업데이트 파일이 허용 크기를 초과했습니다.",
                                status_code=502,
                            )
                        digest.update(chunk)
                        handle.write(chunk)
        except httpx.HTTPError as exc:
            temporary.unlink(missing_ok=True)
            raise StudioError(
                "UPDATE_DOWNLOAD_FAILED",
                "GitHub에서 업데이트 파일을 내려받지 못했습니다.",
                status_code=502,
            ) from exc
        finally:
            if close_client:
                await client.aclose()
        actual = digest.hexdigest()
        if actual != expected:
            temporary.unlink(missing_ok=True)
            raise StudioError(
                "UPDATE_CHECKSUM_MISMATCH",
                "업데이트 파일의 SHA-256이 배포 정보와 일치하지 않습니다.",
                status_code=502,
            )
        os.replace(temporary, archive_path)
        (archive_path.with_suffix(".sha256")).write_text(actual, encoding="ascii")
        return {
            "version": version,
            "archive": str(archive_path),
            "sha256": actual,
            "size": size,
        }

    def launch_installer(self, version: str) -> dict[str, Any]:
        if not getattr(sys, "frozen", False):
            raise StudioError(
                "UPDATE_PACKAGED_APP_REQUIRED",
                "개발 실행본에서는 자동 적용할 수 없습니다. 배포 실행 파일에서 이용하세요.",
                status_code=409,
            )
        archive = self._download_path(version)
        digest_path = archive.with_suffix(".sha256")
        if not archive.is_file() or not digest_path.is_file():
            raise StudioError(
                "UPDATE_NOT_DOWNLOADED",
                "먼저 업데이트 파일을 내려받으세요.",
                status_code=409,
            )
        expected = digest_path.read_text(encoding="ascii").strip()
        actual = self._hash_file(archive)
        if actual != expected:
            raise StudioError(
                "UPDATE_CHECKSUM_MISMATCH",
                "저장된 업데이트 파일이 변경되었습니다. 다시 내려받으세요.",
                status_code=409,
            )
        install_dir = Path(sys.executable).resolve().parent
        bundled_updater = install_dir / "TradeRouterUpdater.exe"
        if not bundled_updater.is_file():
            raise StudioError(
                "UPDATER_MISSING",
                "배포본에서 업데이트 실행 파일을 찾을 수 없습니다.",
                status_code=500,
            )
        updater_copy = self.update_dir / "TradeRouterUpdater.exe"
        shutil.copy2(bundled_updater, updater_copy)
        router_pid = self._read_pid(self.paths.home.parent / "TradeRouter" / "daemon.pid")
        try:
            host_pid = int(os.environ.get("TRADE_STUDIO_HOST_PID", "0"))
        except ValueError:
            host_pid = 0
        arguments = [
            str(updater_copy),
            "--archive",
            str(archive),
            "--target",
            str(install_dir),
            "--launch",
            "TradeRouterStudio.exe",
        ]
        wait_pids = dict.fromkeys(
            pid for pid in (os.getpid(), host_pid, router_pid) if pid and pid > 0
        )
        for pid in wait_pids:
            arguments.extend(["--wait-pid", str(pid)])
        flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS if os.name == "nt" else 0
        subprocess.Popen(
            arguments,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(self.update_dir),
            creationflags=flags,
            close_fds=True,
        )
        return {"restarting": True, "version": version}

    async def _release(self, *, refresh: bool) -> dict[str, Any]:
        if self._latest is not None and not refresh:
            return self._latest
        url = f"https://api.github.com/repos/{self.repository}/releases/latest"
        client = self._client or httpx.AsyncClient(
            follow_redirects=True,
            headers={
                "accept": "application/vnd.github+json",
                "user-agent": f"TradeRouterStudio/{__version__}",
                "x-github-api-version": "2022-11-28",
            },
            timeout=15,
        )
        try:
            response = await client.get(url)
            if response.status_code == 404:
                raise StudioError(
                    "UPDATE_RELEASE_NOT_FOUND",
                    "아직 공개된 GitHub 배포 버전이 없습니다.",
                    status_code=404,
                )
            response.raise_for_status()
            release = response.json()
        except StudioError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise StudioError(
                "UPDATE_CHECK_FAILED",
                "GitHub 업데이트 정보를 확인하지 못했습니다.",
                status_code=502,
            ) from exc
        finally:
            if self._client is None:
                await client.aclose()
        if release.get("draft") or release.get("prerelease"):
            raise StudioError(
                "UPDATE_RELEASE_INVALID",
                "최신 GitHub 배포가 정식 버전이 아닙니다.",
                status_code=502,
            )
        self._latest = release
        return release

    async def _get_bytes(self, url: str, *, max_bytes: int) -> bytes:
        self._validate_download_url(url)
        client = self._client or httpx.AsyncClient(
            follow_redirects=True,
            headers={"user-agent": f"TradeRouterStudio/{__version__}"},
            timeout=20,
        )
        try:
            response = await client.get(url)
            response.raise_for_status()
            content = response.content
        except httpx.HTTPError as exc:
            raise StudioError(
                "UPDATE_DOWNLOAD_FAILED",
                "GitHub 배포 확인 파일을 내려받지 못했습니다.",
                status_code=502,
            ) from exc
        finally:
            if self._client is None:
                await client.aclose()
        if len(content) > max_bytes:
            raise StudioError(
                "UPDATE_RESPONSE_TOO_LARGE",
                "GitHub 배포 확인 파일이 비정상적으로 큽니다.",
                status_code=502,
            )
        return content

    def _download_path(self, version: str) -> Path:
        safe_version = "".join(ch for ch in version if ch.isalnum() or ch in ".-_")
        return self.update_dir / f"TradeRouterStudio-{safe_version}.zip"

    @staticmethod
    def _tag_version(tag: str) -> str:
        value = str(tag).strip()
        return value[1:] if value.lower().startswith("v") else value

    @staticmethod
    def _hash_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _validate_download_url(url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in {
            "github.com",
            "objects.githubusercontent.com",
        }:
            raise StudioError(
                "UPDATE_URL_REJECTED",
                "허용되지 않은 업데이트 다운로드 주소입니다.",
                status_code=502,
            )

    @staticmethod
    def _read_pid(path: Path) -> int | None:
        try:
            value = int(path.read_text(encoding="ascii").strip())
            return value if value > 0 else None
        except (OSError, ValueError):
            return None
