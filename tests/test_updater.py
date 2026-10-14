from __future__ import annotations

import zipfile

from trade_router_studio.updater import apply_update


def test_update_replaces_program_directory_and_keeps_backup(tmp_path, monkeypatch):
    target = tmp_path / "TradeRouterStudio"
    target.mkdir()
    (target / "TradeRouterStudio.exe").write_bytes(b"old executable")
    (target / "old.txt").write_text("old", encoding="utf-8")
    archive = tmp_path / "release.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("TradeRouterStudio.exe", b"new executable")
        bundle.writestr("VERSION", "0.2.0")

    launched = []
    monkeypatch.setattr(
        "trade_router_studio.updater.subprocess.Popen",
        lambda *args, **kwargs: launched.append((args, kwargs)),
    )

    apply_update(archive, target, "TradeRouterStudio.exe", [])

    assert (target / "TradeRouterStudio.exe").read_bytes() == b"new executable"
    assert (target / "VERSION").read_text(encoding="utf-8") == "0.2.0"
    assert (tmp_path / "TradeRouterStudio.previous" / "old.txt").is_file()
    assert launched
