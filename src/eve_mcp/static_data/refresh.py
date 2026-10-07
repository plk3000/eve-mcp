"""Explicit official SDE refresh and isolated local catalog lifecycle."""

from __future__ import annotations

import fcntl
import hashlib
import io
import json
import math
import os
import shutil
import sqlite3
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile, is_zipfile

import httpx

from eve_mcp.static_data.catalog import StaticCatalog, StaticType
from eve_mcp.static_data.manifest import LATEST_URL, BuildManifest, is_valid_build_id

_REQUIRED_DATASETS = (
    "_sde.jsonl",
    "types.jsonl",
    "typeDogma.jsonl",
    "dogmaAttributes.jsonl",
    "dogmaEffects.jsonl",
    "groups.jsonl",
    "categories.jsonl",
)
_ATTRIBUTE_NAMES = (
    "powerOutput",
    "lowSlots",
    "medSlots",
    "hiSlots",
    "rigSlots",
    "serviceSlots",
    "cpuOutput",
    "upgradeCapacity",
    "cpu",
    "power",
    "upgradeCost",
    "requiredSkill1",
    "requiredSkill2",
    "requiredSkill3",
    "requiredSkill4",
    "requiredSkill5",
    "requiredSkill6",
    "requiredSkill1Level",
    "requiredSkill2Level",
    "requiredSkill3Level",
    "requiredSkill4Level",
    "requiredSkill5Level",
    "requiredSkill6Level",
)
_SLOT_EFFECTS = {
    "hiPower": "high",
    "medPower": "medium",
    "loPower": "low",
    "rigSlot": "rig",
    "serviceSlot": "service",
}
_SLOT_ATTRIBUTES = {
    "high": "hiSlots",
    "medium": "medSlots",
    "low": "lowSlots",
    "rig": "rigSlots",
    "service": "serviceSlots",
}


class StaticDataSourceUnavailable(RuntimeError):
    """The official SDE service did not return a usable response."""


class StaticDataManager:
    def __init__(
        self,
        data_dir: Path,
        *,
        http_transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.data_dir = data_dir
        self.root = data_dir / "static-data"
        default_data_dir = Path.home() / ".local" / "share" / "eve-mcp"
        self.cache_root = (
            Path.home() / ".cache" / "eve-mcp" / "sde"
            if data_dir == default_data_dir
            else data_dir / "sde-cache"
        )
        self.catalog_root = self.root
        self.current_path = self.root / "current.json"
        self.lock_path = data_dir / ".static-data.lock"
        self.http_transport = http_transport

    def status(self) -> dict[str, Any]:
        current = self._current()
        builds = (
            sorted(
                path.name
                for path in self.catalog_root.iterdir()
                if path.is_dir()
                and not path.name.startswith(".")
                and (path / "catalog.sqlite3").is_file()
            )
            if self.catalog_root.exists()
            else []
        )
        return {
            "active_build": current.get("build_id") if current else None,
            "installed_builds": builds,
            "catalog_schema_version": 1 if builds else None,
            "disk_bytes": self._bytes(self.root) + self._bytes(self.cache_root),
            "provenance": current.get("manifest") if current else None,
            "newer_build_check": "not_checked_offline",
        }

    def refresh_official(self, *, force: bool = False) -> dict[str, Any]:
        with self._exclusive_lock():
            with httpx.Client(
                transport=self.http_transport,
                timeout=httpx.Timeout(60.0),
                follow_redirects=False,
                headers={"User-Agent": "eve-mcp/0.1 (official SDE refresh)"},
            ) as client:
                latest_response = client.get(LATEST_URL)
                if latest_response.status_code != 200:
                    raise StaticDataSourceUnavailable(
                        f"CCP latest.jsonl returned HTTP {latest_response.status_code}."
                    )
                manifest = BuildManifest.parse_latest_jsonl(latest_response.content)
                current = self._current()
                build_path = self.catalog_root / manifest.build_id / "catalog.sqlite3"
                if (
                    current
                    and current.get("build_id") == manifest.build_id
                    and build_path.is_file()
                    and not force
                ):
                    return {"active_build": manifest.build_id, "unchanged": True}

                archive_response = client.get(manifest.archive_url)
                if archive_response.status_code != 200:
                    raise StaticDataSourceUnavailable(
                        f"CCP SDE archive returned HTTP {archive_response.status_code}."
                    )
                return self._refresh_locked(manifest, archive_response.content, force)

    def _refresh_locked(
        self,
        manifest: BuildManifest,
        archive_bytes: bytes,
        force: bool,
    ) -> dict[str, Any]:
        self.catalog_root.mkdir(parents=True, exist_ok=True)
        self.cache_root.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=".stage-", dir=self.root))
        cache_stage = Path(tempfile.mkdtemp(prefix=".stage-", dir=self.cache_root))
        build_path = self.catalog_root / manifest.build_id
        cache_path = self.cache_root / manifest.build_id
        backup_build: Path | None = None
        backup_cache: Path | None = None
        promoted_build = False
        promoted_cache = False
        pointer_promoted = False
        try:
            records = self._read_archive(archive_bytes, manifest.build_id, manifest.release_date)
            database_path = stage / "catalog.sqlite3"
            StaticCatalog.create(database_path, manifest.build_id, records)
            with sqlite3.connect(database_path) as connection:
                if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                    raise ValueError("imported catalog failed integrity check")

            archive_name = f"eve-online-static-data-{manifest.build_id}-jsonl.zip"
            raw_path = cache_stage / "raw"
            raw_path.mkdir()
            (raw_path / archive_name).write_bytes(archive_bytes)
            archive_sha256 = hashlib.sha256(archive_bytes).hexdigest()
            provenance = {
                "source": "CCP Tranquility Static Data Export",
                "source_url": manifest.marker_url,
                "build_id": manifest.build_id,
                "release_date": manifest.release_date,
                "archive": {
                    "name": archive_name,
                    "url": manifest.archive_url,
                    "downloaded_bytes": len(archive_bytes),
                    "sha256": archive_sha256,
                },
                "imported_type_count": len(records),
                "imported_at": datetime.now(UTC).isoformat(),
                "catalog_schema_version": 1,
            }
            (stage / "manifest.json").write_text(
                json.dumps(provenance, sort_keys=True, indent=2) + "\n", encoding="utf-8"
            )
            if build_path.exists() or cache_path.exists():
                if not force:
                    raise FileExistsError("build already exists; use force to replace it")
                suffix = uuid.uuid4().hex
                if build_path.exists():
                    backup_build = self.catalog_root / f".{manifest.build_id}-{suffix}.old"
                    os.replace(build_path, backup_build)
                if cache_path.exists():
                    backup_cache = self.cache_root / f".{manifest.build_id}-{suffix}.old"
                    os.replace(cache_path, backup_cache)
            staged_catalog = stage / "promoted"
            staged_catalog.mkdir()
            os.replace(database_path, staged_catalog / "catalog.sqlite3")
            os.replace(stage / "manifest.json", staged_catalog / "manifest.json")
            os.replace(staged_catalog, build_path)
            promoted_build = True
            os.replace(cache_stage, cache_path)
            promoted_cache = True
            pointer_tmp = self.root / ".current.tmp"
            pointer_tmp.write_text(
                json.dumps({"build_id": manifest.build_id, "manifest": provenance}, sort_keys=True)
                + "\n",
                encoding="utf-8",
            )
            os.replace(pointer_tmp, self.current_path)
            pointer_promoted = True
            if backup_build:
                shutil.rmtree(backup_build)
            if backup_cache:
                shutil.rmtree(backup_cache)
            return {"active_build": manifest.build_id, "unchanged": False}
        except Exception:
            if not pointer_promoted:
                if promoted_build and build_path.exists():
                    shutil.rmtree(build_path)
                if promoted_cache and cache_path.exists():
                    shutil.rmtree(cache_path)
                if backup_build and backup_build.exists():
                    os.replace(backup_build, build_path)
                if backup_cache and backup_cache.exists():
                    os.replace(backup_cache, cache_path)
            raise
        finally:
            if stage.exists():
                shutil.rmtree(stage)
            if cache_stage.exists():
                shutil.rmtree(cache_stage)

    def clear_build(self, build_id: str, *, yes: bool) -> dict[str, Any]:
        if not yes:
            raise ValueError("clearing a build requires --yes")
        if not is_valid_build_id(build_id):
            raise ValueError("build ID is invalid")
        with self._exclusive_lock():
            current = self._current()
            was_active = bool(current and current.get("build_id") == build_id)
            paths = (self.catalog_root / build_id, self.cache_root / build_id)
            removed = sum(self._bytes(path) for path in paths)
            for path in paths:
                if path.is_dir():
                    shutil.rmtree(path)
            if was_active and self.current_path.is_file():
                self.current_path.unlink()
            return {
                "removed_bytes": removed,
                "paths": [str(path) for path in paths],
                "warning": "fitting drafting/saving is unavailable until refresh"
                if was_active
                else None,
            }

    def clear_all(self, *, yes: bool) -> dict[str, Any]:
        if not yes:
            raise ValueError("clearing all static data requires --yes")
        with self._exclusive_lock():
            paths = (self.root, self.cache_root)
            removed = sum(self._bytes(path) for path in paths)
            result = {"removed_bytes": removed, "paths": [str(path) for path in paths]}
            for path in paths:
                if path.exists():
                    shutil.rmtree(path)
            return result

    def catalog(self, build_id: str | None = None) -> StaticCatalog:
        current = self._current()
        selected_build = build_id or (current.get("build_id") if current else None)
        if not selected_build:
            raise FileNotFoundError("No static catalog; run eve-mcp static-data refresh.")
        if not isinstance(selected_build, str) or not is_valid_build_id(selected_build):
            raise ValueError("Static catalog build ID is invalid.")
        return StaticCatalog(self.catalog_root / selected_build / "catalog.sqlite3")

    def _current(self) -> dict[str, Any] | None:
        if not self.current_path.is_file():
            return None
        value = json.loads(self.current_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("Static catalog pointer is invalid.")
        return value

    @contextmanager
    def _exclusive_lock(self) -> Iterator[None]:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+b") as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RuntimeError("Another static-data lifecycle operation is running.") from error
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    @classmethod
    def _read_archive(
        cls,
        content: bytes,
        expected_build_id: str,
        expected_release_date: str | None = None,
    ) -> list[StaticType]:
        if not is_zipfile(io.BytesIO(content)):
            raise ValueError("official SDE archive is not a ZIP file")
        try:
            with ZipFile(io.BytesIO(content)) as archive:
                names = archive.namelist()
                if any(names.count(name) != 1 for name in _REQUIRED_DATASETS):
                    raise ValueError("official SDE archive is missing a required JSONL dataset")
                datasets = {
                    name: cls._read_jsonl(archive, name)
                    for name in _REQUIRED_DATASETS
                    if name not in {"types.jsonl", "typeDogma.jsonl"}
                }
                return cls._types_from_datasets(
                    archive, datasets, expected_build_id, expected_release_date
                )
        except (BadZipFile, OSError, RuntimeError) as error:
            raise ValueError("official SDE archive could not be read") from error

    @staticmethod
    def _iter_jsonl(archive: ZipFile, filename: str) -> Iterator[dict[str, Any]]:
        try:
            with archive.open(filename) as stream:
                for _line_number, encoded in enumerate(stream, start=1):
                    if not encoded.strip():
                        continue
                    value = json.loads(encoded.decode("utf-8"))
                    if not isinstance(value, dict):
                        raise ValueError
                    yield value
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, ValueError) as error:
            raise ValueError(f"official SDE dataset {filename} is malformed.") from error

    @classmethod
    def _read_jsonl(cls, archive: ZipFile, filename: str) -> list[dict[str, Any]]:
        return list(cls._iter_jsonl(archive, filename))

    @classmethod
    def _types_from_datasets(
        cls,
        archive: ZipFile,
        datasets: dict[str, list[dict[str, Any]]],
        expected_build_id: str,
        expected_release_date: str | None,
    ) -> list[StaticType]:
        metadata = [record for record in datasets["_sde.jsonl"] if record.get("_key") == "sde"]
        if (
            len(metadata) != 1
            or str(metadata[0].get("buildNumber")) != expected_build_id
            or not isinstance(metadata[0].get("releaseDate"), str)
            or expected_release_date is not None
            and metadata[0].get("releaseDate") != expected_release_date
        ):
            raise ValueError("SDE archive build metadata does not match latest.jsonl.")

        categories = cls._indexed_records(datasets["categories.jsonl"], "category")
        groups = cls._indexed_records(datasets["groups.jsonl"], "group")
        attributes = cls._indexed_records(datasets["dogmaAttributes.jsonl"], "dogma attribute")
        effects = cls._indexed_records(datasets["dogmaEffects.jsonl"], "dogma effect")
        attribute_names: dict[int, str] = {}
        defaults: dict[str, float] = {}
        for attribute_id, record in attributes.items():
            name = record.get("name")
            if isinstance(name, str):
                attribute_names[attribute_id] = name
                defaults[name] = cls._number(record.get("defaultValue", 0), f"default {name}")
        missing_attributes = set(_ATTRIBUTE_NAMES) - defaults.keys()
        if missing_attributes:
            raise ValueError(
                "official SDE is missing fitting dogma attributes: "
                + ", ".join(sorted(missing_attributes))
            )
        effect_names: dict[int, str] = {}
        for effect_id, record in effects.items():
            effect_name = record.get("name")
            if isinstance(effect_name, str):
                effect_names[effect_id] = effect_name

        candidates: dict[int, tuple[str, str, str]] = {}
        for record in cls._iter_jsonl(archive, "types.jsonl"):
            type_id = record.get("_key")
            group_id = record.get("groupID")
            if type(record.get("published")) is not bool:
                raise ValueError("official SDE type record has invalid published metadata")
            if not record["published"]:
                continue
            if type(type_id) is not int or type_id < 1 or type(group_id) is not int:
                raise ValueError("official SDE type record has invalid IDs")
            group = groups.get(group_id)
            if group is None:
                raise ValueError(f"official SDE type {type_id} references an unknown group")
            category_id = group.get("categoryID")
            category = categories.get(category_id) if type(category_id) is int else None
            category_name = cls._english_name(category, "category") if category else ""
            if category_name not in {"Ship", "Module", "Charge", "Drone"}:
                continue
            group_name = cls._english_name(group, "group")
            type_name = cls._english_name(record, "type")
            candidates[type_id] = (category_name, group_name, type_name)

        result: list[StaticType] = []
        processed_dogma_ids: set[int] = set()
        for dogma in cls._iter_jsonl(archive, "typeDogma.jsonl"):
            dogma_type_id = dogma.get("_key")
            if (
                type(dogma_type_id) is not int
                or dogma_type_id < 0
                or dogma_type_id in processed_dogma_ids
            ):
                raise ValueError("official SDE type dogma records have invalid or duplicate IDs")
            processed_dogma_ids.add(dogma_type_id)
            if dogma_type_id not in candidates:
                continue
            category_name, group_name, type_name = candidates[dogma_type_id]
            values = dict(defaults)
            for entry in dogma.get("dogmaAttributes", []):
                if not isinstance(entry, dict):
                    raise ValueError(f"official SDE type dogma for {dogma_type_id} is malformed")
                dogma_attribute_id, value = entry.get("attributeID"), entry.get("value")
                if type(dogma_attribute_id) is not int:
                    raise ValueError(
                        f"official SDE type dogma for {dogma_type_id} has an invalid ID"
                    )
                name = attribute_names.get(dogma_attribute_id)
                if name is not None:
                    values[name] = cls._number(value, f"type {dogma_type_id} {name}")
            slot_class = cls._slot_class(dogma, effect_names, dogma_type_id)
            if category_name == "Ship":
                kind = "hull"
            elif category_name == "Charge":
                kind = "charge"
            elif category_name == "Drone":
                kind = "drone"
            elif slot_class is None:
                continue
            else:
                kind = "rig" if slot_class == "rig" else "module"

            required_skills: dict[int, int] = {}
            for index in range(1, 7):
                skill = values[f"requiredSkill{index}"]
                if skill <= 0:
                    continue
                level = values[f"requiredSkill{index}Level"]
                skill_id = cls._integer(skill, f"type {dogma_type_id} required skill")
                skill_level = cls._integer(level, f"type {dogma_type_id} skill level")
                if skill_level == 0:
                    continue
                if skill_level > 5:
                    raise ValueError(
                        f"official SDE type {dogma_type_id} required skill {skill_id} "
                        f"has invalid level {skill_level}"
                    )
                required_skills[skill_id] = skill_level

            slots = (
                {
                    name: cls._integer(values[attribute], f"type {dogma_type_id} {attribute}")
                    for name, attribute in _SLOT_ATTRIBUTES.items()
                }
                if kind == "hull"
                else {}
            )
            result.append(
                StaticType(
                    type_id=dogma_type_id,
                    name=type_name,
                    kind=kind,
                    group=group_name,
                    category=category_name,
                    slot_class=slot_class,
                    cpu=values["cpuOutput"] if kind == "hull" else values["cpu"],
                    powergrid=values["powerOutput"] if kind == "hull" else values["power"],
                    calibration=(
                        values["upgradeCapacity"]
                        if kind == "hull"
                        else values["upgradeCost"]
                        if kind == "rig"
                        else 0
                    ),
                    slots=slots,
                    required_skills=required_skills,
                )
            )
            del candidates[dogma_type_id]
        if not result:
            raise ValueError("official SDE contains no fitting-relevant types")
        return result

    @staticmethod
    def _indexed_records(records: list[dict[str, Any]], label: str) -> dict[int, dict[str, Any]]:
        indexed: dict[int, dict[str, Any]] = {}
        for record in records:
            record_id = record.get("_key")
            if type(record_id) is not int or record_id < 0 or record_id in indexed:
                raise ValueError(f"official SDE {label} records have invalid or duplicate IDs")
            indexed[record_id] = record
        return indexed

    @staticmethod
    def _english_name(record: dict[str, Any], label: str) -> str:
        names = record.get("name")
        name = names.get("en") if isinstance(names, dict) else None
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"official SDE {label} record has no English name")
        return name

    @staticmethod
    def _slot_class(
        dogma: dict[str, Any], effect_names: dict[int, str], type_id: int
    ) -> str | None:
        classes: set[str] = set()
        for effect in dogma.get("dogmaEffects", []):
            if not isinstance(effect, dict):
                raise ValueError(f"official SDE type dogma for {type_id} is malformed")
            effect_id = effect.get("effectID")
            if type(effect_id) is not int:
                raise ValueError(f"official SDE type dogma for {type_id} has an invalid effect ID")
            effect_name = effect_names.get(effect_id)
            slot_class = _SLOT_EFFECTS.get(effect_name) if effect_name else None
            if slot_class:
                classes.add(slot_class)
        if len(classes) > 1:
            raise ValueError(f"official SDE type {type_id} has conflicting slot effects")
        return next(iter(classes), None)

    @staticmethod
    def _number(value: Any, label: str) -> float:
        if type(value) not in {int, float} or not math.isfinite(value):
            raise ValueError(f"official SDE {label} is not a finite number")
        return float(value)

    @classmethod
    def _integer(cls, value: Any, label: str) -> int:
        number = cls._number(value, label)
        if number < 0 or not number.is_integer():
            raise ValueError(f"official SDE {label} is not a nonnegative integer")
        return int(number)

    @staticmethod
    def _bytes(path: Path) -> int:
        if path.is_file():
            return path.stat().st_size
        if path.is_dir():
            return sum(child.stat().st_size for child in path.rglob("*") if child.is_file())
        return 0
