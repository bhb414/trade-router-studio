from __future__ import annotations

import ast
import asyncio
import hashlib
import os
import subprocess
import sys
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any

from .config import StudioPaths
from .database import StudioStore
from .errors import StudioError
from .models import ProcessStatus, ScriptRecord
from .router_api import RouterAdminClient

MAX_SCRIPT_BYTES = 262_144
MAX_RESTARTS = 5


def validate_source(source: str) -> dict[str, Any]:
    size = len(source.encode("utf-8"))
    if size > MAX_SCRIPT_BYTES:
        raise StudioError(
            "SCRIPT_TOO_LARGE",
            f"전략 스크립트는 {MAX_SCRIPT_BYTES:,}바이트까지 저장할 수 있습니다.",
            status_code=413,
        )
    try:
        tree = ast.parse(source, filename="strategy.py")
    except SyntaxError as exc:
        raise StudioError(
            "SCRIPT_SYNTAX_ERROR",
            f"{exc.lineno}행 {exc.offset or 0}열: {exc.msg}",
            status_code=422,
        ) from exc
    mains = [
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "main"
    ]
    if not mains:
        raise StudioError(
            "SCRIPT_ENTRYPOINT_REQUIRED",
            "async def main(router) 진입점을 작성하세요.",
            status_code=422,
        )
    positional = [*mains[0].args.posonlyargs, *mains[0].args.args]
    if len(positional) != 1 or mains[0].args.vararg is not None:
        raise StudioError(
            "SCRIPT_ENTRYPOINT_INVALID",
            "main 함수는 router 매개변수 하나만 받아야 합니다.",
            status_code=422,
        )
    return {
        "valid": True,
        "bytes": size,
        "source_hash": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "entrypoint": "main",
    }


@dataclass(slots=True)
class _Handle:
    status: ProcessStatus
    task: asyncio.Task[None] | None = None
    process: asyncio.subprocess.Process | None = None
    stop_requested: bool = False
    ready: asyncio.Event = field(default_factory=asyncio.Event)


class ScriptSupervisor:
    def __init__(
        self, paths: StudioPaths, store: StudioStore, router: RouterAdminClient
    ) -> None:
        self.paths = paths
        self.store = store
        self.router = router
        self._handles: dict[str, _Handle] = {}
        self._lock = asyncio.Lock()
        self._closing = False

    async def restore(self) -> None:
        for script in await self.store.list_scripts():
            if script.desired_running:
                with suppress(StudioError):
                    await self.start(script.strategy_id, persist=False)

    async def save(self, strategy_id: str, source: str) -> ScriptRecord:
        validation = validate_source(source)
        status = await self.status(strategy_id)
        if status.state in {"starting", "running", "backoff"}:
            raise StudioError(
                "SCRIPT_RUNNING",
                "실행 중인 전략을 중지한 뒤 코드를 저장하세요.",
                status_code=409,
            )
        await self.router.strategy(strategy_id)
        return await self.store.save_script(
            strategy_id=strategy_id,
            source=source,
            source_hash=validation["source_hash"],
        )

    async def start(self, strategy_id: str, *, persist: bool = True) -> ProcessStatus:
        async with self._lock:
            existing = self._handles.get(strategy_id)
            if existing and existing.status.state in {
                "starting",
                "running",
                "backoff",
            }:
                return existing.status
            strategy = await self.router.strategy(strategy_id)
            try:
                script = await self.store.get_script(strategy_id)
            except KeyError as exc:
                raise StudioError(
                    "SCRIPT_NOT_FOUND",
                    "저장된 전략 스크립트가 없습니다.",
                    status_code=404,
                ) from exc
            validate_source(script.source)
            if persist:
                script = await self.store.set_desired_running(strategy_id, True)
            status = ProcessStatus(
                strategy_id=strategy_id,
                state="starting",
                desired_running=script.desired_running,
            )
            handle = _Handle(status=status)
            self._handles[strategy_id] = handle
            handle.task = asyncio.create_task(self._supervise(handle, strategy, script))
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(handle.ready.wait(), timeout=2)
        return handle.status

    async def stop(
        self, strategy_id: str, *, preserve_desired: bool = False
    ) -> ProcessStatus:
        if not preserve_desired:
            with suppress(KeyError):
                await self.store.set_desired_running(strategy_id, False)
        handle = self._handles.get(strategy_id)
        if handle is None:
            return ProcessStatus(
                strategy_id=strategy_id,
                state="stopped",
                desired_running=preserve_desired,
            )
        handle.stop_requested = True
        process = handle.process
        if process is not None and process.returncode is None:
            with suppress(ProcessLookupError):
                process.terminate()
        if handle.task is not None:
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(asyncio.shield(handle.task), timeout=5)
            if not handle.task.done():
                if process is not None and process.returncode is None:
                    with suppress(ProcessLookupError):
                        process.kill()
                handle.task.cancel()
                with suppress(asyncio.CancelledError):
                    await handle.task
        handle.status.state = "stopped"
        handle.status.desired_running = preserve_desired
        handle.status.stopped_at = self._now()
        handle.status.pid = None
        return handle.status

    async def close(self) -> None:
        self._closing = True
        for strategy_id in list(self._handles):
            await self.stop(strategy_id, preserve_desired=True)

    async def status(self, strategy_id: str) -> ProcessStatus:
        handle = self._handles.get(strategy_id)
        if handle is not None:
            return handle.status
        try:
            desired = (await self.store.get_script(strategy_id)).desired_running
        except KeyError:
            desired = False
        return ProcessStatus(
            strategy_id=strategy_id, state="stopped", desired_running=desired
        )

    async def statuses(self) -> dict[str, ProcessStatus]:
        scripts = await self.store.list_scripts()
        ids = {item.strategy_id for item in scripts} | set(self._handles)
        return {strategy_id: await self.status(strategy_id) for strategy_id in ids}

    def logs(self, strategy_id: str, max_bytes: int = 65_536) -> str:
        path = self._log_path(strategy_id)
        if not path.exists():
            return ""
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes))
            return handle.read().decode("utf-8", errors="replace")

    async def _supervise(
        self, handle: _Handle, strategy: dict[str, Any], script: ScriptRecord
    ) -> None:
        status = handle.status
        while not handle.stop_requested and not self._closing:
            source_path = self._write_source(script)
            self._rotate_log(status.strategy_id)
            env = os.environ.copy()
            env.update(
                {
                    "TRADE_STUDIO_ROUTER_TOKEN": self.router.token,
                    "TRADE_STUDIO_ROUTER_URL": self.router.base_url,
                    "TRADE_STUDIO_STRATEGY_ID": strategy["id"],
                    "TRADE_STUDIO_ACCOUNT": strategy["trading_account"],
                    "TRADE_STUDIO_MARKET_DATA": strategy["market_data"],
                }
            )
            status.state = "starting"
            status.message = None
            try:
                command = (
                    [sys.executable, "--strategy-worker", str(source_path)]
                    if getattr(sys, "frozen", False)
                    else [
                        sys.executable,
                        "-m",
                        "trade_router_studio.worker",
                        str(source_path),
                    ]
                )
                process = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    stdin=asyncio.subprocess.DEVNULL,
                    env=env,
                    cwd=str(self.paths.home),
                    creationflags=(
                        subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                    ),
                )
            except Exception as exc:  # noqa: BLE001 - isolate child startup failures
                status.state = "failed"
                status.message = f"프로세스를 시작하지 못했습니다: {type(exc).__name__}"
                status.stopped_at = self._now()
                handle.ready.set()
                await self.store.set_desired_running(status.strategy_id, False)
                return
            handle.process = process
            status.state = "running"
            status.desired_running = True
            status.pid = process.pid
            status.started_at = self._now()
            status.exit_code = None
            handle.ready.set()
            output = asyncio.create_task(
                self._capture(process.stdout, status.strategy_id, "OUT")
            )
            errors = asyncio.create_task(
                self._capture(process.stderr, status.strategy_id, "ERR")
            )
            exit_code = await process.wait()
            await asyncio.gather(output, errors)
            status.exit_code = exit_code
            status.pid = None
            status.stopped_at = self._now()
            handle.process = None
            if handle.stop_requested or self._closing:
                status.state = "stopped"
                return
            if exit_code == 0:
                status.state = "stopped"
                status.desired_running = False
                await self.store.set_desired_running(status.strategy_id, False)
                return
            status.restart_count += 1
            if status.restart_count >= MAX_RESTARTS:
                status.state = "failed"
                status.desired_running = False
                status.message = "반복 오류로 자동 정지했습니다. 로그를 확인하세요."
                await self.store.set_desired_running(status.strategy_id, False)
                return
            delay = min(2 ** (status.restart_count - 1), 30)
            status.state = "backoff"
            status.message = f"종료 코드 {exit_code}; {delay}초 후 다시 시작합니다."
            await asyncio.sleep(delay)

    async def _capture(
        self,
        stream: asyncio.StreamReader | None,
        strategy_id: str,
        channel: str,
    ) -> None:
        if stream is None:
            return
        path = self._log_path(strategy_id)
        while line := await stream.readline():
            rendered = line.decode("utf-8", errors="replace").rstrip()
            with path.open("a", encoding="utf-8") as handle:
                handle.write(
                    f"{self._now().isoformat(timespec='seconds')} [{channel}] {rendered}\n"
                )

    def _write_source(self, script: ScriptRecord):
        key = hashlib.sha256(script.strategy_id.encode()).hexdigest()[:20]
        path = self.paths.script_dir / f"{key}-{script.source_hash[:12]}.py"
        if not path.exists():
            path.write_text(script.source, encoding="utf-8")
        return path

    def _log_path(self, strategy_id: str):
        key = hashlib.sha256(strategy_id.encode()).hexdigest()[:20]
        return self.paths.strategy_log_dir / f"{key}.log"

    def _rotate_log(self, strategy_id: str) -> None:
        path = self._log_path(strategy_id)
        if path.exists() and path.stat().st_size > 2_000_000:
            with path.open("rb") as handle:
                handle.seek(-1_000_000, os.SEEK_END)
                tail = handle.read()
            path.write_bytes(tail)

    @staticmethod
    def _now():
        from datetime import datetime

        return datetime.now().astimezone()
