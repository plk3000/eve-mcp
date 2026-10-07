from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from eve_mcp.fittings.creation_ledger import CreationLedger
from eve_mcp.fittings.proposal import create_proposal
from eve_mcp.fittings.writer import FittingWriter
from eve_mcp.profiles import ProfileRepository
from eve_mcp.static_data.catalog import StaticCatalog, StaticType


class FakeEndpoints:
    def __init__(
        self,
        fits: list[dict[str, object]] | None = None,
        fail_post: bool = False,
        apply_then_fail: bool = False,
    ) -> None:
        self.fits = fits or []
        self.fail_post = fail_post
        self.apply_then_fail = apply_then_fail
        self.get_calls = 0
        self.posts: list[tuple[str, dict[str, object]]] = []

    async def fittings(
        self, character_id: str, limit: int = 100, fresh: bool = False
    ) -> dict[str, object]:
        assert character_id == "100"
        assert fresh is True
        self.get_calls += 1
        return {"items": self.fits, "returned_count": len(self.fits)}

    async def skills(self, character_id: str) -> dict[str, object]:
        assert character_id == "100"
        return {
            "items": [
                {"skill_id": 10, "active_skill_level": 1},
                {"skill_id": 20, "active_skill_level": 1},
            ]
        }

    async def create_fitting(self, character_id: str, fitting: dict[str, object]) -> int:
        assert character_id == "100"
        self.posts.append((character_id, fitting))
        if self.fail_post:
            if self.apply_then_fail:
                self.fits.append({"fitting_id": 5, **fitting})
            raise TimeoutError("request timed out")
        self.fits.append({"fitting_id": 5, **fitting})
        return 5


def _setup(
    tmp_path,
    scopes: list[str] | None = None,
    *,
    fail_post: bool = False,
    apply_then_fail: bool = False,
):
    profiles = ProfileRepository(tmp_path / "profiles.sqlite")
    profiles.upsert(
        "100",
        "Alice",
        scopes
        if scopes is not None
        else ["esi-fittings.read_fittings.v1", "esi-fittings.write_fittings.v1"],
        datetime.now(UTC),
        "ok",
    )
    catalog = StaticCatalog.create(
        tmp_path / "catalog.sqlite3",
        "fixture",
        [
            StaticType(
                1,
                "Hull",
                "hull",
                "Frigate",
                "Ship",
                None,
                10,
                10,
                0,
                {"high": 1},
                {10: 1},
            ),
            StaticType(2, "Module", "module", "Module", "Module", "high", 2, 2, 0, {}, {20: 1}),
        ],
    )
    endpoints = FakeEndpoints(fail_post=fail_post, apply_then_fail=apply_then_fail)
    writer = FittingWriter(
        profiles,
        endpoints,
        lambda version: catalog,
        CreationLedger(tmp_path / "ledger.sqlite"),
    )
    proposal = create_proposal(
        character_id="100",
        catalog_version="fixture",
        name="Approved",
        description="",
        ship_type_id=1,
        items=[{"type_id": 2, "flag": "HiSlot0", "quantity": 1}],
    )
    return writer, endpoints, proposal


class VentureEndpoints(FakeEndpoints):
    async def skills(self, character_id: str) -> dict[str, object]:
        assert character_id == "100"
        return {
            "items": [
                {
                    "skills": [
                        {"skill_id": 3426, "active_skill_level": 4, "trained_skill_level": 5},
                        {"skill_id": 3413, "active_skill_level": 3, "trained_skill_level": 5},
                    ]
                }
            ]
        }


def _workday_venture_writer(tmp_path) -> tuple[FittingWriter, VentureEndpoints, object]:
    profiles = ProfileRepository(tmp_path / "profiles.sqlite")
    profiles.upsert(
        "100",
        "Alice",
        ["esi-fittings.read_fittings.v1", "esi-fittings.write_fittings.v1"],
        datetime.now(UTC),
        "ok",
    )
    records = [
        StaticType(
            32880,
            "Venture",
            "hull",
            "Mining Frigate",
            "Ship",
            None,
            240,
            45,
            400,
            {"high": 3, "medium": 3, "low": 1, "rig": 3, "service": 0},
            {},
        ),
        StaticType(482, "Miner II", "module", "Mining Laser", "Module", "high", 80, 4, 0, {}, {}),
        StaticType(25861, "Salvager I", "module", "Salvager", "Module", "high", 20, 1, 0, {}, {}),
        StaticType(
            3829,
            "Medium Shield Extender I",
            "module",
            "Shield Extender",
            "Module",
            "medium",
            28,
            28,
            0,
            {},
            {},
        ),
        StaticType(
            6003,
            "1MN Monopropellant Enduring Afterburner",
            "module",
            "Afterburner",
            "Module",
            "medium",
            15,
            10,
            0,
            {},
            {},
        ),
        StaticType(
            6569,
            "ML-3 Compact Mining Survey Chipset",
            "module",
            "Survey Scanner",
            "Module",
            "medium",
            6,
            1,
            0,
            {},
            {},
        ),
        StaticType(
            28576,
            "Mining Laser Upgrade II",
            "module",
            "Mining Laser Upgrade",
            "Module",
            "low",
            40,
            1,
            0,
            {},
            {},
        ),
        StaticType(
            31788,
            "Small Core Defense Field Extender I",
            "rig",
            "Shield Rig",
            "Module",
            "rig",
            0,
            0,
            50,
            {},
            {},
        ),
        StaticType(2454, "Hobgoblin I", "drone", "Combat Drone", "Drone", None, 0, 0, 0, {}, {}),
    ]
    catalog = StaticCatalog.create(tmp_path / "catalog.sqlite3", "fixture", records)
    endpoints = VentureEndpoints()
    writer = FittingWriter(
        profiles,
        endpoints,
        lambda version: catalog,
        CreationLedger(tmp_path / "ledger.sqlite"),
    )
    proposal = create_proposal(
        character_id="100",
        catalog_version="fixture",
        name="Workday Venture",
        description="Supervised low-attention high-sec mining Venture.",
        ship_type_id=32880,
        items=[
            {"type_id": 482, "flag": "HiSlot0", "quantity": 1},
            {"type_id": 482, "flag": "HiSlot1", "quantity": 1},
            {"type_id": 25861, "flag": "HiSlot2", "quantity": 1},
            {"type_id": 3829, "flag": "MedSlot0", "quantity": 1},
            {"type_id": 6003, "flag": "MedSlot1", "quantity": 1},
            {"type_id": 6569, "flag": "MedSlot2", "quantity": 1},
            {"type_id": 28576, "flag": "LoSlot0", "quantity": 1},
            {"type_id": 31788, "flag": "RigSlot0", "quantity": 1},
            {"type_id": 31788, "flag": "RigSlot1", "quantity": 1},
            {"type_id": 31788, "flag": "RigSlot2", "quantity": 1},
            {"type_id": 2454, "flag": "DroneBay", "quantity": 2},
        ],
    )
    return writer, endpoints, proposal


def test_writer_fresh_revalidation_accepts_workday_venture_with_active_fitting_skills(
    tmp_path,
) -> None:
    writer, endpoints, proposal = _workday_venture_writer(tmp_path)

    result = asyncio.run(writer.create("100", proposal.to_dict(), proposal.proposal_id, True))

    assert result["status"] == "created"
    assert len(endpoints.posts) == 1


def test_writer_does_not_post_workday_venture_when_fitting_skills_are_absent(tmp_path) -> None:
    writer, endpoints, proposal = _workday_venture_writer(tmp_path)

    async def no_fitting_skills(character_id: str) -> dict[str, object]:
        assert character_id == "100"
        return {"items": [{"skills": []}]}

    endpoints.skills = no_fitting_skills  # type: ignore[method-assign]
    result = asyncio.run(writer.create("100", proposal.to_dict(), proposal.proposal_id, True))

    assert result["status"] == "proposal_invalid"
    assert endpoints.posts == []


def test_missing_confirmation_and_wrong_character_make_no_endpoint_calls(tmp_path) -> None:
    writer, endpoints, proposal = _setup(tmp_path)

    result = asyncio.run(writer.create("100", proposal.to_dict(), proposal.proposal_id, False))

    assert result["status"] == "confirmation_required"
    assert endpoints.get_calls == 0
    assert endpoints.posts == []


def test_character_mismatch_and_missing_scope_make_no_endpoint_calls(tmp_path) -> None:
    writer, endpoints, proposal = _setup(tmp_path)
    altered = proposal.to_dict()
    altered["character_id"] = "200"

    with pytest.raises(ValueError, match="character"):
        asyncio.run(writer.create("100", altered, proposal.proposal_id, True))
    assert endpoints.get_calls == 0
    assert endpoints.posts == []

    writer, endpoints, proposal = _setup(tmp_path / "no-scope", scopes=[])
    result = asyncio.run(writer.create("100", proposal.to_dict(), proposal.proposal_id, True))
    assert result["status"] == "scope_required"
    assert endpoints.get_calls == 0
    assert endpoints.posts == []


def test_modified_proposal_hash_is_rejected_before_endpoint_calls(tmp_path) -> None:
    writer, endpoints, proposal = _setup(tmp_path)
    modified = proposal.to_dict()
    modified["fitting"]["name"] = "Tampered"

    with pytest.raises(ValueError, match="canonical proposal ID"):
        asyncio.run(writer.create("100", modified, proposal.proposal_id, True))

    assert endpoints.get_calls == 0
    assert endpoints.posts == []


def test_create_posts_once_then_freshly_reads_back_exact_fit(tmp_path) -> None:
    writer, endpoints, proposal = _setup(tmp_path)

    result = asyncio.run(writer.create("100", proposal.to_dict(), proposal.proposal_id, True))

    assert result["status"] == "created"
    assert result["fitting_id"] == 5
    assert len(endpoints.posts) == 1
    assert endpoints.get_calls == 2


def test_completed_ledger_retry_and_existing_exact_fit_do_not_post(tmp_path) -> None:
    writer, endpoints, proposal = _setup(tmp_path)
    first = asyncio.run(writer.create("100", proposal.to_dict(), proposal.proposal_id, True))
    after_first_posts = len(endpoints.posts)
    second = asyncio.run(writer.create("100", proposal.to_dict(), proposal.proposal_id, True))

    assert first["status"] == "created"
    assert second["status"] == "already_created"
    assert len(endpoints.posts) == after_first_posts == 1

    writer, endpoints, proposal = _setup(tmp_path / "ledger-lost")
    endpoints.fits = [
        {
            "fitting_id": 11,
            "name": "Approved",
            "description": "",
            "ship_type_id": 1,
            "items": [{"type_id": 2, "flag": "HiSlot0", "quantity": 1}],
        }
    ]
    result = asyncio.run(writer.create("100", proposal.to_dict(), proposal.proposal_id, True))
    assert result["status"] == "already_created"
    assert endpoints.posts == []


def test_same_name_different_fit_is_refused_without_post(tmp_path) -> None:
    writer, endpoints, proposal = _setup(tmp_path)
    endpoints.fits = [
        {
            "fitting_id": 7,
            "name": "Approved",
            "description": "different",
            "ship_type_id": 1,
            "items": [],
        }
    ]

    result = asyncio.run(writer.create("100", proposal.to_dict(), proposal.proposal_id, True))

    assert result["status"] == "name_conflict"
    assert endpoints.posts == []


def test_timeout_is_unknown_and_retry_reconciles_without_second_post(tmp_path) -> None:
    writer, endpoints, proposal = _setup(tmp_path, fail_post=True)

    first = asyncio.run(writer.create("100", proposal.to_dict(), proposal.proposal_id, True))
    second = asyncio.run(writer.create("100", proposal.to_dict(), proposal.proposal_id, True))

    assert first["status"] == "creation_outcome_unknown"
    assert second["status"] == "creation_outcome_unknown"
    assert len(endpoints.posts) == 1


def test_retry_reconciles_successful_but_timed_out_post_without_duplicate(tmp_path) -> None:
    writer, endpoints, proposal = _setup(tmp_path, fail_post=True, apply_then_fail=True)

    first = asyncio.run(writer.create("100", proposal.to_dict(), proposal.proposal_id, True))
    second = asyncio.run(writer.create("100", proposal.to_dict(), proposal.proposal_id, True))

    assert first["status"] == "creation_outcome_unknown"
    assert second["status"] == "already_created"
    assert second["reconciled"] is True
    assert len(endpoints.posts) == 1
