"""FastMCP stdio server; no network listener is started by default."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from eve_mcp.auth.sso import RefreshingAccessTokenProvider
from eve_mcp.auth.token_store import KeyringTokenStore
from eve_mcp.config import Settings
from eve_mcp.esi.client import EsiClient
from eve_mcp.esi.endpoints import EsiCharacterEndpoints
from eve_mcp.fittings.creation_ledger import CreationLedger
from eve_mcp.fittings.writer import FittingWriter
from eve_mcp.mcp.character_tools import CharacterEndpoints, CharacterTools
from eve_mcp.mcp.profile_tools import ProfileTools
from eve_mcp.profiles import ProfileRepository
from eve_mcp.static_data.refresh import StaticDataManager


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

    def catalog_provider() -> Any:
        return StaticDataManager(settings.data_dir).catalog()

    fitting_writer = FittingWriter(
        profiles,
        endpoint_service,
        lambda version: StaticDataManager(settings.data_dir).catalog(version),
        CreationLedger(settings.data_dir / "fitting-creations.sqlite3"),
    )
    characters = CharacterTools(profiles, endpoint_service, catalog_provider, fitting_writer)
    profile_tools = ProfileTools(profiles)
    server = FastMCP(
        "eve-mcp",
        instructions=(
            "EVE ESI data tools require an explicit character. The only fitting mutation "
            "creates a new saved fitting; it never updates or deletes."
        ),
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
    async def eve_get_fittings(
        character: str, ship_type_id: int | None = None, limit: int = 100
    ) -> dict[str, Any]:
        """Return bounded saved fittings for the explicit character; this is not an active fit."""
        return await characters.fittings(character, ship_type_id, limit)

    @server.tool()
    def eve_search_fitting_types(
        query: str, kind: str | None = None, limit: int = 20
    ) -> dict[str, Any]:
        """Search bounded fitting names in the installed offline catalog."""
        return characters.search_fitting_types(query, kind, limit)

    @server.tool()
    async def eve_get_fitting_context(
        character: str, hull_type_id: int | None = None
    ) -> dict[str, Any]:
        """Return selected-character skills and optional catalog hull facts."""
        return await characters.fitting_context(character, hull_type_id)

    @server.tool()
    async def eve_validate_fitting(
        character: str,
        fitting: dict[str, Any],
        include_asset_check: bool = True,
    ) -> dict[str, Any]:
        """Validate a proposed payload; validation does not save, buy, or fit anything."""
        return await characters.validate_fitting(character, fitting, include_asset_check)

    @server.tool()
    async def eve_create_fitting(
        character: str,
        proposal: dict[str, Any],
        proposal_id: str,
        confirm_create: Literal[True],
    ) -> dict[str, Any]:
        """Creates one new saved fitting for the selected character; never updates or deletes.

        Call only after direct operator intent to save the reviewed exact proposal. Requires
        the canonical proposal ID, matching selected character, installed catalog, scopes,
        literal confirmation, conflict preflight, and successful fresh readback.
        """
        return await characters.create_fitting(character, proposal, proposal_id, confirm_create)

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
