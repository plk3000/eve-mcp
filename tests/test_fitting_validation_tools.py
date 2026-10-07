from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from eve_mcp.esi.endpoints import FixtureCharacterEndpoints
from eve_mcp.mcp.character_tools import CharacterTools
from eve_mcp.profiles import ProfileRepository
from eve_mcp.static_data.catalog import StaticCatalog, StaticType


def test_validator_returns_character_bound_canonical_proposal(tmp_path) -> None:
    catalog = StaticCatalog.create(
        tmp_path / "catalog.sqlite3",
        "fixture",
        [
            StaticType(
                1,
                "Hull",
                "hull",
                "Frigate",
                "Ship",
                None,
                10,
                10,
                0,
                {"high": 1},
                {10: 1},
            ),
            StaticType(
                2,
                "Module",
                "module",
                "Module",
                "Module",
                "high",
                2,
                2,
                0,
                {},
                {20: 1},
            ),
        ],
    )
    profiles = ProfileRepository(tmp_path / "profiles.sqlite")
    profiles.upsert("100", "Alice", [], datetime.now(UTC), "ok")
    profiles.upsert("200", "Bob", [], datetime.now(UTC), "ok")
    endpoints = FixtureCharacterEndpoints(
        {
            "100": {
                "skills": [
                    {"skill_id": 10, "active_skill_level": 1},
                    {"skill_id": 20, "active_skill_level": 1},
                ]
            },
            "200": {"skills": []},
        }
    )
    tools = CharacterTools(profiles, endpoints, lambda: catalog)

    result = asyncio.run(
        tools.validate_fitting(
            "Alice",
            {
                "name": "Approved fit",
                "description": "Reviewed",
                "ship_type_id": 1,
                "items": [{"type_id": 2, "flag": "HiSlot0", "quantity": 1}],
            },
            include_asset_check=False,
        )
    )

    assert result["status"] == "valid"
    assert result["proposal"]["character_id"] == "100"
    assert result["proposal"]["catalog_version"] == "fixture"
    assert result["proposal"]["proposal_id"]
    assert "asset_availability" not in result


def test_truncated_asset_read_never_claims_item_absence(tmp_path) -> None:
    catalog = StaticCatalog.create(
        tmp_path / "catalog.sqlite3",
        "fixture",
        [
            StaticType(1, "Hull", "hull", "Frigate", "Ship", None, 10, 10, 0, {"high": 1}, {}),
            StaticType(2, "Module", "module", "Module", "Module", "high", 2, 2, 0, {}, {}),
        ],
    )
    profiles = ProfileRepository(tmp_path / "profiles.sqlite")
    profiles.upsert("100", "Alice", [], datetime.now(UTC), "ok")
    assets = [{"type_id": 999, "quantity": 1} for _ in range(1000)]
    assets.append({"type_id": 2, "quantity": 1})
    endpoints = FixtureCharacterEndpoints(
        {
            "100": {
                "skills": [],
                "assets": assets,
            }
        }
    )
    tools = CharacterTools(profiles, endpoints, lambda: catalog)

    result = asyncio.run(
        tools.validate_fitting(
            "Alice",
            {
                "name": "Fit",
                "description": "",
                "ship_type_id": 1,
                "items": [{"type_id": 2, "flag": "HiSlot0", "quantity": 1}],
            },
            include_asset_check=True,
        )
    )

    assert result["asset_inventory_truncated"] is True
    assert result["asset_availability"][0]["sufficient"] is None


def test_server_exposes_discovery_context_and_validation_tools_only() -> None:
    from eve_mcp.mcp.server import build_server

    names = {tool.name for tool in build_server()._tool_manager._tools.values()}

    assert {
        "eve_search_fitting_types",
        "eve_get_fitting_context",
        "eve_validate_fitting",
    } <= names
    assert not any("delete_fitting" in name or "update_fitting" in name for name in names)
