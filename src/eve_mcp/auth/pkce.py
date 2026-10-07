"""PKCE and the deliberately small selected-v1 OAuth scope contract."""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

SSO_AUTHORIZE_URL = "https://login.eveonline.com/v2/oauth/authorize"
SCOPES = (
    "esi-skills.read_skills.v1",
    "esi-skills.read_skillqueue.v1",
    "esi-assets.read_assets.v1",
    "esi-industry.read_character_jobs.v1",
    "esi-industry.read_character_mining.v1",
    "esi-characters.read_blueprints.v1",
    "esi-wallet.read_character_wallet.v1",
    "esi-markets.read_character_orders.v1",
)


@dataclass(frozen=True)
class PkcePair:
    verifier: str
    challenge: str
    state: str


def new_pkce_pair() -> PkcePair:
    """Create independent high-entropy verifier and CSRF state values."""
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    return PkcePair(verifier=verifier, challenge=challenge, state=secrets.token_urlsafe(32))


def build_authorization_url(client_id: str, redirect_uri: str, pair: PkcePair) -> str:
    """Build but never open the official authorization URL."""
    query = urlencode(
        {
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "scope": " ".join(SCOPES),
            "state": pair.state,
            "code_challenge": pair.challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"{SSO_AUTHORIZE_URL}?{query}"
