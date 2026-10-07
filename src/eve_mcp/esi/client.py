"""Cache-aware async ESI HTTP client with safe error normalization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any

import httpx


class EsiError(RuntimeError):
    """Safe ESI failure; never includes bodies or credentials."""


class EsiScopeError(EsiError):
    """The selected character did not grant an endpoint's required scope."""


class EsiHttpError(EsiError):
    """An upstream ESI request failed."""


@dataclass
class CacheEntry:
    payload: Any
    etag: str | None
    expires_at: datetime
    total_pages: int | None


@dataclass(frozen=True)
class EsiResponse:
    """Payload plus safe HTTP metadata required by endpoint adapters."""

    payload: Any
    expires_at: datetime
    total_pages: int | None


class EsiClient:
    """Injectable ESI client whose cache is isolated by character and URL."""

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.client = httpx.AsyncClient(
            base_url="https://esi.evetech.net/latest/",
            transport=transport,
            timeout=httpx.Timeout(20.0),
            headers={"User-Agent": "eve-mcp/0.1 (self-hosted read-only MCP)"},
        )
        self.cache: dict[tuple[str | None, str], CacheEntry] = {}

    async def get(
        self, path: str, character_id: str | None = None, access_token: str | None = None
    ) -> Any:
        """Return only payload for small consumers; adapters use ``get_response``."""
        return (await self.get_response(path, character_id, access_token)).payload

    async def get_response(
        self, path: str, character_id: str | None = None, access_token: str | None = None
    ) -> EsiResponse:
        key = (character_id, path)
        cached = self.cache.get(key)
        now = datetime.now(UTC)
        if cached and cached.expires_at > now:
            return EsiResponse(cached.payload, cached.expires_at, cached.total_pages)
        headers: dict[str, str] = {}
        if cached and cached.etag:
            headers["If-None-Match"] = cached.etag
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        try:
            response = await self.client.get(path, headers=headers)
        except httpx.TimeoutException as error:
            raise EsiError("ESI request timed out; retry after a short delay.") from error
        except httpx.HTTPError as error:
            raise EsiError("ESI request failed before receiving a response.") from error
        if response.status_code == 304 and cached:
            cached.expires_at = self._expiry(response, now)
            return EsiResponse(cached.payload, cached.expires_at, cached.total_pages)
        if response.status_code in {401, 403}:
            raise EsiScopeError(
                "ESI denied this request. Reauthorize this character with the required scope."
            )
        if response.is_error:
            raise EsiHttpError(f"ESI returned HTTP {response.status_code}; retry later.")
        expires_at = self._expiry(response, now)
        total_pages = self._page_count(response)
        self.cache[key] = CacheEntry(
            response.json(), response.headers.get("ETag"), expires_at, total_pages
        )
        return EsiResponse(response.json(), expires_at, total_pages)

    @staticmethod
    def _page_count(response: httpx.Response) -> int | None:
        value = response.headers.get("X-Pages")
        try:
            return max(1, int(value)) if value is not None else None
        except ValueError:
            return None

    @staticmethod
    def _expiry(response: httpx.Response, now: datetime) -> datetime:
        value = response.headers.get("Expires")
        if value:
            try:
                expires_at = parsedate_to_datetime(value)
                return expires_at.astimezone(UTC)
            except (TypeError, ValueError):
                pass
        return now + timedelta(minutes=5)

    async def aclose(self) -> None:
        await self.client.aclose()
