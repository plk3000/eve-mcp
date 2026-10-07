from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from typer.testing import CliRunner

from eve_mcp.auth.pkce import SCOPES, build_authorization_url, new_pkce_pair
from eve_mcp.auth.sso import SsoClient, SsoWorkflow, StateMismatchError
from eve_mcp.auth.token_store import InMemoryTokenStore
from eve_mcp.profiles import ProfileRepository


@pytest.mark.asyncio
async def test_sso_mock_exchange_verifies_identity_and_stores_only_selected_profile(
    tmp_path,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/token"):
            return httpx.Response(
                200,
                json={
                    "access_token": "short-lived",
                    "refresh_token": "refresh-only",
                    "expires_in": 1200,
                },
            )
        if request.url.path.endswith("/verify"):
            assert request.headers["authorization"] == "Bearer short-lived"
            return httpx.Response(
                200, json={"CharacterID": 100, "CharacterName": "Alice", "Scopes": " ".join(SCOPES)}
            )
        raise AssertionError(request.url)

    profiles = ProfileRepository(tmp_path / "profiles.db")
    secrets = InMemoryTokenStore()
    workflow = SsoWorkflow(
        SsoClient("client", "http://127.0.0.1:8080/callback", httpx.MockTransport(handler)),
        profiles,
        secrets,
    )
    transaction = workflow.begin()
    profile = await workflow.complete(transaction, {"code": "one-time", "state": transaction.state})

    assert profile.character_id == "100"
    assert secrets.get("100") == "refresh-only"
    assert profiles.resolve("Alice").granted_scopes == SCOPES
    assert len(requests) == 2


def test_pkce_is_random_and_authorization_url_has_exact_readonly_scopes() -> None:
    first, second = new_pkce_pair(), new_pkce_pair()
    assert first.verifier != second.verifier
    url = build_authorization_url("client", "http://127.0.0.1:8080/callback", first)
    assert "code_challenge=" in url
    assert "esi-assets.read_assets.v1" in url
    assert "openid" not in url
    assert "esi-characters.read_blueprints.v1" in url
    assert "esi-wallet.read_character_wallet.v1" in url
    assert "esi-markets.read_character_orders.v1" in url
    assert "corporation" not in url


@pytest.mark.asyncio
async def test_state_mismatch_never_exchanges_or_writes(tmp_path) -> None:
    profiles = ProfileRepository(tmp_path / "profiles.db")
    secrets = InMemoryTokenStore()
    workflow = SsoWorkflow(SsoClient("client", "http://127.0.0.1/callback"), profiles, secrets)
    transaction = workflow.begin()
    with pytest.raises(StateMismatchError):
        await workflow.complete(transaction, {"code": "nope", "state": "wrong"})
    assert profiles.list() == []


def test_settings_accepts_explicit_loopback_callback_with_port(monkeypatch) -> None:
    monkeypatch.setenv("EVE_MCP_CLIENT_ID", "client")
    monkeypatch.setenv("EVE_MCP_REDIRECT_URI", "http://127.0.0.1:8080/callback")

    from eve_mcp.config import Settings

    assert Settings.from_environment().require_sso_configuration() == (
        "client",
        "http://127.0.0.1:8080/callback",
    )


def test_auth_cli_requires_self_hosted_configuration_and_lists_safe_profiles(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("EVE_MCP_DATA_DIR", str(tmp_path))
    from eve_mcp.cli import app

    runner = CliRunner()
    missing = runner.invoke(app, ["auth", "add"])
    assert missing.exit_code != 0
    assert "EVE_MCP_CLIENT_ID" in missing.stdout
    assert "esi-industry.read_character_mining.v1" in missing.stdout

    profiles = ProfileRepository(tmp_path / "eve-mcp.db")
    profiles.upsert("100", "Alice", ["openid"], datetime.now(UTC), "authorized")
    listed = runner.invoke(app, ["auth", "list"])
    assert listed.exit_code == 0
    assert "Alice" in listed.stdout
    disabled = runner.invoke(app, ["auth", "disable", "Alice"])
    assert disabled.exit_code == 0
    assert profiles.resolve_including_disabled("100").enabled is False
