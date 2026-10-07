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
            headers={"User-Agent": "eve-mcp/0.1 (self-hosted MCP)"},
        )
        self.cache: dict[tuple[str | None, str], CacheEntry] = {}

    async def get(
        self, path: str, character_id: str | None = None, access_token: str | None = None
    ) -> Any:
        """Return only payload for small consumers; adapters use ``get_response``."""
        return (await self.get_response(path, character_id, access_token)).payload

    async def get_response(
        self,
        path: str,
        character_id: str | None = None,
        access_token: str | None = None,
        *,
        use_cache: bool = True,
        bearer_auth: bool = False,
    ) -> EsiResponse:
        key = (character_id, path)
        cached = self.cache.get(key) if use_cache else None
        now = datetime.now(UTC)
        if cached and cached.expires_at > now:
            return EsiResponse(cached.payload, cached.expires_at, cached.total_pages)
        headers: dict[str, str] = {}
        if cached and cached.etag:
            headers["If-None-Match"] = cached.etag
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        if access_token and bearer_auth:
            headers["Authorization"] = "Bearer " + access_token
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
        payload = response.json()
        if use_cache:
            self.cache[key] = CacheEntry(
                payload, response.headers.get("ETag"), expires_at, total_pages
            )
        return EsiResponse(payload, expires_at, total_pages)

    async def post_fitting(
        self, character_id: str, fitting: dict[str, Any], access_token: str
    ) -> Any:
        """Create one new saved fitting at the fixed character fitting endpoint."""
        path = f"characters/{character_id}/fittings/"
        try:
            response = await self.client.post(
                path,
                json=fitting,
                headers={"Authorization": "Bearer " + access_token},
            )
        except httpx.TimeoutException as error:
            raise EsiError(
                "Fitting creation outcome is unknown after a request timeout."
            ) from error
        except httpx.HTTPError as error:
            raise EsiError(
                "Fitting creation outcome is unknown after a transport failure."
            ) from error
        if response.status_code in {401, 403}:
            raise EsiScopeError(
                "ESI denied fitting creation. Reauthorize this character with the fitting "
                "write scope."
            )
        if response.is_error:
            raise EsiHttpError(f"ESI returned HTTP {response.status_code} for fitting creation.")
        try:
            return response.json()
        except ValueError:
            return None

    def invalidate(self, character_id: str, path: str) -> None:
        """Invalidate one character's exact cached ESI representation."""
        self.cache.pop((character_id, path), None)

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
