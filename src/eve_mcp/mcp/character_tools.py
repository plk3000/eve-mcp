"""Explicit-character MCP tool implementations."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from typing import Any, Protocol

from eve_mcp.fittings.models import Fitting, FittingItem
from eve_mcp.fittings.proposal import create_proposal
from eve_mcp.fittings.skill_data import extract_skill_rows
from eve_mcp.fittings.validation import trained_skill_levels, validate_fitting
from eve_mcp.fittings.writer import FittingWriter
from eve_mcp.profiles import ProfileRepository
from eve_mcp.static_data.catalog import StaticCatalog, StaticType


class CharacterEndpoints(Protocol):
    async def character(self, character_id: str) -> dict[str, Any]: ...
    async def skills(self, character_id: str) -> dict[str, Any]: ...
    async def fittings(
        self, character_id: str, limit: int = 100, fresh: bool = False
    ) -> dict[str, Any]: ...
    async def create_fitting(self, character_id: str, fitting: dict[str, Any]) -> Any: ...
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
    def __init__(
        self,
        profiles: ProfileRepository,
        endpoints: CharacterEndpoints,
        catalog_provider: Callable[[], StaticCatalog] | None = None,
        fitting_writer: FittingWriter | None = None,
    ) -> None:
        self.profiles, self.endpoints = profiles, endpoints
        self.catalog_provider = catalog_provider
        self.fitting_writer = fitting_writer

    def _id(self, character: str) -> str:
        return self.profiles.resolve(character).character_id

    async def character(self, character: str) -> dict[str, Any]:
        return await self.endpoints.character(self._id(character))

    async def skills(self, character: str) -> dict[str, Any]:
        return await self.endpoints.skills(self._id(character))

    async def fittings(
        self, character: str, ship_type_id: int | None = None, limit: int = 100
    ) -> dict[str, Any]:
        bounded_limit = min(max(limit, 1), 100)
        result = await self.endpoints.fittings(
            self._id(character), 1000 if ship_type_id is not None else bounded_limit
        )
        if ship_type_id is not None:
            filtered = [
                item for item in result["items"] if item.get("ship_type_id") == ship_type_id
            ]
            result["items"] = filtered[:bounded_limit]
            result["returned_count"] = len(result["items"])
            source_truncated = result.get("truncated", False)
            result["total_available"] = len(filtered) if not source_truncated else None
            result["truncated"] = source_truncated or len(filtered) > bounded_limit
            result["next_page"] = None
        return result

    def search_fitting_types(
        self, query: str, kind: str | None = None, limit: int = 20
    ) -> dict[str, Any]:
        if kind is not None and kind not in {"hull", "module", "charge", "drone", "rig"}:
            raise ValueError("kind must be hull, module, charge, drone, rig, or null")
        catalog = self._catalog()
        if catalog is None:
            return self._static_data_unavailable()
        results = catalog.search(query, kind, min(max(limit, 1), 50))
        return {
            "status": "ok",
            "catalog_version": catalog.version,
            "returned_count": len(results),
            "items": [self._type_summary(item) for item in results],
        }

    async def fitting_context(
        self, character: str, hull_type_id: int | None = None
    ) -> dict[str, Any]:
        character_id = self._id(character)
        catalog = self._catalog()
        if catalog is None:
            return self._static_data_unavailable()
        character_data = await self.endpoints.character(character_id)
        skills_response = await self.endpoints.skills(character_id)
        skills = [
            {
                "skill_id": item["skill_id"],
                "level": item.get("active_skill_level", item.get("trained_skill_level", 0)),
            }
            for item in extract_skill_rows(skills_response)
            if isinstance(item.get("skill_id"), int)
        ]
        hull = catalog.get_type(hull_type_id) if hull_type_id is not None else None
        if hull_type_id is not None and hull is None:
            return {
                "status": "incomplete",
                "reason": "unknown_hull_type",
                "hull_type_id": hull_type_id,
                "catalog_version": catalog.version,
                "character_id": character_id,
            }
        return {
            "status": "ok",
            "character_id": character_id,
            "character_name": character_data["items"][0].get("name"),
            "skills": skills,
            "hull": self._type_summary(hull) if hull else None,
            "catalog_version": catalog.version,
            "limitations": [
                "No live ship state, market price, route, or combat effectiveness is measured."
            ],
        }

    async def validate_fitting(
        self,
        character: str,
        fitting: dict[str, Any],
        include_asset_check: bool = True,
    ) -> dict[str, Any]:
        character_id = self._id(character)
        catalog = self._catalog()
        if catalog is None:
            return self._static_data_unavailable()
        submitted = Fitting(
            name=fitting["name"],
            description=fitting.get("description", ""),
            ship_type_id=fitting["ship_type_id"],
            items=tuple(
                FittingItem(item["type_id"], item["flag"], item["quantity"])
                for item in fitting["items"]
            ),
        )
        type_ids = {submitted.ship_type_id, *(item.type_id for item in submitted.items)}
        facts = {type_id: fact for type_id in type_ids if (fact := catalog.get_type(type_id))}
        skill_response = await self.endpoints.skills(character_id)
        trained_skills = trained_skill_levels(skill_response)
        validation = validate_fitting(submitted, facts, trained_skills)
        result: dict[str, Any] = {
            "status": validation["status"],
            "character_id": character_id,
            "character_name": self.profiles.resolve(character_id).character_name,
            "catalog_version": catalog.version,
            "fitting": submitted.to_dict(),
            "validation": validation,
            "eft_export": self._eft_export(submitted, catalog),
        }
        if validation["status"] != "valid":
            return result
        proposal = create_proposal(
            character_id=character_id,
            catalog_version=catalog.version,
            name=submitted.name,
            description=submitted.description,
            ship_type_id=submitted.ship_type_id,
            items=[item.to_dict() for item in submitted.items],
        )
        result["proposal"] = proposal.to_dict()
        if include_asset_check:
            asset_response = await self.endpoints.assets(
                character_id, limit=1000, include_nested=True
            )
            inventory_truncated = asset_response.get("truncated", False)
            quantities: Counter[int] = Counter()
            for asset in asset_response["items"]:
                if isinstance(asset, dict) and isinstance(asset.get("type_id"), int):
                    quantities[asset["type_id"]] += int(asset.get("quantity", 1))
            result["asset_availability"] = [
                {
                    "type_id": item.type_id,
                    "required_quantity": item.quantity,
                    "reported_quantity": quantities[item.type_id],
                    "sufficient": (
                        None if inventory_truncated else quantities[item.type_id] >= item.quantity
                    ),
                }
                for item in submitted.items
            ]
            result["asset_inventory_truncated"] = inventory_truncated
            result["asset_caveat"] = (
                "ESI asset quantities do not guarantee access, location, or fitting availability; "
                "an incomplete inventory cannot establish absence."
            )
        return result

    async def create_fitting(
        self,
        character: str,
        proposal: dict[str, Any],
        proposal_id: str,
        confirm_create: bool,
    ) -> dict[str, Any]:
        if self.fitting_writer is None:
            return self._static_data_unavailable()
        return await self.fitting_writer.create(character, proposal, proposal_id, confirm_create)

    def _catalog(self) -> StaticCatalog | None:
        if self.catalog_provider is None:
            return None
        try:
            return self.catalog_provider()
        except FileNotFoundError:
            return None

    @staticmethod
    def _static_data_unavailable() -> dict[str, str]:
        return {
            "status": "static_data_unavailable",
            "recovery": "Run eve-mcp static-data refresh to install the official CCP SDE catalog.",
        }

    @staticmethod
    def _type_summary(item: StaticType) -> dict[str, Any]:
        return {
            "type_id": item.type_id,
            "name": item.name,
            "kind": item.kind,
            "group": item.group,
            "slot_class": item.slot_class,
            "cpu": item.cpu,
            "powergrid": item.powergrid,
            "calibration": item.calibration,
            "slots": item.slots,
            "required_skills": item.required_skills,
        }

    @staticmethod
    def _eft_export(fitting: Fitting, catalog: StaticCatalog) -> str | None:
        hull = catalog.get_type(fitting.ship_type_id)
        modules = [catalog.get_type(item.type_id) for item in fitting.items]
        if hull is None or any(item is None for item in modules):
            return None
        lines = [f"[{hull.name}, {fitting.name}]"]
        lines.extend(
            f"{item.name}" + (f" x{fitting_item.quantity}" if fitting_item.quantity > 1 else "")
            for fitting_item, item in zip(fitting.items, modules, strict=True)
            if item is not None
        )
        return "\n".join(lines)

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
