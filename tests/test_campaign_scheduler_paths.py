"""Pin campaign status queries to the scheduler installed on the Zeus host."""

import ast
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN_QUERIES = {
    "mot_3d_linear_submission_remote.py": 1,
    "zeus_confirmation_submission_remote.py": 1,
    "zeus_confirmation_remote.py": 2,
    "zeus_production_submission_remote.py": 1,
    "zeus_sensitivity_submission_remote.py": 1,
    "zeus_refinement_remote.py": 2,
    "zeus_discovery_submission_remote.py": 1,
    "zeus_screening_remote.py": 1,
    "mot_3d_discovery_transition_remote.py": 1,
    "mot_3d_selection_submission_remote.py": 1,
    "zeus_finalization_remote.py": 1,
    "zeus_production_remote.py": 1,
    "zeus_sensitivity_remote.py": 1,
}


@pytest.mark.parametrize("filename,count", CAMPAIGN_QUERIES.items())
def test_campaign_qstat_uses_installed_pinned_binary_and_targeted_job(filename, count):
    source = (ROOT / "workflow_api" / filename).read_text(encoding="utf-8")
    assert "/usr/local/bin/qstat" not in source
    calls = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.List)
        and node.elts
        and isinstance(node.elts[0], ast.Constant)
        and node.elts[0].value == "/opt/pbs/bin/qstat"
    ]
    assert len(calls) == count
    for call in calls:
        assert len(call.elts) == 5
        assert [ast.literal_eval(value) for value in call.elts[:4]] == [
            "/opt/pbs/bin/qstat", "-x", "-t", "-f"
        ]


@pytest.mark.parametrize("family", ["zeeman", "mot_2d", "mot_3d"])
def test_existing_individual_qstat_fallback_remains_unchanged(family):
    source = (ROOT / "workflow_api" / f"{family}_zeus_remote.py").read_text(
        encoding="utf-8"
    )
    assert "/usr/local/bin/qstat" in source
    assert "/opt/pbs/bin/qstat" in source
