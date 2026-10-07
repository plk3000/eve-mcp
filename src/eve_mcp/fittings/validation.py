"""Deterministic checks limited to installed catalog facts and trained skills."""

from __future__ import annotations

from collections import Counter
from typing import Any

from eve_mcp.fittings.models import Fitting
from eve_mcp.fittings.skill_data import extract_skill_rows
from eve_mcp.static_data.catalog import StaticType

_FLAG_PREFIX = {
    "high": "HiSlot",
    "medium": "MedSlot",
    "low": "LoSlot",
    "rig": "RigSlot",
    "service": "ServiceSlot",
}


def trained_skill_levels(response: dict[str, Any]) -> dict[int, int]:
    items = response.get("items")
    if not isinstance(items, list):
        raise ValueError("character skills response has no item list")
    trained: dict[int, int] = {}
    for item in extract_skill_rows(response):
        skill_id = item.get("skill_id")
        if type(skill_id) is not int or skill_id < 1:
            raise ValueError("character skills response contains an invalid skill ID")
        level = item.get("active_skill_level")
        if type(level) is not int:
            level = item.get("trained_skill_level", 0)
        if type(level) is not int or not 0 <= level <= 5:
            raise ValueError(f"character skills response has an invalid level for skill {skill_id}")
        trained[skill_id] = level
    return trained


_CPU_MANAGEMENT_SKILL_ID = 3426
_POWER_GRID_MANAGEMENT_SKILL_ID = 3413
_CORE_FITTING_BONUS_PERCENT_PER_LEVEL = 5


def _resource_limits(hull: StaticType | None, trained_skills: dict[int, int]) -> dict[str, float]:
    if hull is None:
        return {"cpu": 0.0, "powergrid": 0.0, "calibration": 0.0}
    cpu_percent = 100 + _CORE_FITTING_BONUS_PERCENT_PER_LEVEL * trained_skills.get(
        _CPU_MANAGEMENT_SKILL_ID, 0
    )
    powergrid_percent = 100 + _CORE_FITTING_BONUS_PERCENT_PER_LEVEL * trained_skills.get(
        _POWER_GRID_MANAGEMENT_SKILL_ID, 0
    )
    return {
        "cpu": hull.cpu * cpu_percent / 100,
        "powergrid": hull.powergrid * powergrid_percent / 100,
        "calibration": hull.calibration,
    }


def validate_fitting(
    fitting: Fitting,
    facts: dict[int, StaticType],
    trained_skills: dict[int, int],
) -> dict[str, object]:
    violations: list[dict[str, object]] = []
    gaps: list[dict[str, int]] = []
    unknown: set[int] = set()
    hull = facts.get(fitting.ship_type_id)
    totals = {"cpu": 0.0, "powergrid": 0.0, "calibration": 0.0}
    limits = _resource_limits(hull, trained_skills)
    used_slots: Counter[str] = Counter()
    seen_flags: set[str] = set()

    if hull is None:
        unknown.add(fitting.ship_type_id)
    elif hull.kind != "hull":
        violations.append({"type_id": fitting.ship_type_id, "reason": "ship_type_not_hull"})

    for item in fitting.items:
        static_type = facts.get(item.type_id)
        if static_type is None:
            unknown.add(item.type_id)
            continue
        if static_type.slot_class:
            prefix = _FLAG_PREFIX.get(static_type.slot_class)
            if not prefix or not item.flag.startswith(prefix):
                violations.append(
                    {
                        "type_id": item.type_id,
                        "flag": item.flag,
                        "reason": "wrong_slot_class",
                        "expected": static_type.slot_class,
                    }
                )
            else:
                used_slots[static_type.slot_class] += 1
                if item.flag in seen_flags:
                    violations.append({"flag": item.flag, "reason": "duplicate_slot_assignment"})
                seen_flags.add(item.flag)
                slot_number = int(item.flag.removeprefix(prefix))
                if hull is not None and slot_number >= hull.slots.get(static_type.slot_class, 0):
                    violations.append(
                        {
                            "type_id": item.type_id,
                            "flag": item.flag,
                            "reason": "slot_index_unavailable",
                        }
                    )
        elif static_type.kind in {"module", "rig", "charge"}:
            unknown.add(item.type_id)
        elif static_type.kind == "drone" and item.flag not in {"DroneBay", "FighterBay"}:
            violations.append(
                {
                    "type_id": item.type_id,
                    "flag": item.flag,
                    "reason": "drone_not_in_bay",
                }
            )
        elif static_type.kind == "hull":
            violations.append({"type_id": item.type_id, "reason": "item_type_is_hull"})
        for resource in totals:
            totals[resource] += getattr(static_type, resource) * item.quantity
        for skill_id, required_level in static_type.required_skills.items():
            trained_level = trained_skills.get(skill_id, 0)
            if trained_level < required_level:
                gaps.append(
                    {
                        "type_id": item.type_id,
                        "skill_id": skill_id,
                        "required_level": required_level,
                        "trained_level": trained_level,
                    }
                )

    if hull:
        for slot_class, count in used_slots.items():
            available = hull.slots.get(slot_class, 0)
            if count > available:
                violations.append(
                    {
                        "slot_class": slot_class,
                        "used": count,
                        "available": available,
                        "reason": "slot_count_exceeded",
                    }
                )
        for resource, total in totals.items():
            if total > limits[resource]:
                violations.append(
                    {
                        "resource": resource,
                        "used": total,
                        "available": limits[resource],
                        "reason": "resource_exceeded",
                    }
                )
        for skill_id, required_level in hull.required_skills.items():
            trained_level = trained_skills.get(skill_id, 0)
            if trained_level < required_level:
                gaps.append(
                    {
                        "type_id": hull.type_id,
                        "skill_id": skill_id,
                        "required_level": required_level,
                        "trained_level": trained_level,
                    }
                )

    status = "incomplete" if unknown else "invalid" if violations or gaps else "valid"
    return {
        "status": status,
        "valid": status == "valid",
        "complete": status != "incomplete",
        "skill_gaps": sorted(gaps, key=lambda gap: (gap["type_id"], gap["skill_id"])),
        "slot_violations": violations,
        "resource_totals": totals,
        "resource_limits": limits,
        "unknown_type_ids": sorted(unknown),
        "assumptions": [
            "Validation covers installed static fitting facts and recorded skill levels only.",
            "Core CPU and power-grid skill bonuses are included.",
            (
                "Implant, module-provided, rig-provided, subsystem, role, and other fitting "
                "modifiers remain outside validation unless they are actually modeled."
            ),
        ],
    }
