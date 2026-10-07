from __future__ import annotations

from pathlib import Path


def test_fitting_scopes_and_create_only_documentation_are_explicit() -> None:
    from eve_mcp.auth.pkce import SCOPES

    root = Path(__file__).parents[1]
    assert "esi-fittings.read_fittings.v1" in SCOPES
    assert "esi-fittings.write_fittings.v1" in SCOPES
    assert not any("corporation" in scope or "fleet" in scope for scope in SCOPES)
    docs = (root / "docs" / "fittings.md").read_text()
    assert "never updates or deletes" in docs
    assert "readback" in docs.lower()
    assert "name conflict" in docs.lower()
    assert "unknown" in docs.lower()


def test_production_fitting_write_has_only_the_fixed_create_route() -> None:
    root = Path(__file__).parents[1] / "src" / "eve_mcp"
    source = "\n".join(path.read_text() for path in root.rglob("*.py"))
    client = (root / "esi" / "client.py").read_text()
    assert "characters/{character_id}/fittings/" in client
    assert "delete_fitting" not in source
    assert "update_fitting" not in source
    assert "replace_fitting" not in source
    assert "self.client.delete(" not in client
    assert "self.client.put(" not in client
    assert "self.client.patch(" not in client
