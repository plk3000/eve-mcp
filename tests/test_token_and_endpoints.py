import asyncio


def test_in_memory_token_store_is_per_character_and_does_not_echo_secret() -> None:
    from eve_mcp.auth.token_store import InMemoryTokenStore, MissingTokenError

    store = InMemoryTokenStore()
    store.put("100", "alpha-secret")
    store.put("200", "beta-secret")
    assert store.get("100") == "alpha-secret"
    store.delete("100")
    assert store.get("200") == "beta-secret"
    try:
        store.get("100")
    except MissingTokenError as exc:
        assert "alpha-secret" not in str(exc)


def test_fixture_endpoint_adapter_is_character_isolated() -> None:
    from eve_mcp.esi.endpoints import FixtureCharacterEndpoints

    endpoints = FixtureCharacterEndpoints(
        {"100": {"skills": [{"skill_id": 1, "active_skill_level": 5}]}}
    )
    assert asyncio.run(endpoints.skills("100"))["items"][0]["skill_id"] == 1
