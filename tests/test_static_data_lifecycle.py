from __future__ import annotations

import fcntl
import hashlib
import io
import json
from zipfile import ZipFile

import httpx
import pytest
from typer.testing import CliRunner

from eve_mcp import cli
from eve_mcp.static_data.refresh import StaticDataManager, StaticDataSourceUnavailable

LATEST_URL = "https://developers.eveonline.com/static-data/tranquility/latest.jsonl"
ARCHIVE_URL = (
    "https://developers.eveonline.com/static-data/tranquility/"
    "eve-online-static-data-3586130-jsonl.zip"
)


def _official_archive(build_number: int = 3586130) -> bytes:
    categories = [
        {"_key": 6, "name": {"en": "Ship"}},
        {"_key": 7, "name": {"en": "Module"}},
        {"_key": 8, "name": {"en": "Charge"}},
    ]
    groups = [
        {"_key": 10, "categoryID": 6, "name": {"en": "Frigate"}},
        {"_key": 20, "categoryID": 7, "name": {"en": "Mining Laser"}},
        {"_key": 30, "categoryID": 8, "name": {"en": "Frequency Crystal"}},
    ]
    types = [
        {"_key": 100, "groupID": 10, "name": {"en": "Fixture Frigate"}, "published": True},
        {"_key": 200, "groupID": 20, "name": {"en": "Fixture Mining Laser"}, "published": True},
        {"_key": 300, "groupID": 30, "name": {"en": "Fixture Charge"}, "published": True},
    ]
    attributes = [
        {"_key": 11, "name": "powerOutput", "defaultValue": 0},
        {"_key": 12, "name": "lowSlots", "defaultValue": 0},
        {"_key": 13, "name": "medSlots", "defaultValue": 0},
        {"_key": 14, "name": "hiSlots", "defaultValue": 0},
        {"_key": 48, "name": "cpuOutput", "defaultValue": 0},
        {"_key": 50, "name": "cpu", "defaultValue": 0},
        {"_key": 182, "name": "requiredSkill1", "defaultValue": 0},
        {"_key": 277, "name": "requiredSkill1Level", "defaultValue": 1},
        {"_key": 30, "name": "power", "defaultValue": 0},
        {"_key": 1132, "name": "upgradeCapacity", "defaultValue": 0},
        {"_key": 1133, "name": "upgradeCost", "defaultValue": 0},
        {"_key": 1137, "name": "rigSlots", "defaultValue": 0},
        {"_key": 2056, "name": "serviceSlots", "defaultValue": 0},
        *[
            {"_key": 3000 + index, "name": f"requiredSkill{index}", "defaultValue": 0}
            for index in range(2, 7)
        ],
        *[
            {
                "_key": 3100 + index,
                "name": f"requiredSkill{index}Level",
                "defaultValue": 1,
            }
            for index in range(2, 7)
        ],
    ]
    type_dogma = [
        {
            "_key": 100,
            "dogmaAttributes": [
                {"attributeID": 11, "value": 41},
                {"attributeID": 12, "value": 2},
                {"attributeID": 13, "value": 3},
                {"attributeID": 14, "value": 4},
                {"attributeID": 48, "value": 130},
                {"attributeID": 1132, "value": 400},
                {"attributeID": 182, "value": 3329},
                {"attributeID": 277, "value": 1},
            ],
            "dogmaEffects": [],
        },
        {
            "_key": 200,
            "dogmaAttributes": [
                {"attributeID": 30, "value": 2},
                {"attributeID": 50, "value": 60},
                {"attributeID": 182, "value": 3386},
                {"attributeID": 277, "value": 1},
            ],
            "dogmaEffects": [{"effectID": 12, "isDefault": False}],
        },
        {"_key": 300, "dogmaAttributes": [], "dogmaEffects": []},
    ]
    effects = [{"_key": 12, "name": "hiPower"}]
    data = {
        "_sde.jsonl": [
            {"_key": "sde", "buildNumber": build_number, "releaseDate": "2026-10-07T11:10:05Z"}
        ],
        "types.jsonl": types,
        "typeDogma.jsonl": type_dogma,
        "dogmaAttributes.jsonl": attributes,
        "dogmaEffects.jsonl": effects,
        "groups.jsonl": groups,
        "categories.jsonl": categories,
    }
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        for filename, records in data.items():
            archive.writestr(
                filename,
                "".join(json.dumps(record) + "\n" for record in records),
            )
    return buffer.getvalue()


def _latest(build_number: int = 3586130) -> bytes:
    return (
        json.dumps(
            {
                "_key": "sde",
                "buildNumber": build_number,
                "releaseDate": "2026-10-07T11:10:05Z",
            }
        )
        + "\n"
    ).encode()


def _manager(tmp_path, archive: bytes | None = None) -> tuple[StaticDataManager, list[str]]:
    payload = _official_archive() if archive is None else archive
    requests: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if request.url == httpx.URL(LATEST_URL):
            return httpx.Response(200, content=_latest())
        if request.url == httpx.URL(ARCHIVE_URL):
            return httpx.Response(200, content=payload)
        return httpx.Response(404)

    transport = httpx.MockTransport(handle)
    return StaticDataManager(tmp_path, http_transport=transport), requests


def _rewrite_archive(
    content: bytes,
    *,
    omit: str | None = None,
    malformed: str | None = None,
) -> bytes:
    rewritten = io.BytesIO()
    with ZipFile(io.BytesIO(content)) as source, ZipFile(rewritten, "w") as target:
        for filename in source.namelist():
            if filename == omit:
                continue
            target.writestr(
                filename,
                b"{malformed json}\n" if filename == malformed else source.read(filename),
            )
    return rewritten.getvalue()


def test_status_is_offline_and_reports_missing_catalog(tmp_path) -> None:
    manager, requests = _manager(tmp_path)

    status = manager.status()

    assert status["active_build"] is None
    assert status["installed_builds"] == []
    assert requests == []


def test_cli_status_refresh_and_clear_use_explicit_lifecycle(tmp_path, monkeypatch) -> None:
    manager, requests = _manager(tmp_path)
    monkeypatch.setattr(cli, "_static_data", lambda: manager)
    runner = CliRunner()

    status = runner.invoke(cli.app, ["static-data", "status"])
    assert status.exit_code == 0
    assert json.loads(status.stdout)["active_build"] is None
    assert requests == []

    refreshed = runner.invoke(cli.app, ["static-data", "refresh"])
    assert refreshed.exit_code == 0
    assert json.loads(refreshed.stdout)["active_build"] == "3586130"
    assert requests == [LATEST_URL, ARCHIVE_URL]

    cleared = runner.invoke(cli.app, ["static-data", "clear", "--all", "--yes"])
    assert cleared.exit_code == 0
    assert "Clearing " in cleared.stdout
    assert not manager.root.exists()
    assert not manager.cache_root.exists()


def test_official_refresh_imports_real_shaped_sde_and_records_download_checksum(
    tmp_path,
) -> None:
    archive = _official_archive()
    manager, requests = _manager(tmp_path, archive)

    result = manager.refresh_official()

    assert result["active_build"] == "3586130"
    assert requests == [LATEST_URL, ARCHIVE_URL]
    provenance = json.loads((manager.catalog_root / "3586130" / "manifest.json").read_text())
    assert provenance["build_id"] == "3586130"
    assert provenance["archive"]["name"] == "eve-online-static-data-3586130-jsonl.zip"
    assert provenance["archive"]["downloaded_bytes"] == len(archive)
    assert provenance["archive"]["sha256"] == hashlib.sha256(archive).hexdigest()
    assert (
        manager.cache_root / "3586130" / "raw" / "eve-online-static-data-3586130-jsonl.zip"
    ).read_bytes() == archive

    catalog = manager.catalog()
    hull = catalog.get_type(100)
    module = catalog.get_type(200)
    assert hull is not None
    assert (hull.name, hull.kind, hull.slots, hull.required_skills) == (
        "Fixture Frigate",
        "hull",
        {"high": 4, "medium": 3, "low": 2, "rig": 0, "service": 0},
        {3329: 1},
    )
    assert hull.cpu == 130
    assert hull.powergrid == 41
    assert hull.calibration == 400
    assert module is not None
    assert (module.name, module.kind, module.slot_class) == (
        "Fixture Mining Laser",
        "module",
        "high",
    )
    assert module.cpu == 60
    assert module.powergrid == 2
    assert module.required_skills == {3386: 1}
    assert catalog.get_type(300).kind == "charge"


def test_refresh_of_same_build_does_not_redownload_archive_unless_forced(tmp_path) -> None:
    manager, requests = _manager(tmp_path)

    assert manager.refresh_official()["active_build"] == "3586130"
    first_pointer = manager.current_path.read_bytes()
    assert manager.refresh_official()["unchanged"] is True
    assert manager.current_path.read_bytes() == first_pointer
    assert requests == [LATEST_URL, ARCHIVE_URL, LATEST_URL]

    assert manager.refresh_official(force=True)["unchanged"] is False
    assert requests == [LATEST_URL, ARCHIVE_URL, LATEST_URL, LATEST_URL, ARCHIVE_URL]


def test_invalid_archive_preserves_active_catalog_and_cache_byte_for_byte(tmp_path) -> None:
    manager, _ = _manager(tmp_path)
    manager.refresh_official()
    pointer_before = manager.current_path.read_bytes()
    catalog_before = (manager.catalog_root / "3586130" / "catalog.sqlite3").read_bytes()
    archive_before = (
        manager.cache_root / "3586130" / "raw" / "eve-online-static-data-3586130-jsonl.zip"
    ).read_bytes()
    broken_manager, _ = _manager(tmp_path, b"not a zip archive")

    with pytest.raises(ValueError, match="archive"):
        broken_manager.refresh_official(force=True)

    assert manager.current_path.read_bytes() == pointer_before
    assert (manager.catalog_root / "3586130" / "catalog.sqlite3").read_bytes() == catalog_before
    assert (
        manager.cache_root / "3586130" / "raw" / "eve-online-static-data-3586130-jsonl.zip"
    ).read_bytes() == archive_before


def test_archive_build_mismatch_is_rejected_before_pointer_promotion(tmp_path) -> None:
    manager, _ = _manager(tmp_path, _official_archive(build_number=123))

    with pytest.raises(ValueError, match="build metadata"):
        manager.refresh_official()

    assert manager.status()["active_build"] is None
    assert manager.status()["installed_builds"] == []


@pytest.mark.parametrize(
    ("broken_archive", "message"),
    [
        (_rewrite_archive(_official_archive(), omit="types.jsonl"), "required JSONL"),
        (_rewrite_archive(_official_archive(), malformed="types.jsonl"), "malformed"),
    ],
)
def test_incomplete_or_malformed_dataset_preserves_active_catalog(
    tmp_path, broken_archive: bytes, message: str
) -> None:
    manager, _ = _manager(tmp_path)
    manager.refresh_official()
    pointer_before = manager.current_path.read_bytes()
    catalog_before = (manager.catalog_root / "3586130" / "catalog.sqlite3").read_bytes()
    archive_before = (
        manager.cache_root / "3586130" / "raw" / "eve-online-static-data-3586130-jsonl.zip"
    ).read_bytes()
    broken_manager, _ = _manager(tmp_path, broken_archive)

    with pytest.raises(ValueError, match=message):
        broken_manager.refresh_official(force=True)

    assert manager.current_path.read_bytes() == pointer_before
    assert (manager.catalog_root / "3586130" / "catalog.sqlite3").read_bytes() == catalog_before
    assert (
        manager.cache_root / "3586130" / "raw" / "eve-online-static-data-3586130-jsonl.zip"
    ).read_bytes() == archive_before


def test_refresh_does_not_follow_archive_redirects(tmp_path) -> None:
    requests: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if request.url == httpx.URL(LATEST_URL):
            return httpx.Response(200, content=_latest())
        return httpx.Response(302, headers={"Location": "https://not-ccp.example/archive.zip"})

    manager = StaticDataManager(tmp_path, http_transport=httpx.MockTransport(handle))

    with pytest.raises(StaticDataSourceUnavailable, match="HTTP 302"):
        manager.refresh_official()

    assert requests == [LATEST_URL, ARCHIVE_URL]


def test_clear_requires_confirmation_and_preserves_adjacent_profile_data(tmp_path) -> None:
    manager, _ = _manager(tmp_path)
    protected = tmp_path / "eve-mcp.db"
    protected.write_text("profile metadata", encoding="utf-8")

    with pytest.raises(ValueError, match="--yes"):
        manager.clear_all(yes=False)
    manager.refresh_official()
    result = manager.clear_all(yes=True)

    assert protected.read_text(encoding="utf-8") == "profile metadata"
    assert result["removed_bytes"] > len("profile metadata")
    assert result["paths"] == [str(manager.root), str(manager.cache_root)]
    assert not manager.root.exists()
    assert not manager.cache_root.exists()


def test_clear_active_build_requires_confirmation_and_reports_feature_impact(tmp_path) -> None:
    manager, _ = _manager(tmp_path)
    manager.refresh_official()

    with pytest.raises(ValueError, match="--yes"):
        manager.clear_build("3586130", yes=False)
    result = manager.clear_build("3586130", yes=True)

    assert "unavailable until refresh" in result["warning"]
    assert manager.status()["active_build"] is None
    assert manager.catalog_root.joinpath("3586130").exists() is False


def test_concurrent_refresh_is_refused_by_process_lock(tmp_path) -> None:
    manager, _ = _manager(tmp_path)
    manager.root.mkdir(parents=True)
    with manager.lock_path.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(RuntimeError, match="lifecycle operation is running"):
            manager.refresh_official()
