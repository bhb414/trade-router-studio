from __future__ import annotations

import argparse
import ctypes
import os
import shutil
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path


def _wait_for_process(pid: int, timeout: float = 60) -> None:
    if os.name != "nt":
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except OSError:
                return
            time.sleep(0.25)
        raise TimeoutError(f"process {pid} did not exit")
    synchronize = 0x00100000
    handle = ctypes.windll.kernel32.OpenProcess(synchronize, False, pid)
    if not handle:
        return
    try:
        result = ctypes.windll.kernel32.WaitForSingleObject(handle, int(timeout * 1000))
        if result == 0x00000102:
            raise TimeoutError(f"process {pid} did not exit")
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def _payload_root(extracted: Path, launcher: str) -> Path:
    if (extracted / launcher).is_file():
        return extracted
    candidates = [item for item in extracted.iterdir() if item.is_dir()]
    if len(candidates) == 1 and (candidates[0] / launcher).is_file():
        return candidates[0]
    raise RuntimeError("업데이트 ZIP에서 실행 파일을 찾을 수 없습니다.")


def apply_update(archive: Path, target: Path, launcher: str, wait_pids: list[int]) -> None:
    for pid in wait_pids:
        _wait_for_process(pid)
    target = target.resolve()
    parent = target.parent
    backup = parent / f"{target.name}.previous"
    staging = parent / f".{target.name}.update"
    with tempfile.TemporaryDirectory(prefix="trade-router-update-") as temporary:
        extracted = Path(temporary)
        with zipfile.ZipFile(archive) as bundle:
            for item in bundle.infolist():
                destination = (extracted / item.filename).resolve()
                if extracted.resolve() not in destination.parents and destination != extracted.resolve():
                    raise RuntimeError("업데이트 ZIP에 잘못된 경로가 있습니다.")
            bundle.extractall(extracted)
        source = _payload_root(extracted, launcher)
        shutil.rmtree(staging, ignore_errors=True)
        shutil.copytree(source, staging)
        if not (staging / launcher).is_file():
            raise RuntimeError("새 실행 파일을 준비하지 못했습니다.")
        shutil.rmtree(backup, ignore_errors=True)
        os.replace(target, backup)
        try:
            os.replace(staging, target)
        except Exception:
            os.replace(backup, target)
            raise
    flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS if os.name == "nt" else 0
    subprocess.Popen(
        [str(target / launcher)],
        cwd=str(target),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
        close_fds=True,
    )


def _message(text: str, title: str) -> None:
    if os.name == "nt":
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x10)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--launch", required=True)
    parser.add_argument("--wait-pid", type=int, action="append", default=[])
    args = parser.parse_args()
    try:
        apply_update(args.archive, args.target, args.launch, args.wait_pid)
    except Exception as exc:
        _message(f"업데이트를 적용하지 못했습니다.\n\n{type(exc).__name__}: {exc}", "Trade Router Studio")
        raise


if __name__ == "__main__":
    main()
