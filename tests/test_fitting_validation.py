from __future__ import annotations

from dataclasses import replace

import pytest

from eve_mcp.fittings.models import Fitting, FittingItem
from eve_mcp.fittings.validation import trained_skill_levels, validate_fitting
from eve_mcp.static_data.catalog import StaticType


def _facts() -> dict[int, StaticType]:
    return {
        1: StaticType(
            1,
            "Hull",
            "hull",
            "Frigate",
            "Ship",
            None,
            10,
            10,
            0,
            {"high": 1, "medium": 0, "low": 0, "rig": 0, "service": 0},
            {10: 1},
        ),
        2: StaticType(
            2,
            "Module",
            "module",
            "Module",
            "Module",
            "high",
            5,
            4,
            0,
            {},
            {20: 2},
        ),
    }


def _workday_venture() -> Fitting:
    return Fitting(
        "Workday Venture",
        "Supervised low-attention high-sec mining Venture.",
        32880,
        (
            FittingItem(482, "HiSlot0", 1),
            FittingItem(482, "HiSlot1", 1),
            FittingItem(25861, "HiSlot2", 1),
            FittingItem(3829, "MedSlot0", 1),
            FittingItem(6003, "MedSlot1", 1),
            FittingItem(6569, "MedSlot2", 1),
            FittingItem(28576, "LoSlot0", 1),
            FittingItem(31788, "RigSlot0", 1),
            FittingItem(31788, "RigSlot1", 1),
            FittingItem(31788, "RigSlot2", 1),
            FittingItem(2454, "DroneBay", 2),
        ),
    )


def _workday_venture_facts() -> dict[int, StaticType]:
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
    return {record.type_id: record for record in records}


def test_active_skill_level_takes_precedence_over_inaccessible_trained_level() -> None:
    levels = trained_skill_levels(
        {
            "items": [
                {
                    "skills": [
                        {"skill_id": 3426, "active_skill_level": 4, "trained_skill_level": 5},
                        {"skill_id": 3413, "active_skill_level": 3, "trained_skill_level": 5},
                    ]
                }
            ]
        }
    )

    assert levels == {3426: 4, 3413: 3}


def test_workday_venture_uses_active_core_fitting_skill_bonuses() -> None:
    result = validate_fitting(
        _workday_venture(),
        _workday_venture_facts(),
        {
            3426: 4,  # CPU Management IV; trained V must not override alpha-active IV.
            3413: 3,  # Power Grid Management III.
        },
    )

    assert result["status"] == "valid"
    assert result["resource_totals"] == {"cpu": 269.0, "powergrid": 49.0, "calibration": 150.0}
    assert result["resource_limits"] == {"cpu": 288.0, "powergrid": 51.75, "calibration": 400.0}
    assert any(
        "Core CPU and power-grid skill bonuses are included." == item
        for item in result["assumptions"]
    )


def test_workday_venture_without_core_fitting_skills_is_invalid() -> None:
    result = validate_fitting(_workday_venture(), _workday_venture_facts(), {})

    assert result["status"] == "invalid"
    assert {item["resource"] for item in result["slot_violations"] if "resource" in item} == {
        "cpu",
        "powergrid",
    }


def test_validation_reports_skill_gaps_slot_and_resource_overflow() -> None:
    result = validate_fitting(
        Fitting("Fit", "", 1, (FittingItem(2, "MedSlot0", 1),)),
        _facts(),
        {10: 1, 20: 1},
    )

    assert result["status"] == "invalid"
    assert result["skill_gaps"] == [
        {"type_id": 2, "skill_id": 20, "required_level": 2, "trained_level": 1}
    ]
    assert result["slot_violations"]


def test_unknown_type_is_incomplete_and_valid_fit_reports_totals() -> None:
    missing = validate_fitting(
        Fitting("Fit", "", 1, (FittingItem(999, "HiSlot0", 1),)),
        _facts(),
        {10: 1, 20: 2},
    )
    valid = validate_fitting(
        Fitting("Fit", "", 1, (FittingItem(2, "HiSlot0", 1),)),
        _facts(),
        {10: 1, 20: 2},
    )

    assert missing["status"] == "incomplete"
    assert missing["unknown_type_ids"] == [999]
    assert valid["status"] == "valid"
    assert valid["resource_totals"] == {"cpu": 5.0, "powergrid": 4.0, "calibration": 0.0}


@pytest.mark.parametrize(
    ("resource", "amount"),
    [("cpu", 11), ("powergrid", 11), ("calibration", 1)],
)
def test_validation_rejects_resource_overflow(resource: str, amount: int) -> None:
    facts = _facts()
    facts[2] = replace(facts[2], **{resource: amount})

    result = validate_fitting(
        Fitting("Fit", "", 1, (FittingItem(2, "HiSlot0", 1),)),
        facts,
        {10: 1, 20: 2},
    )

    assert result["status"] == "invalid"
    assert any(entry.get("resource") == resource for entry in result["slot_violations"])


def test_validation_rejects_duplicate_or_unavailable_slots_and_hull_skill_gap() -> None:
    facts = _facts()
    fitting = Fitting(
        "Fit",
        "",
        1,
        (
            FittingItem(2, "HiSlot0", 1),
            FittingItem(2, "HiSlot1", 1),
        ),
    )

    result = validate_fitting(fitting, facts, {20: 2})

    assert result["status"] == "invalid"
    assert {item["reason"] for item in result["slot_violations"]} >= {
        "slot_count_exceeded",
        "slot_index_unavailable",
    }
    assert any(gap["type_id"] == 1 for gap in result["skill_gaps"])


def test_validation_does_not_assume_missing_item_slot_facts() -> None:
    facts = _facts()
    facts[2] = replace(facts[2], kind="charge", slot_class=None)

    result = validate_fitting(
        Fitting("Fit", "", 1, (FittingItem(2, "HiSlot0", 1),)),
        facts,
        {10: 1, 20: 2},
    )

    assert result["status"] == "incomplete"
    assert result["unknown_type_ids"] == [2]
