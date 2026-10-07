"""FastMCP stdio server; no network listener is started by default."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from eve_mcp.auth.sso import RefreshingAccessTokenProvider
from eve_mcp.auth.token_store import KeyringTokenStore
from eve_mcp.config import Settings
from eve_mcp.esi.client import EsiClient
from eve_mcp.esi.endpoints import EsiCharacterEndpoints
from eve_mcp.mcp.character_tools import CharacterEndpoints, CharacterTools
from eve_mcp.mcp.profile_tools import ProfileTools
from eve_mcp.profiles import ProfileRepository


def build_server(
    profiles: ProfileRepository | None = None,
    endpoints: CharacterEndpoints | None = None,
) -> Any:
    """Construct the server with injectable dependencies and no bound socket."""
    from fastmcp import FastMCP

    settings = Settings.from_environment()
    profiles = profiles or ProfileRepository(Path(settings.data_dir) / "eve-mcp.db")
    if endpoints is None:
        endpoint_service: CharacterEndpoints = EsiCharacterEndpoints(
            EsiClient(), RefreshingAccessTokenProvider(settings, KeyringTokenStore())
        )
    else:
        endpoint_service = endpoints
    characters = CharacterTools(profiles, endpoint_service)
    profile_tools = ProfileTools(profiles)
    server = FastMCP(
        "eve-mcp",
        instructions="Read-only EVE ESI data. Every data tool requires an explicit character.",
    )

    @server.tool()
    def eve_list_characters() -> dict[str, Any]:
        return profile_tools.list_characters()

    @server.tool()
    def eve_get_character_status(character: str) -> dict[str, Any]:
        return profile_tools.status(character)

    @server.tool()
    async def eve_get_character_summary(character: str) -> dict[str, Any]:
        return await characters.summary(character)

    @server.tool()
    async def eve_get_character(character: str) -> dict[str, Any]:
        return await characters.character(character)

    @server.tool()
    async def eve_get_skills(character: str) -> dict[str, Any]:
        return await characters.skills(character)

    @server.tool()
    async def eve_get_skill_queue(character: str, limit: int = 50) -> dict[str, Any]:
        return await characters.skill_queue(character, limit)

    @server.tool()
    async def eve_get_assets(
        character: str,
        location_id: int | None = None,
        type_id: int | None = None,
        include_nested: bool = False,
        limit: int = 250,
    ) -> dict[str, Any]:
        return await characters.assets(character, location_id, type_id, include_nested, limit)

    @server.tool()
    async def eve_get_mining_ledger(
        character: str, days: int = 30, limit: int = 250
    ) -> dict[str, Any]:
        return await characters.mining_ledger(character, days, limit)

    @server.tool()
    async def eve_get_industry_jobs(
        character: str, include_completed: bool = False, limit: int = 100
    ) -> dict[str, Any]:
        return await characters.industry_jobs(character, include_completed, limit)

    @server.tool()
    async def eve_get_blueprints(character: str, limit: int = 250) -> dict[str, Any]:
        """Return bounded, read-only ESI blueprints for the explicit character."""
        return await characters.blueprints(character, limit)

    @server.tool()
    async def eve_get_wallet_transactions(
        character: str, days: int = 30, limit: int = 250
    ) -> dict[str, Any]:
        """Return bounded recent, read-only ESI wallet transactions for the explicit character."""
        return await characters.wallet_transactions(character, days, limit)

    @server.tool()
    async def eve_get_character_market_orders(
        character: str, order_state: str = "active", limit: int = 250
    ) -> dict[str, Any]:
        """Return bounded, read-only ESI market orders for the explicit character."""
        return await characters.market_orders(character, order_state, limit)

    return server


def run_stdio() -> None:
    """Run strictly on standard input/output; FastMCP opens no TCP listener."""
    build_server().run(transport="stdio")
