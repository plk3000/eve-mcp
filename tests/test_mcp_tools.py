import asyncio
from datetime import UTC, datetime


def test_tools_require_explicit_character_and_return_bounded_data(tmp_path) -> None:
    from eve_mcp.esi.endpoints import FixtureCharacterEndpoints
    from eve_mcp.mcp.character_tools import CharacterTools
    from eve_mcp.mcp.profile_tools import ProfileTools
    from eve_mcp.profiles import ProfileRepository

    profiles = ProfileRepository(tmp_path / "profiles.sqlite")
    profiles.upsert("100", "Alice", ["esi-skills.read_skills.v1"], datetime.now(UTC), "ok")
    endpoints = FixtureCharacterEndpoints(
        {"100": {"skills": [{"skill_id": 1}], "assets": [{"type_id": 2}]}}
    )
    characters = CharacterTools(profiles, endpoints)
    profiles_tool = ProfileTools(profiles)
    assert profiles_tool.list_characters()["returned_count"] == 1
    assert asyncio.run(characters.skills("Alice"))["character_id"] == "100"
    assert asyncio.run(characters.assets("100", limit=1))["returned_count"] == 1


def test_server_has_selected_v1_tools() -> None:
    from eve_mcp.mcp.server import build_server

    server = build_server()
    names = {tool.name for tool in server._tool_manager._tools.values()}
    assert {
        "eve_list_characters",
        "eve_get_character_status",
        "eve_get_skills",
        "eve_get_assets",
        "eve_get_mining_ledger",
        "eve_get_industry_jobs",
    } <= names
