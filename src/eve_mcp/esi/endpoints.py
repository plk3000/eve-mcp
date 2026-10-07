"""Normalized read-only selected-v1 ESI endpoint adapters."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import urlencode

from eve_mcp.esi.client import EsiClient, EsiResponse


class AccessTokenProvider(Protocol):
    """Retrieves an access token for only the selected immutable character ID."""

    async def get_access_token(self, character_id: str) -> str: ...


class EsiCharacterEndpoints:
    """Production adapter for the selected, authenticated read-only ESI routes."""

    def __init__(self, client: EsiClient, tokens: AccessTokenProvider) -> None:
        self.client = client
        self.tokens = tokens

    async def character(self, character_id: str) -> dict[str, Any]:
        return self._envelope(
            character_id, await self._get(character_id, f"characters/{character_id}/")
        )

    async def skills(self, character_id: str) -> dict[str, Any]:
        return self._envelope(
            character_id, await self._get(character_id, f"characters/{character_id}/skills/")
        )

    async def skill_queue(self, character_id: str, limit: int = 50) -> dict[str, Any]:
        return await self._paged(character_id, f"characters/{character_id}/skillqueue/", limit)

    async def assets(
        self,
        character_id: str,
        limit: int = 250,
        location_id: int | None = None,
        type_id: int | None = None,
        include_nested: bool = False,
    ) -> dict[str, Any]:
        filters_applied = location_id is not None or type_id is not None or not include_nested
        # Fetch available pages before filtering so the result never falsely claims that
        # a matching asset does not exist merely because it was later in ESI's response.
        result = await self._paged(
            character_id, f"characters/{character_id}/assets/", 1000 if filters_applied else limit
        )
        items = result["items"]
        filtered = [
            item
            for item in items
            if (location_id is None or item.get("location_id") == location_id)
            and (type_id is None or item.get("type_id") == type_id)
            and (
                include_nested
                or item.get("location_flag") not in {"AutoFit", "Cargo", "DroneBay", "FighterBay"}
            )
        ]
        result["items"] = filtered[:limit]
        result["returned_count"] = len(result["items"])
        if len(filtered) > limit:
            result["truncated"] = True
            result["next_page"] = None
        # Filtering means ESI's raw total cannot truthfully describe the filtered set.
        if filters_applied:
            result["total_available"] = None
            if result["next_page"] is None and len(filtered) <= limit:
                result["truncated"] = False
        return result

    async def mining_ledger(
        self, character_id: str, limit: int = 250, days: int = 30
    ) -> dict[str, Any]:
        bounded_days = min(max(days, 1), 365)
        start = (datetime.now(UTC).date() - timedelta(days=bounded_days)).isoformat()
        path = f"characters/{character_id}/mining/?{urlencode({'from_date': start})}"
        return await self._paged(character_id, path, limit)

    async def industry_jobs(
        self, character_id: str, limit: int = 100, include_completed: bool = False
    ) -> dict[str, Any]:
        value = "true" if include_completed else "false"
        return await self._paged(
            character_id,
            f"characters/{character_id}/industry/jobs/?include_completed={value}",
            limit,
        )

    async def blueprints(self, character_id: str, limit: int = 250) -> dict[str, Any]:
        return await self._paged(character_id, f"characters/{character_id}/blueprints/", limit)

    async def wallet_transactions(
        self, character_id: str, limit: int = 250, days: int = 30
    ) -> dict[str, Any]:
        result = await self._paged(
            character_id, f"characters/{character_id}/wallet/transactions/", 1000
        )
        cutoff = datetime.now(UTC) - timedelta(days=min(max(days, 1), 90))
        filtered = [
            item for item in result["items"] if self._is_on_or_after(item.get("date"), cutoff)
        ]
        return self._filtered(result, filtered, limit)

    async def market_orders(
        self, character_id: str, limit: int = 250, state: str = "active"
    ) -> dict[str, Any]:
        if state == "active":
            return await self._paged(character_id, f"characters/{character_id}/orders/", limit)
        result = await self._paged(character_id, f"characters/{character_id}/orders/history/", 1000)
        filtered = [item for item in result["items"] if item.get("state") == state]
        return self._filtered(result, filtered, limit)

    async def _get(self, character_id: str, path: str) -> EsiResponse:
        return await self.client.get_response(
            path,
            character_id=character_id,
            access_token=await self.tokens.get_access_token(character_id),
        )

    async def _paged(self, character_id: str, base_path: str, limit: int) -> dict[str, Any]:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        first = await self._get(character_id, self._page_path(base_path, 1))
        first_items = self._items(first.payload)
        pages = first.total_pages or 1
        items = list(first_items)
        for page in range(2, pages + 1):
            if len(items) >= limit:
                break
            response = await self._get(character_id, self._page_path(base_path, page))
            items.extend(self._items(response.payload))
        bounded = items[:limit]
        more_pages = (
            pages
            if len(items) < limit
            else min(pages, (len(bounded) // max(len(first_items), 1)) + 1)
        )
        return {
            "character_id": character_id,
            "items": bounded,
            "as_of": datetime.now(UTC).isoformat(),
            "cache_expires_at": first.expires_at.isoformat(),
            "returned_count": len(bounded),
            "total_available": None if pages > 1 else len(items),
            "truncated": len(items) > len(bounded) or pages > 1 and len(items) < limit,
            "next_page": more_pages
            if len(items) > len(bounded) or pages > 1 and len(items) < limit
            else None,
        }

    @staticmethod
    def _page_path(path: str, page: int) -> str:
        separator = "&" if "?" in path else "?"
        return f"{path}{separator}page={page}"

    @staticmethod
    def _items(payload: Any) -> list[dict[str, Any]]:
        if not isinstance(payload, list):
            raise ValueError(
                "ESI returned an unexpected non-list payload for a collection endpoint."
            )
        return [item for item in payload if isinstance(item, dict)]

    @staticmethod
    def _is_on_or_after(value: Any, cutoff: datetime) -> bool:
        if not isinstance(value, str):
            return False
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")) >= cutoff
        except ValueError:
            return False

    @staticmethod
    def _filtered(
        result: dict[str, Any], items: list[dict[str, Any]], limit: int
    ) -> dict[str, Any]:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        result["items"] = items[:limit]
        result["returned_count"] = len(result["items"])
        result["total_available"] = None
        result["truncated"] = len(items) > limit or bool(result["next_page"])
        if len(items) <= limit:
            result["next_page"] = None
        return result

    @staticmethod
    def _envelope(character_id: str, response: EsiResponse) -> dict[str, Any]:
        items = response.payload if isinstance(response.payload, list) else [response.payload]
        return {
            "character_id": character_id,
            "items": items,
            "as_of": datetime.now(UTC).isoformat(),
            "cache_expires_at": response.expires_at.isoformat(),
            "returned_count": len(items),
            "total_available": len(items),
            "truncated": False,
            "next_page": None,
        }


class FixtureCharacterEndpoints:
    """Fixture-only test double; never the production server default."""

    def __init__(self, data: Mapping[str, Mapping[str, Any]]) -> None:
        self._data = data

    async def character(self, character_id: str) -> dict[str, Any]:
        return self._response(character_id, "character")

    async def skills(self, character_id: str) -> dict[str, Any]:
        return self._response(character_id, "skills")

    async def skill_queue(self, character_id: str, limit: int = 50) -> dict[str, Any]:
        return self._bounded(character_id, "skill_queue", limit)

    async def assets(self, character_id: str, limit: int = 250, **_: Any) -> dict[str, Any]:
        return self._bounded(character_id, "assets", limit)

    async def mining_ledger(self, character_id: str, limit: int = 250, **_: Any) -> dict[str, Any]:
        return self._bounded(character_id, "mining_ledger", limit)

    async def industry_jobs(self, character_id: str, limit: int = 100, **_: Any) -> dict[str, Any]:
        return self._bounded(character_id, "industry_jobs", limit)

    async def blueprints(self, character_id: str, limit: int = 250) -> dict[str, Any]:
        return self._bounded(character_id, "blueprints", limit)

    async def wallet_transactions(
        self, character_id: str, limit: int = 250, days: int = 30
    ) -> dict[str, Any]:
        cutoff = datetime.now(UTC) - timedelta(days=min(max(days, 1), 90))
        items = [
            item
            for item in self._data.get(character_id, {}).get("wallet_transactions", [])
            if EsiCharacterEndpoints._is_on_or_after(item.get("date"), cutoff)
        ]
        return self._envelope(character_id, items[:limit], len(items))

    async def market_orders(
        self, character_id: str, limit: int = 250, state: str | None = None
    ) -> dict[str, Any]:
        items = self._data.get(character_id, {}).get("market_orders", [])
        filtered = [item for item in items if state is None or item.get("state") == state]
        return self._envelope(character_id, filtered[:limit], len(filtered))

    def _response(self, character_id: str, key: str) -> dict[str, Any]:
        record = self._data.get(character_id, {}).get(key, {})
        items = record if isinstance(record, list) else record.get("items", record)
        return self._envelope(character_id, items if isinstance(items, list) else [items])

    def _bounded(self, character_id: str, key: str, limit: int) -> dict[str, Any]:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        items = self._data.get(character_id, {}).get(key, [])
        return self._envelope(character_id, list(items)[:limit], len(items))

    @staticmethod
    def _envelope(character_id: str, items: list[Any], total: int | None = None) -> dict[str, Any]:
        now = datetime.now(UTC).isoformat()
        return {
            "character_id": character_id,
            "items": items,
            "as_of": now,
            "cache_expires_at": now,
            "returned_count": len(items),
            "total_available": len(items) if total is None else total,
            "truncated": len(items) < (len(items) if total is None else total),
            "next_page": None,
        }
