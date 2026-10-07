from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx


def test_fittings_retrieval_resolves_character_and_filters_hull(tmp_path) -> None:
    from eve_mcp.esi.endpoints import FixtureCharacterEndpoints
    from eve_mcp.mcp.character_tools import CharacterTools
    from eve_mcp.profiles import ProfileRepository

    profiles = ProfileRepository(tmp_path / "profiles.sqlite")
    profiles.upsert("100", "Alice", [], datetime.now(UTC), "ok")
    profiles.upsert("200", "Bob", [], datetime.now(UTC), "ok")
    endpoints = FixtureCharacterEndpoints(
        {
            "100": {
                "fittings": [
                    {"fitting_id": 3, "ship_type_id": 999},
                    {"fitting_id": 1, "ship_type_id": 123},
                ]
            },
            "200": {"fittings": [{"fitting_id": 2, "ship_type_id": 999}]},
        }
    )

    result = asyncio.run(CharacterTools(profiles, endpoints).fittings("Alice", 123, limit=1))

    assert result["character_id"] == "100"
    assert result["items"] == [{"fitting_id": 1, "ship_type_id": 123}]
    assert result["returned_count"] == 1
    assert result["total_available"] == 1


def test_production_fittings_reads_selected_character_endpoint() -> None:
    import asyncio

    from eve_mcp.esi.client import EsiClient
    from eve_mcp.esi.endpoints import EsiCharacterEndpoints

    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=[{"fitting_id": 1, "ship_type_id": 123}])

    class Tokens:
        async def get_access_token(self, character_id: str) -> str:
            assert character_id == "100"
            return "token"

    result = asyncio.run(
        EsiCharacterEndpoints(EsiClient(transport=httpx.MockTransport(handler)), Tokens()).fittings(
            "100", limit=1
        )
    )

    assert result["items"][0]["fitting_id"] == 1
    assert calls[0].url.path == "/latest/characters/100/fittings/"
    assert calls[0].headers["authorization"].startswith("Bearer ")


def test_create_endpoint_posts_once_with_selected_token_and_invalidates_cache() -> None:
    import asyncio

    from eve_mcp.esi.client import EsiClient
    from eve_mcp.esi.endpoints import EsiCharacterEndpoints

    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=[])
        return httpx.Response(201, json={"fitting_id": 4})

    class Tokens:
        async def get_access_token(self, character_id: str) -> str:
            assert character_id == "100"
            return "token-for-100"

    client = EsiClient(transport=httpx.MockTransport(handler))
    endpoints = EsiCharacterEndpoints(client, Tokens())

    async def exercise() -> None:
        await endpoints.fittings("100")
        assert ("100", "characters/100/fittings/") in client.cache
        response = await endpoints.create_fitting(
            "100",
            {
                "name": "New",
                "description": "",
                "ship_type_id": 123,
                "items": [],
            },
        )
        assert response == {"fitting_id": 4}

    asyncio.run(exercise())

    assert [request.method for request in calls] == ["GET", "POST"]
    assert calls[1].url.path == "/latest/characters/100/fittings/"
    assert calls[1].headers["authorization"] == "Bearer token-for-100"
    assert ("100", "characters/100/fittings/") not in client.cache
