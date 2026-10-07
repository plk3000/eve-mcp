from datetime import UTC, datetime

import pytest


def test_profiles_are_isolated_resolved_and_disabled(tmp_path) -> None:
    from eve_mcp.profiles import DisabledProfileError, ProfileRepository

    repo = ProfileRepository(tmp_path / "profiles.sqlite")
    repo.upsert("100", "Alice", ["scope.a"], datetime.now(UTC), "ok")
    repo.upsert("200", "Bob", ["scope.b"], datetime.now(UTC), "ok")
    assert repo.resolve("Alice").character_id == "100"
    assert repo.resolve("200").character_name == "Bob"
    repo.set_enabled("100", False)
    with pytest.raises(DisabledProfileError):
        repo.resolve("100")
    assert repo.resolve("200").character_id == "200"
    assert "token" not in repo.schema_columns()


def test_duplicate_display_names_are_ambiguous(tmp_path) -> None:
    from eve_mcp.profiles import AmbiguousProfileError, ProfileRepository

    repo = ProfileRepository(tmp_path / "profiles.sqlite")
    for identifier in ("100", "200"):
        repo.upsert(identifier, "Twin", [], None, "ok")
    with pytest.raises(AmbiguousProfileError):
        repo.resolve("Twin")
