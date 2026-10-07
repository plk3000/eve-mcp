"""Read-only explicit-character MCP tool implementations."""

from __future__ import annotations

from typing import Any, Protocol

from eve_mcp.profiles import ProfileRepository


class CharacterEndpoints(Protocol):
    async def character(self, character_id: str) -> dict[str, Any]: ...
    async def skills(self, character_id: str) -> dict[str, Any]: ...
    async def skill_queue(self, character_id: str, limit: int = 50) -> dict[str, Any]: ...
    async def assets(
        self,
        character_id: str,
        limit: int = 250,
        location_id: int | None = None,
        type_id: int | None = None,
        include_nested: bool = False,
    ) -> dict[str, Any]: ...
    async def mining_ledger(
        self, character_id: str, limit: int = 250, days: int = 30
    ) -> dict[str, Any]: ...
    async def industry_jobs(
        self, character_id: str, limit: int = 100, include_completed: bool = False
    ) -> dict[str, Any]: ...
    async def blueprints(self, character_id: str, limit: int = 250) -> dict[str, Any]: ...
    async def wallet_transactions(
        self, character_id: str, limit: int = 250, days: int = 30
    ) -> dict[str, Any]: ...
    async def market_orders(
        self, character_id: str, limit: int = 250, state: str = "active"
    ) -> dict[str, Any]: ...


class CharacterTools:
    def __init__(self, profiles: ProfileRepository, endpoints: CharacterEndpoints) -> None:
        self.profiles, self.endpoints = profiles, endpoints

    def _id(self, character: str) -> str:
        return self.profiles.resolve(character).character_id

    async def character(self, character: str) -> dict[str, Any]:
        return await self.endpoints.character(self._id(character))

    async def skills(self, character: str) -> dict[str, Any]:
        return await self.endpoints.skills(self._id(character))

    async def skill_queue(self, character: str, limit: int = 50) -> dict[str, Any]:
        return await self.endpoints.skill_queue(self._id(character), min(max(limit, 1), 250))

    async def assets(
        self,
        character: str,
        location_id: int | None = None,
        type_id: int | None = None,
        include_nested: bool = False,
        limit: int = 250,
    ) -> dict[str, Any]:
        return await self.endpoints.assets(
            self._id(character),
            min(max(limit, 1), 1000),
            location_id=location_id,
            type_id=type_id,
            include_nested=include_nested,
        )

    async def mining_ledger(
        self, character: str, days: int = 30, limit: int = 250
    ) -> dict[str, Any]:
        return await self.endpoints.mining_ledger(
            self._id(character), min(max(limit, 1), 1000), days=min(max(days, 1), 365)
        )

    async def industry_jobs(
        self, character: str, include_completed: bool = False, limit: int = 100
    ) -> dict[str, Any]:
        return await self.endpoints.industry_jobs(
            self._id(character), min(max(limit, 1), 1000), include_completed=include_completed
        )

    async def blueprints(self, character: str, limit: int = 250) -> dict[str, Any]:
        return await self.endpoints.blueprints(self._id(character), min(max(limit, 1), 1000))

    async def wallet_transactions(
        self, character: str, days: int = 30, limit: int = 250
    ) -> dict[str, Any]:
        return await self.endpoints.wallet_transactions(
            self._id(character), min(max(limit, 1), 1000), days=min(max(days, 1), 90)
        )

    async def market_orders(
        self, character: str, order_state: str = "active", limit: int = 250
    ) -> dict[str, Any]:
        if order_state not in {"active", "cancelled", "expired", "fulfilled"}:
            raise ValueError("order_state must be active, cancelled, expired, or fulfilled")
        return await self.endpoints.market_orders(
            self._id(character), min(max(limit, 1), 1000), state=order_state
        )

    async def summary(self, character: str) -> dict[str, Any]:
        character_id = self._id(character)
        skills = await self.skills(character)
        queue = await self.skill_queue(character)
        assets = await self.assets(character, limit=1)
        mining = await self.mining_ledger(character, limit=1)
        jobs = await self.industry_jobs(character, limit=1)
        return {
            "character_id": character_id,
            "skills": skills["returned_count"],
            "skill_queue": queue["returned_count"],
            "assets": assets["total_available"],
            "mining_ledger": mining["total_available"],
            "industry_jobs": jobs["total_available"],
        }
