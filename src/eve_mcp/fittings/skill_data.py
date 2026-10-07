"""Normalize the two supported character-skill response envelopes."""

from __future__ import annotations

from typing import Any


def extract_skill_rows(response: dict[str, Any]) -> list[dict[str, Any]]:
    """Return ESI skill rows from production or fixture endpoint envelopes."""
    items = response.get("items")
    if not isinstance(items, list):
        return []
    if len(items) == 1 and isinstance(items[0], dict):
        nested = items[0].get("skills")
        if isinstance(nested, list):
            return [item for item in nested if isinstance(item, dict)]
    return [item for item in items if isinstance(item, dict) and "skill_id" in item]
