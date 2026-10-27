import copy
import json
from pathlib import Path

import pytest

from workflow_api.acceptance_remote import assert_campaign_target
from workflow_api.campaign_deployment import ISOLATED_CHECKOUT, normal_checkout, render_normal_deployment
from workflow_api.mot_2d_plan import render_campaign_files, render_screen_transition


def bound():
    return {"kind": "mot_2d_s0_campaign", "execution_checkout": ISOLATED_CHECKOUT}


def test_isolated_binding_cannot_authorize_existing_scientific_or_test_only_root():
    manifest = bound()
    assert_campaign_target(manifest, "tal.noa", f"/home/tal.noa/{ISOLATED_CHECKOUT}", "data/optimization/mot_2d/fresh")
    for checkout in ("ytterbium_lab_simulation_new", "ytterbium_lab_simulation_ui_acceptance", "arbitrary"):
        with pytest.raises(ValueError):
            assert_campaign_target(manifest, "tal.noa", f"/home/tal.noa/{checkout}")
    with pytest.raises(ValueError):
        assert_campaign_target({"kind": "mot_2d_s0_campaign"}, "tal.noa", f"/home/tal.noa/{ISOLATED_CHECKOUT}")
    with pytest.raises(ValueError):
        assert_campaign_target(manifest, "tal.noa", f"/home/tal.noa/{ISOLATED_CHECKOUT}", "data/optimization/mot_2d/ui_acceptance/fresh")


@pytest.mark.parametrize("change", [
    {"execution_checkout": None}, {"execution_checkout": "arbitrary"},
    {"execution_checkout": "../ytterbium_lab_simulation_new"},
    {"kind": "mot_2d_ui_acceptance_v1"}, {"kind": "unknown_campaign"},
    {"acceptance": {}},
])
def test_invalid_binding_does_not_fall_back_to_a_different_target(change):
    manifest = {**bound(), **change}
    with pytest.raises(ValueError):normal_checkout(manifest)


def test_renderer_binds_paths_only_and_rejects_ambiguous_template():
    original = b'PROJECT_ROOT="${HOME}/ytterbium_lab_simulation_new"\nsource "${HOME}/venvs/atomsmltr/bin/activate"\n#PBS -l select=1:ncpus=200:mem=64gb\n'
    assert render_normal_deployment({}, original) == original
    rendered = render_normal_deployment(bound(), original)
    assert b'${HOME}/ytterbium_lab_simulation_ui_test' in rendered
    assert b'${HOME}/venvs/atomsmltr-ui-test/bin/activate' in rendered
    assert b'#PBS -l select=1:ncpus=200:mem=64gb' in rendered
    for invalid in (original * 2, original.replace(b'PROJECT_ROOT', b'PROJECT_ROOT').replace(b'ytterbium_lab_simulation_new', b'unknown')):
        with pytest.raises(ValueError):render_normal_deployment(bound(), invalid)


def test_actual_bank_plan_keeps_physics_and_binds_ui_and_cli_pbs(tmp_path, monkeypatch):
    from test_historical_zeeman_source import ROOT, BANK
    from workflow_api.mot_2d_plan import build_plan
    from workflow_api.mot_2d_sources import inspect_source
    from workflow_api.repository_snapshot import RepositorySnapshot
    from studies.mot_2d_s0_campaign import write_pbs
    source = inspect_source(ROOT / BANK, ROOT)
    plan = build_plan(ROOT, name="Deployment regression", slug="deployment-regression", s0_values=[1.35], source=source, snapshot=RepositorySnapshot("a" * 40), execution_checkout=ISOLATED_CHECKOUT)
    manifest = plan.manifest
    assert manifest["execution_checkout"] == ISOLATED_CHECKOUT
    assert manifest["kind"] == "mot_2d_s0_campaign" and "acceptance" not in manifest
    for files in (plan.files, render_screen_transition(manifest, plan.destination, ROOT)):
        for path, content in files.items():
            if path.endswith(".pbs"):
                assert b'${HOME}/ytterbium_lab_simulation_ui_test' in content
                assert b'${HOME}/ytterbium_lab_simulation_new' not in content
    output = tmp_path / "later.pbs"
    write_pbs(output, "bound", "0-2", 200, "24:00:00", "true", revision="a" * 40, manifest=manifest)
    assert b'${HOME}/ytterbium_lab_simulation_new' not in output.read_bytes()
    assert b'${HOME}/ytterbium_lab_simulation_ui_test' in output.read_bytes()


def test_creation_confirm_preserves_reviewed_binding_and_physics(tmp_path):
    from test_workflow_api_creation import repository, source, request, FixedSnapshots
    from workflow_api.mutation import CreationService
    repository(tmp_path)
    selected = source(tmp_path)
    creator = CreationService(tmp_path, FixedSnapshots())
    inputs = {**request(selected), "execution_checkout": ISOLATED_CHECKOUT}
    preview = creator.preview(inputs, "session")
    assert preview["plan"]["execution_checkout"] == ISOLATED_CHECKOUT
    created = creator.confirm(preview["preview_token"], "session")
    manifest = json.loads((tmp_path / created["path"] / "campaign.json").read_text())
    assert manifest["execution_checkout"] == ISOLATED_CHECKOUT
    assert manifest["fixed_design"] == preview["scientific_design"]
    assert created["submitted_to_zeus"] is False
    assert creator.confirm(preview["preview_token"], "session") == created


@pytest.mark.parametrize("target", [None, False, 1, "arbitrary"])
def test_creation_api_rejects_invalid_explicit_binding(tmp_path, target):
    from test_workflow_api_creation import FixedSnapshots
    from workflow_api.mutation import CreationService
    creator = CreationService(tmp_path, FixedSnapshots())
    with pytest.raises(ValueError, match="deployment"):
        creator.preview({"name":"x", "slug":"x", "s0_values":[1.35], "source_id":"x", "execution_checkout":target}, "session")
