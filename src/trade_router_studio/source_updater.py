from __future__ import annotations

import argparse
import ctypes
import os
import subprocess
import time
from pathlib import Path


def _wait_for_process(pid: int, timeout: float = 90) -> None:
    if os.name != "nt":
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except OSError:
                return
            time.sleep(0.25)
        raise TimeoutError(f"process {pid} did not exit")
    handle = ctypes.windll.kernel32.OpenProcess(0x00100000, False, pid)
    if not handle:
        return
    try:
        result = ctypes.windll.kernel32.WaitForSingleObject(handle, int(timeout * 1000))
        if result == 0x00000102:
            raise TimeoutError(f"process {pid} did not exit")
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def _run(command: list[str], *, cwd: Path, log) -> None:
    result = subprocess.run(
        command,
        cwd=str(cwd),
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(command)}")


def apply_source_update(
    project_root: Path,
    version: str,
    marker: Path,
    wait_pids: list[int],
    log_path: Path,
    python: Path,
) -> None:
    for pid in wait_pids:
        _wait_for_process(pid)
    project_root = project_root.resolve()
    python = python.resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"\nUpdating source to v{version}\n")
        _run(["git", "merge", "--ff-only", f"v{version}"], cwd=project_root, log=log)
        router_root = project_root.parent / "trade-router"
        if (router_root / "pyproject.toml").is_file():
            _run(
                [
                    str(python),
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    "-e",
                    str(router_root),
                ],
                cwd=project_root,
                log=log,
            )
        _run(
            [str(python), "-m", "pip", "install", "--disable-pip-version-check", "-e", str(project_root)],
            cwd=project_root,
            log=log,
        )
        marker.unlink(missing_ok=True)
        log.write("Source update complete; restarting.\n")
    flags = (
        subprocess.CREATE_NEW_CONSOLE
        | subprocess.DETACHED_PROCESS
        | subprocess.CREATE_BREAKAWAY_FROM_JOB
        if os.name == "nt"
        else 0
    )
    subprocess.Popen(
        [str(python), "-m", "trade_router_studio.desktop"],
        cwd=str(project_root),
        stdin=subprocess.DEVNULL,
        creationflags=flags,
        close_fds=True,
    )


def _message(text: str) -> None:
    if os.name == "nt":
        ctypes.windll.user32.MessageBoxW(None, text, "Trade Router Studio", 0x10)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--marker", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--wait-pid", type=int, action="append", default=[])
    args = parser.parse_args()
    try:
        apply_source_update(
            args.project_root,
            args.version,
            args.marker,
            args.wait_pid,
            args.log,
            args.python,
        )
    except Exception as exc:
        _message(f"업데이트를 적용하지 못했습니다.\n\n{type(exc).__name__}: {exc}")
        raise


if __name__ == "__main__":
    main()
