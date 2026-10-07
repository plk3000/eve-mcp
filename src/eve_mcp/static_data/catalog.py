"""Narrow SQLite-backed view of fitting-relevant static type facts."""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path

Kind = str


@dataclass(frozen=True)
class StaticType:
    type_id: int
    name: str
    kind: str
    group: str
    category: str
    slot_class: str | None
    cpu: float
    powergrid: float
    calibration: float
    slots: dict[str, int]
    required_skills: dict[int, int]

    def __post_init__(self) -> None:
        if type(self.type_id) is not int or self.type_id < 1:
            raise ValueError("catalog type_id must be a positive integer")
        if not all(
            isinstance(value, str) and value.strip()
            for value in (self.name, self.group, self.category)
        ):
            raise ValueError("catalog type names and classification fields must be nonempty")
        if self.kind not in {"hull", "module", "charge", "drone", "rig"}:
            raise ValueError("catalog kind is unsupported")
        if self.slot_class not in {None, "high", "medium", "low", "rig", "service"}:
            raise ValueError("catalog slot_class is unsupported")
        for value in (self.cpu, self.powergrid, self.calibration):
            if type(value) not in {int, float} or not math.isfinite(value) or value < 0:
                raise ValueError("catalog resource facts must be finite and nonnegative")
        if any(
            not isinstance(slot, str) or type(count) is not int or count < 0
            for slot, count in self.slots.items()
        ):
            raise ValueError("catalog slot counts must be nonnegative integers")
        if any(
            type(skill_id) is not int or type(level) is not int or skill_id < 1 or level < 1
            for skill_id, level in self.required_skills.items()
        ):
            raise ValueError("catalog required skill facts are invalid")


class StaticCatalog:
    """Read-only fitting facts stored in a versioned local SQLite file."""

    def __init__(self, path: Path) -> None:
        self.path = path
        if not path.is_file():
            raise FileNotFoundError("Static catalog is not installed.")
        with sqlite3.connect(path) as connection:
            row = connection.execute("SELECT value FROM metadata WHERE key='version'").fetchone()
        if row is None:
            raise ValueError("Static catalog has no version metadata.")
        self.version = str(row[0])

    @classmethod
    def create(cls, path: Path, version: str, records: list[StaticType]) -> StaticCatalog:
        if not version:
            raise ValueError("catalog version is required")
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as connection:
            connection.executescript(
                """CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE types(
                    type_id INTEGER PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,
                    group_name TEXT NOT NULL, category TEXT NOT NULL, slot_class TEXT,
                    cpu REAL NOT NULL, powergrid REAL NOT NULL, calibration REAL NOT NULL,
                    slots TEXT NOT NULL, required_skills TEXT NOT NULL
                );
                CREATE INDEX types_name ON types(name COLLATE NOCASE);"""
            )
            connection.execute("INSERT INTO metadata VALUES('version', ?)", (version,))
            connection.executemany(
                """INSERT INTO types VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        item.type_id,
                        item.name,
                        item.kind,
                        item.group,
                        item.category,
                        item.slot_class,
                        item.cpu,
                        item.powergrid,
                        item.calibration,
                        json.dumps(item.slots, sort_keys=True),
                        json.dumps(item.required_skills, sort_keys=True),
                    )
                    for item in records
                ],
            )
            connection.commit()
        return cls(path)

    def get_type(self, type_id: int) -> StaticType | None:
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                """SELECT type_id, name, kind, group_name, category, slot_class, cpu,
                          powergrid, calibration, slots, required_skills
                   FROM types WHERE type_id=?""",
                (type_id,),
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def search(self, query: str, kind: Kind | None, limit: int) -> list[StaticType]:
        if not query.strip() or len(query.strip()) < 2:
            raise ValueError("query must contain at least two non-whitespace characters")
        bounded = min(max(limit, 1), 50)
        pattern = f"%{query.strip()}%"
        with sqlite3.connect(self.path) as connection:
            if kind is None:
                rows = connection.execute(
                    """SELECT type_id, name, kind, group_name, category, slot_class, cpu,
                              powergrid, calibration, slots, required_skills FROM types
                       WHERE name LIKE ? COLLATE NOCASE ORDER BY name COLLATE NOCASE LIMIT ?""",
                    (pattern, bounded),
                ).fetchall()
            else:
                rows = connection.execute(
                    """SELECT type_id, name, kind, group_name, category, slot_class, cpu,
                              powergrid, calibration, slots, required_skills FROM types
                       WHERE name LIKE ? COLLATE NOCASE AND kind=? ORDER BY name COLLATE NOCASE
                       LIMIT ?""",
                    (pattern, kind, bounded),
                ).fetchall()
        return [self._from_row(row) for row in rows]

    @staticmethod
    def _from_row(row: tuple[object, ...]) -> StaticType:
        type_id = row[0]
        name = row[1]
        kind = row[2]
        group = row[3]
        category = row[4]
        slot_class = row[5]
        if (
            type(type_id) is not int
            or not isinstance(name, str)
            or not isinstance(kind, str)
            or not isinstance(group, str)
            or not isinstance(category, str)
            or slot_class is not None
            and not isinstance(slot_class, str)
        ):
            raise ValueError("Static catalog row has invalid type metadata.")
        encoded_slots = json.loads(str(row[9]))
        encoded_skills = json.loads(str(row[10]))
        if not isinstance(encoded_slots, dict) or not isinstance(encoded_skills, dict):
            raise ValueError("Static catalog row has invalid fitting facts.")
        if any(
            not isinstance(key, str) or type(value) is not int
            for key, value in encoded_slots.items()
        ):
            raise ValueError("Static catalog row has invalid slot facts.")
        if any(
            not isinstance(key, str) or type(value) is not int
            for key, value in encoded_skills.items()
        ):
            raise ValueError("Static catalog row has invalid skill facts.")
        return StaticType(
            type_id=type_id,
            name=name,
            kind=kind,
            group=group,
            category=category,
            slot_class=slot_class,
            cpu=StaticCatalog._number(row[6], "cpu"),
            powergrid=StaticCatalog._number(row[7], "powergrid"),
            calibration=StaticCatalog._number(row[8], "calibration"),
            slots={key: value for key, value in encoded_slots.items()},
            required_skills={int(key): value for key, value in encoded_skills.items()},
        )

    @staticmethod
    def _number(value: object, label: str) -> float:
        if not isinstance(value, (int, float)):
            raise ValueError(f"Static catalog row has invalid {label}.")
        return float(value)
