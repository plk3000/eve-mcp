from __future__ import annotations

from eve_mcp.static_data.catalog import StaticCatalog, StaticType


def test_catalog_looks_up_types_by_id_and_exposes_only_fitting_facts(tmp_path) -> None:
    catalog = StaticCatalog.create(
        tmp_path / "catalog.sqlite3",
        "fixture-build",
        [
            StaticType(
                type_id=100,
                name="Test Frigate",
                kind="hull",
                group="Frigate",
                category="Ship",
                slot_class=None,
                cpu=0,
                powergrid=0,
                calibration=0,
                slots={"high": 2, "medium": 3, "low": 2, "rig": 2, "service": 0},
                required_skills={10: 1},
            ),
            StaticType(
                type_id=200,
                name="Test Module",
                kind="module",
                group="Mining Laser",
                category="Module",
                slot_class="high",
                cpu=10,
                powergrid=5,
                calibration=0,
                slots={},
                required_skills={10: 1},
            ),
        ],
    )

    assert catalog.version == "fixture-build"
    assert catalog.get_type(100).name == "Test Frigate"
    assert catalog.get_type(200).slot_class == "high"
    assert catalog.get_type(200).required_skills == {10: 1}
    assert catalog.search("test", None, 10)[0].type_id == 100


def test_catalog_lookup_returns_none_for_unknown_type(tmp_path) -> None:
    catalog = StaticCatalog.create(tmp_path / "catalog.sqlite3", "fixture", [])

    assert catalog.get_type(123456) is None
