from __future__ import annotations


def test_extract_skills_supports_production_esi_and_fixture_envelopes() -> None:
    from eve_mcp.fittings.skill_data import extract_skill_rows

    production = {
        "items": [
            {
                "skills": [
                    {"skill_id": 10, "active_skill_level": 3},
                    {"skill_id": 20, "trained_skill_level": 2},
                ]
            }
        ]
    }
    fixture = {
        "items": [
            {"skill_id": 10, "active_skill_level": 3},
            {"skill_id": 20, "trained_skill_level": 2},
        ]
    }

    expected = [
        {"skill_id": 10, "active_skill_level": 3},
        {"skill_id": 20, "trained_skill_level": 2},
    ]
    assert extract_skill_rows(production) == expected
    assert extract_skill_rows(fixture) == expected
