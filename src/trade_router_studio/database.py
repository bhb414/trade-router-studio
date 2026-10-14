from __future__ import annotations

from datetime import datetime
from pathlib import Path

import aiosqlite

from .models import ScriptRecord

_SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS scripts (
    strategy_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    desired_running INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
PRAGMA user_version=1;
"""


class StudioStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._db: aiosqlite.Connection | None = None

    async def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(_SCHEMA)
        await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("studio database is not open")
        return self._db

    async def save_script(
        self, *, strategy_id: str, source: str, source_hash: str
    ) -> ScriptRecord:
        now = datetime.now().astimezone().isoformat()
        await self.db.execute(
            "INSERT INTO scripts(strategy_id,source,source_hash,desired_running,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?) ON CONFLICT(strategy_id) DO UPDATE SET "
            "source=excluded.source,source_hash=excluded.source_hash,updated_at=excluded.updated_at",
            (strategy_id, source, source_hash, 0, now, now),
        )
        await self.db.commit()
        return await self.get_script(strategy_id)

    async def get_script(self, strategy_id: str) -> ScriptRecord:
        row = await (
            await self.db.execute(
                "SELECT * FROM scripts WHERE strategy_id=?", (strategy_id,)
            )
        ).fetchone()
        if row is None:
            raise KeyError(strategy_id)
        return self._record(row)

    async def list_scripts(self) -> list[ScriptRecord]:
        rows = await (
            await self.db.execute("SELECT * FROM scripts ORDER BY strategy_id")
        ).fetchall()
        return [self._record(row) for row in rows]

    async def set_desired_running(
        self, strategy_id: str, desired: bool
    ) -> ScriptRecord:
        cursor = await self.db.execute(
            "UPDATE scripts SET desired_running=?,updated_at=? WHERE strategy_id=?",
            (int(desired), datetime.now().astimezone().isoformat(), strategy_id),
        )
        await self.db.commit()
        if cursor.rowcount == 0:
            raise KeyError(strategy_id)
        return await self.get_script(strategy_id)

    @staticmethod
    def _record(row: aiosqlite.Row) -> ScriptRecord:
        return ScriptRecord(
            strategy_id=row["strategy_id"],
            source=row["source"],
            source_hash=row["source_hash"],
            desired_running=bool(row["desired_running"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
