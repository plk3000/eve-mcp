"""Narrow create-only saved-fitting action with conservative retry reconciliation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any, Protocol

import httpx

from eve_mcp.esi.client import EsiError
from eve_mcp.fittings.creation_ledger import CreationLedger
from eve_mcp.fittings.models import Fitting, FittingItem
from eve_mcp.fittings.proposal import PROPOSAL_SCHEMA_VERSION, create_proposal
from eve_mcp.fittings.validation import trained_skill_levels, validate_fitting
from eve_mcp.profiles import ProfileRepository
from eve_mcp.static_data.catalog import StaticCatalog


class FittingWriteEndpoints(Protocol):
    async def skills(self, character_id: str) -> dict[str, Any]: ...
    async def fittings(
        self, character_id: str, limit: int = 100, fresh: bool = False
    ) -> dict[str, Any]: ...
    async def create_fitting(self, character_id: str, fitting: dict[str, Any]) -> Any: ...


class FittingWriter:
    def __init__(
        self,
        profiles: ProfileRepository,
        endpoints: FittingWriteEndpoints,
        catalog_provider: Callable[[str | None], StaticCatalog],
        ledger: CreationLedger,
    ) -> None:
        self.profiles = profiles
        self.endpoints = endpoints
        self.catalog_provider = catalog_provider
        self.ledger = ledger

    async def create(
        self,
        character: str,
        proposal_payload: dict[str, Any],
        proposal_id: str,
        confirm_create: bool,
    ) -> dict[str, Any]:
        if confirm_create is not True:
            return {"status": "confirmation_required"}
        profile = self.profiles.resolve(character)
        character_id = profile.character_id
        if not _REQUIRED_SCOPES.issubset(profile.granted_scopes):
            return {
                "status": "scope_required",
                "recovery": "Reauthorize this selected character with both fitting scopes.",
            }
        normalized, canonical_id = self._proposal(proposal_payload, proposal_id, character_id)
        catalog_version = normalized["catalog_version"]
        try:
            catalog = self.catalog_provider(catalog_version)
        except FileNotFoundError:
            return {
                "status": "catalog_version_unavailable",
                "recovery": "Refresh/install the catalog version used by this proposal.",
            }
        if catalog_version != catalog.version:
            return {
                "status": "catalog_version_unavailable",
                "recovery": "Revalidate this proposal against an installed matching catalog.",
            }
        fitting = normalized["fitting"]
        facts = {
            type_id: fact
            for type_id in {
                fitting["ship_type_id"],
                *(item["type_id"] for item in fitting["items"]),
            }
            if (fact := catalog.get_type(type_id)) is not None
        }
        skill_response = await self.endpoints.skills(character_id)
        trained = trained_skill_levels(skill_response)
        validation = validate_fitting(_make_fitting(fitting), facts, trained)
        if validation["status"] != "valid":
            return {"status": "proposal_invalid", "validation": validation}

        ledger_row = self.ledger.get(character_id, canonical_id)
        if ledger_row and ledger_row["state"] == "created":
            return {"status": "already_created", "fitting_id": ledger_row["fitting_id"]}
        if ledger_row:
            reconciliation = await self._fresh_fittings(character_id)
            found = self._matching(reconciliation, fitting)
            if found is not None:
                fitting_id = self._fitting_id(found)
                if fitting_id is not None:
                    self.ledger.mark_created(character_id, canonical_id, fitting_id)
                    return {
                        "status": "already_created",
                        "fitting_id": fitting_id,
                        "reconciled": True,
                    }
            self.ledger.mark_unknown(character_id, canonical_id)
            return {
                "status": "creation_outcome_unknown",
                "recovery": (
                    "Inspect saved fittings; this proposal will not be posted again automatically."
                ),
            }

        existing = await self._fresh_fittings(character_id)
        exact = self._matching(existing, fitting)
        if exact is not None:
            fitting_id = self._fitting_id(exact)
            if fitting_id is not None:
                self.ledger.begin(character_id, canonical_id)
                self.ledger.mark_created(character_id, canonical_id, fitting_id)
                return {"status": "already_created", "fitting_id": fitting_id}
            return {
                "status": "creation_outcome_unknown",
                "recovery": "An exact saved fitting exists but its ID could not be verified.",
            }
        for item in existing:
            if _same_name(item, fitting) and _fingerprint(item) != _fingerprint(fitting):
                return {
                    "status": "name_conflict",
                    "recovery": (
                        "Choose a distinct fitting name; existing fittings are never replaced."
                    ),
                }

        if not self.ledger.begin(character_id, canonical_id):
            return {
                "status": "creation_in_progress",
                "recovery": "A matching creation attempt already owns this proposal.",
            }
        try:
            response_id = self._response_id(
                await self.endpoints.create_fitting(character_id, fitting)
            )
        except (EsiError, httpx.HTTPError, TimeoutError):
            self.ledger.mark_unknown(character_id, canonical_id)
            return {
                "status": "creation_outcome_unknown",
                "recovery": "Inspect saved fittings; no automatic second POST will be made.",
            }
        try:
            readback = await self._fresh_fittings(character_id)
        except (EsiError, httpx.HTTPError, ValueError):
            self.ledger.mark_unknown(character_id, canonical_id)
            return {
                "status": "creation_outcome_unknown",
                "recovery": "The POST may have succeeded; inspect saved fittings before retrying.",
            }
        created = self._matching(readback, fitting)
        if created is None:
            self.ledger.mark_unknown(character_id, canonical_id)
            return {
                "status": "creation_outcome_unknown",
                "recovery": (
                    "Fresh readback did not prove creation; inspect saved fittings manually."
                ),
            }
        fitting_id = self._fitting_id(created)
        if fitting_id is None or (response_id is not None and response_id != fitting_id):
            self.ledger.mark_unknown(character_id, canonical_id)
            return {
                "status": "creation_outcome_unknown",
                "recovery": (
                    "Fresh readback did not match the POST response; inspect saved fittings."
                ),
            }
        self.ledger.mark_created(character_id, canonical_id, fitting_id)
        return {"status": "created", "fitting_id": fitting_id, "verified": True}

    async def _fresh_fittings(self, character_id: str) -> list[dict[str, Any]]:
        result = await self.endpoints.fittings(character_id, limit=1000, fresh=True)
        if result.get("truncated") is True:
            raise ValueError("fresh saved-fitting read was truncated")
        return [item for item in result["items"] if isinstance(item, dict)]

    def _proposal(
        self, payload: dict[str, Any], proposal_id: str, character_id: str
    ) -> tuple[dict[str, Any], str]:
        if set(payload) != {
            "proposal_schema_version",
            "proposal_id",
            "character_id",
            "catalog_version",
            "fitting",
        }:
            raise ValueError("proposal contains missing or unsupported fields")
        if payload["proposal_schema_version"] != PROPOSAL_SCHEMA_VERSION:
            raise ValueError("proposal schema version is unsupported")
        if payload["character_id"] != character_id:
            raise ValueError("proposal character does not match the selected character")
        if payload["proposal_id"] != proposal_id:
            raise ValueError("proposal ID argument does not match proposal")
        fitting_data = payload["fitting"]
        if not isinstance(fitting_data, dict) or set(fitting_data) != {
            "name",
            "description",
            "ship_type_id",
            "items",
        }:
            raise ValueError("proposal fitting payload is malformed")
        if not isinstance(fitting_data["items"], list):
            raise ValueError("proposal fitting items must be a list")
        proposal = create_proposal(
            character_id=character_id,
            catalog_version=payload["catalog_version"],
            name=fitting_data["name"],
            description=fitting_data["description"],
            ship_type_id=fitting_data["ship_type_id"],
            items=fitting_data["items"],
        )
        if proposal.proposal_id != proposal_id or proposal.to_dict() != payload:
            raise ValueError("proposal contents do not match the canonical proposal ID")
        return payload, proposal.proposal_id

    @staticmethod
    def _matching(items: list[dict[str, Any]], fitting: dict[str, Any]) -> dict[str, Any] | None:
        expected = _fingerprint(fitting)
        return next((item for item in items if _fingerprint(item) == expected), None)

    @staticmethod
    def _fitting_id(item: dict[str, Any]) -> int | None:
        fitting_id = item.get("fitting_id")
        return fitting_id if type(fitting_id) is int and fitting_id > 0 else None

    @staticmethod
    def _response_id(payload: Any) -> int | None:
        if type(payload) is int and payload > 0:
            return payload
        if isinstance(payload, dict):
            value = payload.get("fitting_id")
            return value if type(value) is int and value > 0 else None
        return None


_REQUIRED_SCOPES = frozenset({"esi-fittings.read_fittings.v1", "esi-fittings.write_fittings.v1"})


def _make_fitting(payload: dict[str, Any]) -> Fitting:
    return Fitting(
        name=payload["name"],
        description=payload["description"],
        ship_type_id=payload["ship_type_id"],
        items=tuple(
            FittingItem(item["type_id"], item["flag"], item["quantity"])
            for item in payload["items"]
        ),
    )


def _fingerprint(payload: dict[str, Any]) -> str | None:
    try:
        items = payload["items"]
        normalized_items = sorted(
            (
                {
                    "type_id": item["type_id"],
                    "flag": item["flag"],
                    "quantity": item["quantity"],
                }
                for item in items
            ),
            key=lambda item: (item["flag"], item["type_id"], item["quantity"]),
        )
        canonical = {
            "name": payload["name"],
            "description": payload["description"],
            "ship_type_id": payload["ship_type_id"],
            "items": normalized_items,
        }
    except (KeyError, TypeError):
        return None
    data = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(data.encode()).hexdigest()


def _same_name(item: dict[str, Any], fitting: dict[str, Any]) -> bool:
    name = item.get("name")
    return isinstance(name, str) and name.strip().casefold() == fitting["name"].strip().casefold()
