"""Non-secret multi-character profile persistence."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


class ProfileError(ValueError):
    """A safe profile selection failure."""


class AmbiguousProfileError(ProfileError):
    """More than one profile uses the exact display name."""


class DisabledProfileError(ProfileError):
    """The selected profile is disabled."""


class UnknownProfileError(ProfileError):
    """No selected profile exists."""


@dataclass(frozen=True)
class Profile:
    character_id: str
    character_name: str
    granted_scopes: tuple[str, ...]
    token_expires_at: datetime | None
    enabled: bool
    last_authorization_status: str
    authorized_at: datetime | None = None
    last_successful_fetch_at: datetime | None = None


class ProfileRepository:
    """SQLite repository deliberately limited to safe metadata."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS profiles (
                character_id TEXT PRIMARY KEY, character_name TEXT NOT NULL,
                authorized_at TEXT, granted_scopes TEXT NOT NULL, token_expires_at TEXT,
                enabled INTEGER NOT NULL, last_successful_fetch_at TEXT,
                last_authorization_status TEXT NOT NULL)"""
            )

    def upsert(
        self,
        character_id: str,
        character_name: str,
        scopes: list[str],
        expires_at: datetime | None,
        status: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO profiles(character_id, character_name, authorized_at, granted_scopes,
                token_expires_at, enabled, last_authorization_status) VALUES(?, ?, ?, ?, ?, 1, ?)
                ON CONFLICT(character_id) DO UPDATE SET character_name=excluded.character_name,
                authorized_at=excluded.authorized_at, granted_scopes=excluded.granted_scopes,
                token_expires_at=excluded.token_expires_at, enabled=1,
                last_authorization_status=excluded.last_authorization_status""",
                (
                    character_id,
                    character_name,
                    datetime.now().isoformat(),
                    json.dumps(scopes),
                    expires_at.isoformat() if expires_at else None,
                    status,
                ),
            )

    def resolve(self, selector: str) -> Profile:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM profiles WHERE character_id = ? OR character_name = ?",
                (selector, selector),
            ).fetchall()
        if not rows:
            raise UnknownProfileError("No authorized character matches the supplied selector.")
        if len(rows) > 1:
            raise AmbiguousProfileError(
                "Character name is ambiguous; use its numeric character ID."
            )
        row = rows[0]
        profile = Profile(
            row[0],
            row[1],
            tuple(json.loads(row[3])),
            self._parse(row[4]),
            bool(row[5]),
            row[7],
            self._parse(row[2]),
            self._parse(row[6]),
        )
        if not profile.enabled:
            raise DisabledProfileError(
                "Selected character is disabled; enable it before requesting data."
            )
        return profile

    def list(self) -> list[Profile]:
        with self._connect() as conn:
            ids = [
                row[0]
                for row in conn.execute("SELECT character_id FROM profiles ORDER BY character_name")
            ]
        return [self.resolve_including_disabled(identifier) for identifier in ids]

    def resolve_including_disabled(self, selector: str) -> Profile:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM profiles WHERE character_id = ? OR character_name = ?",
                (selector, selector),
            ).fetchall()
        if not rows:
            raise UnknownProfileError("No authorized character matches the supplied selector.")
        if len(rows) > 1:
            raise AmbiguousProfileError(
                "Character name is ambiguous; use its numeric character ID."
            )
        row = rows[0]
        return Profile(
            row[0],
            row[1],
            tuple(json.loads(row[3])),
            self._parse(row[4]),
            bool(row[5]),
            row[7],
            self._parse(row[2]),
            self._parse(row[6]),
        )

    def set_enabled(self, selector: str, enabled: bool) -> None:
        profile = self.resolve_including_disabled(selector)
        with self._connect() as conn:
            conn.execute(
                "UPDATE profiles SET enabled = ? WHERE character_id = ?",
                (enabled, profile.character_id),
            )

    def delete(self, selector: str) -> None:
        """Delete only the resolved local metadata record after explicit CLI confirmation."""
        profile = self.resolve_including_disabled(selector)
        with self._connect() as conn:
            conn.execute("DELETE FROM profiles WHERE character_id = ?", (profile.character_id,))

    def schema_columns(self) -> set[str]:
        with self._connect() as conn:
            return {row[1] for row in conn.execute("PRAGMA table_info(profiles)")}

    @staticmethod
    def _parse(value: str | None) -> datetime | None:
        return datetime.fromisoformat(value) if value else None
