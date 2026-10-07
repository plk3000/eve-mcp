"""Non-secret local idempotency ledger for fitting creation attempts."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class CreationLedger:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS fitting_creations(
                    character_id TEXT NOT NULL,
                    proposal_id TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('creating', 'created', 'unknown')),
                    fitting_id INTEGER,
                    attempted_at TEXT NOT NULL,
                    verified_at TEXT,
                    PRIMARY KEY(character_id, proposal_id)
                )"""
            )

    def get(self, character_id: str, proposal_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT state, fitting_id, attempted_at, verified_at
                   FROM fitting_creations WHERE character_id=? AND proposal_id=?""",
                (character_id, proposal_id),
            ).fetchone()
        if row is None:
            return None
        return {
            "state": row[0],
            "fitting_id": row[1],
            "attempted_at": row[2],
            "verified_at": row[3],
        }

    def begin(self, character_id: str, proposal_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """INSERT INTO fitting_creations(character_id, proposal_id, state, attempted_at)
                   VALUES(?, ?, 'creating', ?)
                   ON CONFLICT(character_id, proposal_id) DO NOTHING""",
                (character_id, proposal_id, datetime.now(UTC).isoformat()),
            )
            return cursor.rowcount == 1

    def mark_unknown(self, character_id: str, proposal_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """UPDATE fitting_creations SET state='unknown'
                   WHERE character_id=? AND proposal_id=?""",
                (character_id, proposal_id),
            )

    def mark_created(self, character_id: str, proposal_id: str, fitting_id: int) -> None:
        with self._connect() as connection:
            connection.execute(
                """UPDATE fitting_creations SET state='created', fitting_id=?, verified_at=?
                   WHERE character_id=? AND proposal_id=?""",
                (fitting_id, datetime.now(UTC).isoformat(), character_id, proposal_id),
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)
