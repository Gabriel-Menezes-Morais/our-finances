"""Integridade da suíte fictícia; não declara qualidade semântica do modelo."""

import json
from pathlib import Path

from evals.run import load_cases


def test_pools_are_separate_and_have_case_specific_rubrics() -> None:
    regression = load_cases("regression")
    capability = load_cases("capability")
    assert len(regression) >= 10 and len(capability) >= 10
    cases = regression + capability
    assert len({case["id"] for case in cases}) == len(cases)
    assert all(case["fictional"] is True and len(case["rubric"]) >= 2 for case in cases)
    assert all(case["pool"] == "regression" for case in regression)
    assert all(case["pool"] == "capability" and case["reserved"] for case in capability)
    assert any(len(case.get("history", [])) >= 10 for case in capability)


def test_fixture_has_only_fictional_ids_and_no_identity_keys() -> None:
    fixture = json.loads((Path(__file__).resolve().parents[2] / "evals/fixtures.json").read_text())
    assert fixture["fictional"] is True
    assert not {"owner_id", "workspace_id", "telegram_user_id", "api_key"} & fixture.keys()
