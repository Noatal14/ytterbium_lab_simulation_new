"""Reject changed acceptance production contracts before inputs or physics load."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from studies.mot_2d import production
from workflow_api.acceptance_profile import load_acceptance_profile


def _case(tmp_path, family):
    profile = load_acceptance_profile()
    campaign = (
        tmp_path / f"data/optimization/{family}/ui_acceptance/preflight/campaign.json"
    )
    campaign.parent.mkdir(parents=True)
    if family == "mot_2d":
        from workflow_api.mot_2d_spec import build_manifest

        manifest = build_manifest(
            name="preflight",
            s0_values=[1.3],
            ensemble_directory="data/acceptance/input",
            zeeman_profile="canonical",
            frozen_inputs={},
            git_commit="a" * 40,
            physical_model_sha256="b" * 64,
            hashed_files=[],
            acceptance_profile_id=profile.profile_id,
        )
        pools = profile.stage("mot_2d", "production")["npools"]
        seed, mot_seed = 3015, 43015
    else:
        from studies.mot_3d_campaign import build_campaign_manifest

        manifest = build_campaign_manifest(
            name="preflight",
            input_directory="data/acceptance/input",
            upstream={},
            roles={},
            revision="a" * 40,
            physical_model_sha256="b" * 64,
            acceptance_profile_id=profile.profile_id,
        )
        jobs = profile.policy["generation"].get("jobs")
        pools = None if jobs is None else jobs["mot_2d"]["npools"]
        seed, mot_seed = 3035, 43035
    arguments = SimpleNamespace(
        acceptance_profile=profile.profile_id,
        input_manifest=campaign,
        ensemble_dir=tmp_path / "data/acceptance/input",
        output_dir=campaign.parent / "outputs",
        states_dir=campaign.parent / "states",
        npools=pools,
        zeeman_seeds=[seed],
        mot_seeds=[mot_seed],
    )
    return campaign, manifest, arguments


def _forbid_load_and_physics(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Acceptance preflight reached inputs or physics.")

    monkeypatch.setattr(production, "load_production_ensembles", forbidden)
    monkeypatch.setattr(production, "evaluate_configuration", forbidden)


@pytest.mark.parametrize("family", ["mot_2d", "mot_3d"])
@pytest.mark.parametrize("mutation", ["solver", "dt", "bounds"])
def test_changed_frozen_physics_fails_before_input_loader(
    tmp_path, monkeypatch, family, mutation
):
    monkeypatch.chdir(tmp_path)
    path, manifest, args = _case(tmp_path, family)
    design = manifest["fixed_design" if family == "mot_2d" else "design"]
    key = (
        {"solver": "solver", "dt": "final_dt_s", "bounds": "detuning_bounds_gamma"}[
            mutation
        ]
        if family == "mot_2d"
        else {
            "solver": "stochastic_solver",
            "dt": "screening_dt_s",
            "bounds": "optimization_bounds",
        }[mutation]
    )
    if family == "mot_3d" and mutation == "solver":
        # Use an actual immutable solver field, independent of its spelling.
        key = next(k for k in design if "solver" in k)
    design[key] = (
        "unreviewed" if mutation == "solver" else (0.1 if mutation == "dt" else {})
    )
    path.write_text(json.dumps(manifest))
    _forbid_load_and_physics(monkeypatch)
    with pytest.raises(ValueError, match="design|physics"):
        production.run_seeds(args)
    assert not args.output_dir.exists() and not args.states_dir.exists()


@pytest.mark.parametrize("family", ["mot_2d", "mot_3d"])
def test_wrong_worker_count_fails_before_input_loader(tmp_path, monkeypatch, family):
    monkeypatch.chdir(tmp_path)
    path, manifest, args = _case(tmp_path, family)
    if args.npools is None:
        pytest.skip(
            "Final generation.jobs policy awaits the physically verified recipe/hash."
        )
    args.npools += 1
    path.write_text(json.dumps(manifest))
    _forbid_load_and_physics(monkeypatch)
    with pytest.raises(ValueError, match="workers.*frozen job resources"):
        production.run_seeds(args)
    assert not args.output_dir.exists() and not args.states_dir.exists()


@pytest.mark.parametrize("family", ["mot_2d", "mot_3d"])
@pytest.mark.parametrize(
    "mismatch", ["empty_mot", "extra_mot", "extra_zeeman", "wrong_pair", "duplicate"]
)
def test_seed_argument_drift_fails_before_loader(
    tmp_path, monkeypatch, family, mismatch
):
    monkeypatch.chdir(tmp_path)
    path, manifest, args = _case(tmp_path, family)
    if args.npools is None:
        pytest.skip(
            "Final generation.jobs policy awaits the physically verified recipe/hash."
        )
    if mismatch == "empty_mot":
        args.mot_seeds = []
    elif mismatch == "extra_mot":
        args.mot_seeds.append(args.mot_seeds[0] + 1)
    elif mismatch == "extra_zeeman":
        args.zeeman_seeds.append(args.zeeman_seeds[0] + 1)
    elif mismatch == "wrong_pair":
        args.mot_seeds[0] += 1
    else:
        args.zeeman_seeds *= 2
        args.mot_seeds *= 2
    path.write_text(json.dumps(manifest))
    _forbid_load_and_physics(monkeypatch)
    with pytest.raises(ValueError, match="seed pairs.*sealed registry"):
        production.run_seeds(args)
    assert not args.output_dir.exists() and not args.states_dir.exists()


@pytest.mark.parametrize("role", ["discovery", "sealed_validation"])
def test_changed_manifest_mot_seed_registry_fails_before_loader(
    tmp_path, monkeypatch, role
):
    monkeypatch.chdir(tmp_path)
    path, manifest, args = _case(tmp_path, "mot_2d")
    manifest["mot_seeds"][role][0] += 1
    if role == "sealed_validation":
        # Matching a tampered registry must not authorize the worker request.
        args.mot_seeds[0] = manifest["mot_seeds"][role][0]
    path.write_text(json.dumps(manifest))
    _forbid_load_and_physics(monkeypatch)
    with pytest.raises(ValueError, match="MOT seed registry.*reviewed roles"):
        production.run_seeds(args)
    assert not args.output_dir.exists() and not args.states_dir.exists()
