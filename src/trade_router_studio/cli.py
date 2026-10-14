from __future__ import annotations

import os
import subprocess
import sys
import time
import webbrowser
from typing import Any

import httpx
import typer
from rich.console import Console
from rich.table import Table
from trade_router.core.config import RouterPaths, daemon_base_url
from trade_router.core.secrets import DpapiSecretStore

from .config import StudioPaths, studio_base_url

app = typer.Typer(help="Web strategy studio powered by Trade Router")
console = Console()


def _background_python() -> str:
    if os.name != "nt":
        return sys.executable
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return pythonw if os.path.exists(pythonw) else sys.executable


def _packaged() -> bool:
    return bool(getattr(sys, "frozen", False))


def _studio_token() -> str:
    paths = StudioPaths.discover()
    paths.ensure()
    return DpapiSecretStore(paths.secrets).installation_token()


def _request(method: str, path: str, *, timeout: float = 5) -> Any:
    try:
        response = httpx.request(
            method,
            studio_base_url() + path,
            headers={"authorization": f"Bearer {_studio_token()}"},
            timeout=timeout,
        )
    except httpx.RequestError as exc:
        raise typer.BadParameter("Trade Router Studio가 실행 중이지 않습니다.") from exc
    if response.status_code >= 400:
        try:
            body = response.json()
            message = f"{body.get('code', 'ERROR')}: {body.get('message', '')}"
        except ValueError:
            message = f"HTTP {response.status_code}"
        raise typer.BadParameter(message)
    return response.json() if response.content else None


def _studio_alive() -> bool:
    try:
        _request("GET", "/api/health", timeout=1)
        return True
    except typer.BadParameter:
        return False


def _router_alive() -> bool:
    try:
        token = DpapiSecretStore(RouterPaths.discover().secrets).installation_token()
        response = httpx.get(
            daemon_base_url() + "/v1/system/health",
            headers={"authorization": f"Bearer {token}"},
            timeout=1,
        )
        return response.status_code == 200
    except Exception:  # noqa: BLE001 - health probing must never abort CLI startup
        return False


def _ensure_router() -> None:
    if _router_alive():
        return
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    if _packaged():
        paths = RouterPaths.discover()
        paths.ensure()
        with paths.daemon_log.open("a", encoding="utf-8") as log:
            process = subprocess.Popen(
                [sys.executable, "--router-server"],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                creationflags=flags | (subprocess.DETACHED_PROCESS if os.name == "nt" else 0),
                cwd=str(paths.home),
                close_fds=True,
            )
        paths.pid.write_text(str(process.pid), encoding="ascii")
        for _ in range(40):
            if _router_alive():
                return
            if process.poll() is not None:
                break
            time.sleep(0.25)
    else:
        result = subprocess.run(
            [sys.executable, "-m", "trade_router.cli", "daemon", "start"],
            check=False,
            creationflags=flags,
        )
        if result.returncode == 0 and _router_alive():
            return
    raise typer.BadParameter("Trade Router 데몬을 시작하지 못했습니다.")


def _open_browser() -> None:
    session = _request("POST", "/api/ui-session")
    url = studio_base_url() + session["path"]
    if webbrowser.open(url):
        console.print("Trade Router Studio를 브라우저에서 열었습니다.")
    else:
        console.print(f"브라우저에서 다음 주소를 여세요: {url}")


@app.command("start")
def start(
    foreground: bool = typer.Option(False, "--foreground"),
    no_browser: bool = typer.Option(False, "--no-browser"),
) -> None:
    _ensure_router()
    if _studio_alive():
        console.print("Trade Router Studio가 이미 실행 중입니다.")
        if not no_browser:
            _open_browser()
        return
    paths = StudioPaths.discover()
    paths.ensure()
    if foreground:
        from .server import main

        main()
        return
    flags = (
        subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
        if os.name == "nt"
        else 0
    )
    with paths.server_log.open("a", encoding="utf-8") as log:
        command = (
            [sys.executable, "--studio-server"]
            if _packaged()
            else [_background_python(), "-m", "trade_router_studio.server"]
        )
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            creationflags=flags,
            cwd=str(paths.home),
            close_fds=True,
        )
    paths.pid.write_text(str(process.pid), encoding="ascii")
    for _ in range(40):
        if _studio_alive():
            console.print(
                f"Trade Router Studio started on {studio_base_url()} (PID {process.pid})."
            )
            if not no_browser:
                _open_browser()
            return
        if process.poll() is not None:
            break
        time.sleep(0.25)
    raise typer.BadParameter(f"Studio를 시작하지 못했습니다. 로그: {paths.server_log}")


@app.command("open")
def open_console() -> None:
    if not _studio_alive():
        start(foreground=False, no_browser=True)
    _open_browser()


@app.command("stop")
def stop() -> None:
    paths = StudioPaths.discover()
    if not _studio_alive():
        paths.pid.unlink(missing_ok=True)
        console.print("Trade Router Studio가 실행 중이지 않습니다.")
        return
    _request("POST", "/api/shutdown")
    for _ in range(40):
        if not _studio_alive():
            paths.pid.unlink(missing_ok=True)
            console.print("Trade Router Studio를 종료했습니다.")
            return
        time.sleep(0.25)
    console.print("종료 작업을 정리하고 있습니다.")


def stop_all() -> None:
    """Stop Studio and the central Router for the packaged desktop app."""
    stop()
    _request_router_shutdown()


def request_all_shutdowns() -> None:
    """Submit shutdown requests without waiting, for a closing console handler."""
    try:
        httpx.post(
            studio_base_url() + "/api/shutdown",
            headers={"authorization": f"Bearer {_studio_token()}"},
            timeout=1,
        )
    except httpx.RequestError:
        pass
    try:
        router_token = DpapiSecretStore(
            RouterPaths.discover().secrets
        ).installation_token()
        httpx.post(
            daemon_base_url() + "/v1/system/shutdown",
            headers={"authorization": f"Bearer {router_token}"},
            timeout=1,
        )
    except httpx.RequestError:
        pass


def _request_router_shutdown() -> None:
    if not _router_alive():
        return
    try:
        token = DpapiSecretStore(RouterPaths.discover().secrets).installation_token()
        httpx.post(
            daemon_base_url() + "/v1/system/shutdown",
            headers={"authorization": f"Bearer {token}"},
            timeout=5,
        )
    except httpx.RequestError:
        return


@app.command("status")
def status() -> None:
    data = _request("GET", "/api/health")
    table = Table("항목", "상태")
    table.add_row("Studio", data["status"])
    table.add_row("Trade Router", data["router"]["status"])
    table.add_row("실행 전략", str(data["running_scripts"]))
    console.print(table)


if __name__ == "__main__":
    app()
