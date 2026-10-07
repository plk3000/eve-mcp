from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import httpx


def test_phase2_scopes_cover_only_the_confirmed_character_endpoints() -> None:
    from eve_mcp.auth.pkce import SCOPES

    assert {
        "esi-characters.read_blueprints.v1",
        "esi-wallet.read_character_wallet.v1",
        "esi-markets.read_character_orders.v1",
    } <= set(SCOPES)
    assert not any("corporation" in scope for scope in SCOPES)


def test_fixture_phase2_data_is_bounded_filtered_and_character_isolated(tmp_path) -> None:
    from eve_mcp.esi.endpoints import FixtureCharacterEndpoints
    from eve_mcp.mcp.character_tools import CharacterTools
    from eve_mcp.profiles import ProfileRepository

    profiles = ProfileRepository(tmp_path / "profiles.sqlite")
    profiles.upsert("100", "Alice", [], datetime.now(UTC), "authorized")
    profiles.upsert("200", "Bob", [], datetime.now(UTC), "authorized")
    fresh = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    stale = (datetime.now(UTC) - timedelta(days=90)).isoformat()
    endpoints = FixtureCharacterEndpoints(
        {
            "100": {
                "blueprints": [{"item_id": 1}, {"item_id": 2}],
                "wallet_transactions": [
                    {"transaction_id": 1, "date": fresh},
                    {"transaction_id": 2, "date": stale},
                ],
                "market_orders": [
                    {"order_id": 1, "state": "active"},
                    {"order_id": 2, "state": "expired"},
                ],
            },
            "200": {
                "blueprints": [{"item_id": 99}],
                "wallet_transactions": [],
                "market_orders": [],
            },
        }
    )
    tools = CharacterTools(profiles, endpoints)

    assert [
        item["item_id"] for item in asyncio.run(tools.blueprints("Alice", limit=1))["items"]
    ] == [1]
    assert asyncio.run(tools.blueprints("Bob"))["items"] == [{"item_id": 99}]
    assert [
        item["transaction_id"]
        for item in asyncio.run(tools.wallet_transactions("Alice", days=7))["items"]
    ] == [1]
    assert [
        item["order_id"]
        for item in asyncio.run(tools.market_orders("Alice", order_state="active"))["items"]
    ] == [1]


def test_phase2_production_routes_use_selected_character_token_and_safe_pagination() -> None:
    from eve_mcp.esi.client import EsiClient
    from eve_mcp.esi.endpoints import EsiCharacterEndpoints

    class Tokens:
        async def get_access_token(self, character_id: str) -> str:
            return {"100": "token-for-alice", "200": "token-for-bob"}[character_id]

    calls: list[httpx.Request] = []
    fresh = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    stale = (datetime.now(UTC) - timedelta(days=90)).isoformat()

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.headers["Authorization"] == "Bearer token-for-alice"
        if request.url.path.endswith("/blueprints/"):
            return httpx.Response(
                200, json=[{"item_id": 1}, {"item_id": 2}], headers={"X-Pages": "1"}
            )
        if request.url.path.endswith("/wallet/transactions/"):
            return httpx.Response(
                200,
                json=[
                    {"transaction_id": 1, "date": fresh},
                    {"transaction_id": 2, "date": stale},
                ],
                headers={"X-Pages": "1"},
            )
        if request.url.path.endswith("/orders/history/"):
            return httpx.Response(
                200,
                json=[{"order_id": 3, "state": "cancelled"}],
                headers={"X-Pages": "1"},
            )
        if request.url.path.endswith("/orders/"):
            return httpx.Response(
                200,
                json=[{"order_id": 1, "state": "active"}, {"order_id": 2, "state": "expired"}],
                headers={"X-Pages": "1"},
            )
        raise AssertionError(request.url)

    endpoints = EsiCharacterEndpoints(EsiClient(transport=httpx.MockTransport(handler)), Tokens())
    assert (asyncio.run(endpoints.blueprints("100", limit=1)))["returned_count"] == 1
    assert [
        item["transaction_id"]
        for item in asyncio.run(endpoints.wallet_transactions("100", days=7))["items"]
    ] == [1]
    assert [
        item["order_id"]
        for item in asyncio.run(endpoints.market_orders("100", state="active"))["items"]
    ] == [1, 2]
    assert [
        item["order_id"]
        for item in asyncio.run(endpoints.market_orders("100", state="cancelled"))["items"]
    ] == [3]
    assert {request.url.path for request in calls} == {
        "/latest/characters/100/blueprints/",
        "/latest/characters/100/wallet/transactions/",
        "/latest/characters/100/orders/",
        "/latest/characters/100/orders/history/",
    }


def test_server_discovers_all_phase2_read_only_tools() -> None:
    from eve_mcp.mcp.server import build_server

    server = build_server()
    names = {tool.name for tool in server._tool_manager._tools.values()}
    assert {
        "eve_get_blueprints",
        "eve_get_wallet_transactions",
        "eve_get_character_market_orders",
    } <= names
