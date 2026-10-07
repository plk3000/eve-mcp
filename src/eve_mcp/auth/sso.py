"""Testable EVE SSO exchange and identity-validation workflow.

No MCP tool invokes this module.  The operator-only CLI may invoke it after a
human has configured their own CCP application and completed consent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from eve_mcp.config import Settings

import httpx

from eve_mcp.auth.pkce import SCOPES, PkcePair, build_authorization_url, new_pkce_pair
from eve_mcp.auth.token_store import TokenStore
from eve_mcp.profiles import Profile, ProfileRepository

TOKEN_URL = "https://login.eveonline.com/v2/oauth/token"
VERIFY_URL = "https://login.eveonline.com/oauth/verify"


class SsoError(RuntimeError):
    """Safe SSO error without raw callback/query/token content."""


class StateMismatchError(SsoError):
    """Callback CSRF state differs from the transaction state."""


@dataclass(frozen=True)
class AuthorizationTransaction:
    pair: PkcePair
    authorization_url: str

    @property
    def state(self) -> str:
        return self.pair.state


@dataclass(frozen=True)
class TokenGrant:
    access_token: str
    refresh_token: str
    expires_at: datetime


@dataclass(frozen=True)
class VerifiedCharacter:
    character_id: str
    character_name: str
    scopes: tuple[str, ...]


class SsoClient:
    """Official endpoints with injectable transport for offline tests."""

    def __init__(
        self, client_id: str, redirect_uri: str, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.client_id = client_id
        self.redirect_uri = redirect_uri
        self._client = httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(20.0))

    async def exchange_code(self, code: str, verifier: str) -> TokenGrant:
        return await self._grant(
            {
                "grant_type": "authorization_code",
                "code": code,
                "client_id": self.client_id,
                "redirect_uri": self.redirect_uri,
                "code_verifier": verifier,
            }
        )

    async def refresh_access_token(self, refresh_token: str) -> TokenGrant:
        return await self._grant(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self.client_id,
            }
        )

    async def _grant(self, body: dict[str, str]) -> TokenGrant:
        try:
            response = await self._client.post(TOKEN_URL, data=body)
            response.raise_for_status()
            payload = response.json()
            return TokenGrant(
                access_token=str(payload["access_token"]),
                refresh_token=str(payload["refresh_token"]),
                expires_at=datetime.now(UTC)
                + timedelta(seconds=int(payload.get("expires_in", 1200))),
            )
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            raise SsoError(
                "SSO token exchange failed; retry authorization from the CLI."
            ) from error

    async def verify_identity(self, access_token: str) -> VerifiedCharacter:
        try:
            response = await self._client.get(
                VERIFY_URL, headers={"Authorization": f"Bearer {access_token}"}
            )
            response.raise_for_status()
            payload = response.json()
            character_id = str(payload["CharacterID"])
            character_name = str(payload["CharacterName"])
            scopes = tuple(str(payload.get("Scopes", "")).split())
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            raise SsoError("SSO identity verification failed; no profile was changed.") from error
        if not character_id.isdigit() or not character_name or not set(SCOPES).issubset(scopes):
            raise SsoError(
                "SSO identity did not grant the selected v1 scopes; no profile was changed."
            )
        return VerifiedCharacter(character_id, character_name, scopes)

    async def aclose(self) -> None:
        await self._client.aclose()


class RefreshingAccessTokenProvider:
    """Retrieves and rotates only one character's keyring refresh token on demand."""

    def __init__(self, settings: Settings, secrets: TokenStore) -> None:
        self.settings, self.secrets = settings, secrets

    async def get_access_token(self, character_id: str) -> str:
        client_id, redirect_uri = self.settings.require_sso_configuration()
        client = SsoClient(client_id, redirect_uri)
        try:
            grant = await client.refresh_access_token(self.secrets.get(character_id))
            self.secrets.put(character_id, grant.refresh_token)
            return grant.access_token
        finally:
            await client.aclose()


class SsoWorkflow:
    """Separates callback validation from the only subsequent metadata/secret writes."""

    def __init__(self, sso: SsoClient, profiles: ProfileRepository, secrets: TokenStore) -> None:
        self.sso, self.profiles, self.secrets = sso, profiles, secrets

    def begin(self) -> AuthorizationTransaction:
        pair = new_pkce_pair()
        return AuthorizationTransaction(
            pair, build_authorization_url(self.sso.client_id, self.sso.redirect_uri, pair)
        )

    async def complete(
        self, transaction: AuthorizationTransaction, callback: dict[str, str]
    ) -> Profile:
        if callback.get("state") != transaction.state:
            raise StateMismatchError(
                "Authorization callback state did not match; no profile was changed."
            )
        if "error" in callback or not callback.get("code"):
            raise SsoError(
                "Authorization was cancelled or did not return a code; no profile was changed."
            )
        grant = await self.sso.exchange_code(callback["code"], transaction.pair.verifier)
        identity = await self.sso.verify_identity(grant.access_token)
        self.secrets.put(identity.character_id, grant.refresh_token)
        self.profiles.upsert(
            identity.character_id,
            identity.character_name,
            list(identity.scopes),
            grant.expires_at,
            "authorized",
        )
        return self.profiles.resolve(identity.character_id)
