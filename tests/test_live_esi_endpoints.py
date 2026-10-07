from __future__ import annotations

import httpx
import pytest

from eve_mcp.esi.client import EsiClient, EsiHttpError, EsiScopeError
from eve_mcp.esi.endpoints import EsiCharacterEndpoints


class AccessTokens:
    async def get_access_token(self, character_id: str) -> str:
        return {"100": "access-for-100", "200": "access-for-200"}[character_id]


@pytest.mark.asyncio
async def test_live_endpoints_use_per_character_token_and_paginate_assets() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.headers["authorization"] == "Bearer access-for-100"
        if request.url.path.endswith("/assets/") and request.url.params["page"] == "1":
            return httpx.Response(
                200, json=[{"item_id": 1, "location_flag": "Hangar"}], headers={"X-Pages": "2"}
            )
        if request.url.path.endswith("/assets/"):
            return httpx.Response(
                200, json=[{"item_id": 2, "location_flag": "Cargo"}], headers={"X-Pages": "2"}
            )
        raise AssertionError(request.url)

    endpoints = EsiCharacterEndpoints(
        EsiClient(transport=httpx.MockTransport(handler)), AccessTokens()
    )
    result = await endpoints.assets("100", include_nested=True, limit=2)

    assert [item["item_id"] for item in result["items"]] == [1, 2]
    assert result["total_available"] is None
    assert result["truncated"] is False
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_live_endpoints_apply_nested_asset_filter_and_preserve_page_metadata() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {"item_id": 1, "location_id": 9, "type_id": 34, "is_singleton": False},
                {"item_id": 2, "location_id": 1, "type_id": 34, "is_singleton": False},
            ],
            headers={"X-Pages": "1"},
        )

    endpoints = EsiCharacterEndpoints(
        EsiClient(transport=httpx.MockTransport(handler)), AccessTokens()
    )
    result = await endpoints.assets("100", location_id=9, type_id=34, include_nested=False, limit=1)

    assert result["items"] == [
        {"item_id": 1, "location_id": 9, "type_id": 34, "is_singleton": False}
    ]
    assert result["returned_count"] == 1
    assert result["truncated"] is False
    assert result["next_page"] is None


@pytest.mark.asyncio
async def test_live_endpoints_normalize_scope_and_http_failures_without_token() -> None:
    def scope_handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": "missing required scope"})

    endpoints = EsiCharacterEndpoints(
        EsiClient(transport=httpx.MockTransport(scope_handler)), AccessTokens()
    )
    with pytest.raises(EsiScopeError) as error:
        await endpoints.skills("100")
    assert "access-for-100" not in str(error.value)

    def http_handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "server error"})

    endpoints = EsiCharacterEndpoints(
        EsiClient(transport=httpx.MockTransport(http_handler)), AccessTokens()
    )
    with pytest.raises(EsiHttpError) as error:
        await endpoints.character("100")
    assert "server error" not in str(error.value)


@pytest.mark.asyncio
async def test_live_endpoints_cover_selected_routes_and_bounds() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(str(request.url))
        payload: object = {"name": "Alice"}
        if request.url.path.endswith(("/skillqueue/", "/mining/", "/industry/jobs/")):
            payload = [{"id": 1}, {"id": 2}]
        return httpx.Response(200, json=payload, headers={"X-Pages": "1"})

    endpoints = EsiCharacterEndpoints(
        EsiClient(transport=httpx.MockTransport(handler)), AccessTokens()
    )
    await endpoints.character("100")
    await endpoints.skills("100")
    assert (await endpoints.skill_queue("100", limit=1))["returned_count"] == 1
    assert (await endpoints.mining_ledger("100", days=30, limit=1))["returned_count"] == 1
    assert (await endpoints.industry_jobs("100", include_completed=True, limit=1))[
        "returned_count"
    ] == 1

    assert any(path.endswith("/characters/100/") for path in paths)
    assert any(path.endswith("/characters/100/skills/") for path in paths)
    assert any("/skillqueue/" in path for path in paths)
    assert any("/mining/?from_date=" in path for path in paths)
    assert any("/industry/jobs/?include_completed=true" in path for path in paths)
