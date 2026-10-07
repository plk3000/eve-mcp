from __future__ import annotations

import pytest


def test_proposal_id_is_stable_for_item_order_and_changes_with_catalog_or_payload() -> None:
    from eve_mcp.fittings.proposal import create_proposal

    proposal = create_proposal(
        character_id="100",
        catalog_version="build-a",
        name="Mining",
        description="Example",
        ship_type_id=123,
        items=[
            {"type_id": 2, "flag": "HiSlot0", "quantity": 1},
            {"type_id": 3, "flag": "MedSlot0", "quantity": 2},
        ],
    )
    reordered = create_proposal(
        character_id="100",
        catalog_version="build-a",
        name="Mining",
        description="Example",
        ship_type_id=123,
        items=[
            {"type_id": 3, "flag": "MedSlot0", "quantity": 2},
            {"type_id": 2, "flag": "HiSlot0", "quantity": 1},
        ],
    )
    changed = create_proposal(
        character_id="100",
        catalog_version="build-b",
        name="Mining",
        description="Example",
        ship_type_id=123,
        items=[
            {"type_id": 2, "flag": "HiSlot0", "quantity": 1},
            {"type_id": 3, "flag": "MedSlot0", "quantity": 2},
        ],
    )
    changed_quantity = create_proposal(
        character_id="100",
        catalog_version="build-a",
        name="Mining",
        description="Example",
        ship_type_id=123,
        items=[
            {"type_id": 2, "flag": "HiSlot0", "quantity": 2},
            {"type_id": 3, "flag": "MedSlot0", "quantity": 2},
        ],
    )

    assert proposal.proposal_id == reordered.proposal_id
    assert proposal.proposal_id != changed.proposal_id
    assert proposal.proposal_id != changed_quantity.proposal_id
    assert "token" not in proposal.to_dict()
    assert "character_id" not in proposal.fitting_dict()


@pytest.mark.parametrize(
    "item",
    [
        {"type_id": 0, "flag": "HiSlot0", "quantity": 1},
        {"type_id": 1, "flag": "", "quantity": 1},
        {"type_id": 1, "flag": "NotAFlag", "quantity": 1},
        {"type_id": 1, "flag": "HiSlot0", "quantity": 0},
        {"type_id": True, "flag": "HiSlot0", "quantity": 1},
    ],
)
def test_proposals_reject_invalid_item_fields(item: dict[str, object]) -> None:
    from eve_mcp.fittings.proposal import create_proposal

    with pytest.raises(ValueError):
        create_proposal(
            character_id="100",
            catalog_version="build-a",
            name="Mining",
            description="Example",
            ship_type_id=123,
            items=[item],
        )


def test_proposal_rejects_saving_for_a_different_character() -> None:
    from eve_mcp.fittings.proposal import create_proposal

    proposal = create_proposal(
        character_id="100",
        catalog_version="build-a",
        name="Mining",
        description="Example",
        ship_type_id=123,
        items=[],
    )

    with pytest.raises(ValueError, match="character"):
        proposal.require_character("200")
