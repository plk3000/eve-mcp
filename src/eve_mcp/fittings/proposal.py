"""Canonical, character-bound proposal hashing."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from eve_mcp.fittings.models import Fitting, FittingItem

PROPOSAL_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class FittingProposal:
    character_id: str
    catalog_version: str
    fitting: Fitting
    proposal_id: str

    def require_character(self, character_id: str) -> None:
        if self.character_id != character_id:
            raise ValueError("proposal character does not match the selected character")

    def fitting_dict(self) -> dict[str, object]:
        return self.fitting.to_dict()

    def to_dict(self) -> dict[str, object]:
        return {
            "proposal_schema_version": PROPOSAL_SCHEMA_VERSION,
            "proposal_id": self.proposal_id,
            "character_id": self.character_id,
            "catalog_version": self.catalog_version,
            "fitting": self.fitting_dict(),
        }


def create_proposal(
    *,
    character_id: str,
    catalog_version: str,
    name: str,
    description: str,
    ship_type_id: int,
    items: list[dict[str, Any]],
) -> FittingProposal:
    if not character_id or not catalog_version:
        raise ValueError("character_id and catalog_version are required")
    if not isinstance(items, list):
        raise ValueError("items must be a list")
    if not isinstance(name, str) or not isinstance(description, str):
        raise ValueError("name and description must be strings")
    fitting_items: list[FittingItem] = []
    for item in items:
        if not isinstance(item, dict) or set(item) != {"type_id", "flag", "quantity"}:
            raise ValueError("each item must contain only type_id, flag, and quantity")
        type_id = item["type_id"]
        flag = item["flag"]
        quantity = item["quantity"]
        if type(type_id) is not int or not isinstance(flag, str) or type(quantity) is not int:
            raise ValueError(
                "each item must contain an integer type_id and quantity and a string flag"
            )
        fitting_items.append(FittingItem(type_id, flag, quantity))
    fitting = Fitting(
        name=name,
        description=description,
        ship_type_id=ship_type_id,
        items=tuple(sorted(fitting_items)),
    )
    canonical = {
        "proposal_schema_version": PROPOSAL_SCHEMA_VERSION,
        "character_id": character_id,
        "catalog_version": catalog_version,
        "fitting": fitting.to_dict(),
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    proposal_id = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return FittingProposal(character_id, catalog_version, fitting, proposal_id)
