from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from eve_mcp.static_data.catalog import StaticCatalog, StaticType


def test_search_is_bounded_case_insensitive_and_kind_filtered(tmp_path) -> None:
    from eve_mcp.esi.endpoints import FixtureCharacterEndpoints
    from eve_mcp.mcp.character_tools import CharacterTools
    from eve_mcp.profiles import ProfileRepository

    catalog = StaticCatalog.create(
        tmp_path / "catalog.sqlite3",
        "fixture",
        [
            StaticType(1, "Nova Frigate", "hull", "Frigate", "Ship", None, 0, 0, 0, {}, {}),
            StaticType(2, "Nova Launcher", "module", "Launcher", "Module", "high", 1, 1, 0, {}, {}),
        ],
    )
    profiles = ProfileRepository(tmp_path / "profiles.sqlite")
    profiles.upsert("100", "Alice", [], datetime.now(UTC), "ok")
    tools = CharacterTools(profiles, FixtureCharacterEndpoints({}), lambda: catalog)

    result = tools.search_fitting_types("nOvA", kind="module", limit=500)

    assert result["catalog_version"] == "fixture"
    assert [item["type_id"] for item in result["items"]] == [2]


def test_context_uses_selected_characters_skills_and_optional_hull(tmp_path) -> None:
    from eve_mcp.esi.endpoints import FixtureCharacterEndpoints
    from eve_mcp.mcp.character_tools import CharacterTools
    from eve_mcp.profiles import ProfileRepository

    catalog = StaticCatalog.create(
        tmp_path / "catalog.sqlite3",
        "fixture",
        [StaticType(1, "Nova Frigate", "hull", "Frigate", "Ship", None, 10, 20, 0, {}, {})],
    )
    profiles = ProfileRepository(tmp_path / "profiles.sqlite")
    profiles.upsert("100", "Alice", [], datetime.now(UTC), "ok")
    endpoints = FixtureCharacterEndpoints(
        {
            "100": {
                "character": {"name": "Alice"},
                "skills": [{"skill_id": 10, "active_skill_level": 3}],
            }
        }
    )
    tools = CharacterTools(profiles, endpoints, lambda: catalog)

    result = asyncio.run(tools.fitting_context("Alice", 1))

    assert result["character_id"] == "100"
    assert result["skills"] == [{"skill_id": 10, "level": 3}]
    assert result["hull"]["type_id"] == 1


def test_context_extracts_skills_from_the_production_esi_envelope(tmp_path) -> None:
    from eve_mcp.mcp.character_tools import CharacterTools
    from eve_mcp.profiles import ProfileRepository

    class ProductionShapedEndpoints:
        async def character(self, character_id: str) -> dict[str, object]:
            return {"character_id": character_id, "items": [{"name": "Alice"}]}

        async def skills(self, character_id: str) -> dict[str, object]:
            return {
                "character_id": character_id,
                "items": [
                    {
                        "skills": [
                            {"skill_id": 10, "active_skill_level": 3},
                            {"skill_id": 20, "trained_skill_level": 2},
                        ]
                    }
                ],
            }

    catalog = StaticCatalog.create(
        tmp_path / "catalog.sqlite3",
        "fixture",
        [StaticType(1, "Nova Frigate", "hull", "Frigate", "Ship", None, 10, 20, 0, {}, {})],
    )
    profiles = ProfileRepository(tmp_path / "profiles.sqlite")
    profiles.upsert("100", "Alice", [], datetime.now(UTC), "ok")
    tools = CharacterTools(profiles, ProductionShapedEndpoints(), lambda: catalog)

    result = asyncio.run(tools.fitting_context("Alice", 1))

    assert result["skills"] == [
        {"skill_id": 10, "level": 3},
        {"skill_id": 20, "level": 2},
    ]
