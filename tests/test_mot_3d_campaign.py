import hashlib
import json
import shlex
from argparse import Namespace
from pathlib import Path

import numpy as np
import pytest

from studies import mot_3d_campaign
from studies.mot_3d.integrity import (
    frozen_stage_design,
    simultaneous_intervals,
    validate_artifact_registry,
)


def _write_ensemble(root, seed, mot_seed=None, count=60):
    mot_seed = 8000 + seed if mot_seed is None else mot_seed
    path = root / (
        f"mot_2d_survivors_zeeman_seed{seed}_mot_seed{mot_seed}.npy"
    )
    states = np.zeros((count, 6), dtype=float)
    np.save(path, states)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    path.with_suffix(".json").write_text(
        json.dumps(
            {
                "kind": "mot_2d_final_survivor_ensemble",
                "zeeman_seed": seed,
                "mot_seed": mot_seed,
                "n_survivors": count,
                "shape": list(states.shape),
                "dtype": str(states.dtype),
                "output_sha256": digest,
                "parameters": {"s0": 1.3, "detuning_gamma": -0.9, "magnet_radius": 0.046},
                "design": {
                    "git_commit": "2d-commit",
                    "dt_s": 0.625e-6,
                    "stochastic_solver": "RK4StHybridCustom",
                    "ensemble_dir": "corrected-zeeman-inputs",
                    "zeeman_profile": "corrected-profile",
                },
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def input_dir(tmp_path):
    root = tmp_path / "inputs"
    root.mkdir()
    for seed in mot_3d_campaign.EXPECTED_SEEDS:
        _write_ensemble(root, seed)
    return root


@pytest.fixture
def upstream_campaign(tmp_path, input_dir):
    root = tmp_path / "upstream_2d"
    root.mkdir()
    seeds = list(mot_3d_campaign.EXPECTED_SEEDS)
    mot_seeds = [8000 + seed for seed in seeds]
    (root / "campaign.json").write_text(json.dumps({
        "kind": "mot_2d_s0_campaign",
        "stage": "complete",
        "seed_roles": {"sealed_validation": seeds},
        "mot_seeds": {"sealed_validation": mot_seeds},
        "provenance": {"git_commit": "2d-commit", "physical_model_sha256": "2d-hash"},
        "stages": {"final_report": str(root / "final_report.json")},
        "s0_values": [1.3],
        "fixed_design": {"final_dt_s": 0.625e-6, "solver": "RK4StHybridCustom"},
        "ensemble_source": {"directory": "corrected-zeeman-inputs", "zeeman_profile": "corrected-profile"},
    }))
    (root / "final_report.json").write_text(json.dumps({
        "kind": "mot_2d_s0_campaign_final_report",
        "results": [{
            "s0": 1.3,
            "survivor_states_directory": str(input_dir),
            "recommended_parameters": {
                "s0": 1.3,
                "detuning_gamma": -0.9,
                "magnet_radius": 0.046,
            },
        }],
    }))
    return root


def test_freeze_inputs_uses_declared_12_4_4_split(input_dir):
    roles = mot_3d_campaign.freeze_inputs(input_dir)

    assert [len(roles[name]) for name in roles] == [12, 4, 4]
    assert [row["zeeman_seed"] for row in roles["discovery"]] == list(
        range(3015, 3027)
    )
    assert [row["zeeman_seed"] for row in roles["refinement"]] == list(
        range(3027, 3031)
    )
    assert [row["zeeman_seed"] for row in roles["preliminary_check"]] == list(
        range(3031, 3035)
    )


def test_freeze_inputs_rejects_tampering(input_dir):
    path = next(input_dir.glob("*seed3015_*.npy"))
    path.write_bytes(path.read_bytes() + b"tamper")

    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        mot_3d_campaign.freeze_inputs(input_dir)


def test_create_is_plan_only_and_freezes_new_design(
    input_dir, upstream_campaign, tmp_path, monkeypatch
):
    monkeypatch.setattr(mot_3d_campaign, "_revision", lambda: "abc123")
    monkeypatch.setattr(mot_3d_campaign, "_relevant_hash", lambda: "physics-hash")
    monkeypatch.setattr(mot_3d_campaign, "_dirty_relevant_files", lambda: ())
    output = tmp_path / "campaign"

    mot_3d_campaign.create(
        Namespace(
            name="new-3d",
            input_dir=str(input_dir),
            upstream_campaign=str(upstream_campaign),
            output_dir=str(output),
        )
    )

    manifest = json.loads((output / "campaign.json").read_text())
    assert manifest["stage"] == "dt_validation_required"
    assert manifest["provenance"]["git_commit"] == "abc123"
    assert manifest["upstream_2d_campaign"]["campaign_sha256"]
    assert len(manifest["upstream_2d_campaign"]["sealed_seed_pairs"]) == 20
    assert manifest["design"]["green_full_angle_deg"] == pytest.approx(62.0)
    assert manifest["design"]["donut_shared_aperture_radius_m"] == pytest.approx(
        0.005
    )
    assert manifest["design"]["single_pass_blue_aperture_radius_m"] == pytest.approx(
        0.0075
    )
    assert manifest["design"]["screening_dt_s"] == pytest.approx(1.25e-6)
    assert manifest["design"]["production_dt_s"] == pytest.approx(0.625e-6)
    assert manifest["design"]["timestep_status"] == (
        "provisional_pending_3d_validation"
    )
    assert manifest["design"]["dt_validation_candidates_s"] == pytest.approx(
        [2.5e-6, 1.25e-6, 0.625e-6]
    )
    assert manifest["design"]["dt_validation_reference_s"] == pytest.approx(
        0.3125e-6
    )

    jobs = list((output / "jobs").rglob("*.pbs"))
    assert len(jobs) == 7
    assert all("EXPECTED_COMMIT=abc123" in path.read_text() for path in jobs)
    assert all("export TMPDIR=" in path.read_text() for path in jobs)
    assert all("qsub" not in path.read_text() for path in jobs)
    assert not list(output.rglob("*.db"))
    submitter = (output / "jobs/02_submit_discovery_chain.sh").read_text()
    assert "submit-discovery" in submitter
    assert "qsub" not in submitter
    donut_rounds = manifest["jobs"]["discovery_rounds"]["angled_donut"]
    first = Path(donut_rounds[0]).read_text()
    second = Path(donut_rounds[1]).read_text()
    assert "targets=(59 59 58)" in first
    assert "targets=(117 117 116)" in second

    for job in jobs:
        text = job.read_text()
        if "studies.mot_3d.discovery.optimize" not in text:
            continue
        command = next(
            line for line in text.splitlines()
            if "studies.mot_3d.discovery.optimize" in line
        )
        tokens = shlex.split(command)
        assert tokens[tokens.index("--input") + 1] == str(input_dir.resolve())
        assert tokens[tokens.index("--input-manifest") + 1] == str(
            output / "campaign.json"
        )


def test_discovery_jobs_quote_hostile_input_path(tmp_path):
    root = tmp_path / "campaign with spaces; $(unsafe)"
    input_dir = tmp_path / "input with spaces; $(unsafe) 'quote'"
    input_dir.mkdir()

    smoke, rounds, _ = mot_3d_campaign.write_discovery_jobs(
        root, "abc123", input_dir
    )

    jobs = list(smoke.values()) + [
        path for family_paths in rounds.values() for path in family_paths
    ]
    assert len(jobs) == 7
    for job in jobs:
        command = next(
            line for line in job.read_text().splitlines()
            if "studies.mot_3d.discovery.optimize" in line
        )
        tokens = shlex.split(command)
        assert tokens[tokens.index("--input") + 1] == str(input_dir.resolve())
        assert tokens[tokens.index("--input-manifest") + 1] == str(
            root / "campaign.json"
        )


def test_discovery_loader_accepts_frozen_role_manifest(input_dir, tmp_path, monkeypatch):
    manifest = tmp_path / "campaign.json"
    manifest.write_text(
        json.dumps(
            {
                "upstream_2d_campaign": {
                    "sealed_seed_pairs": [
                        {"zeeman_seed": row["zeeman_seed"], "mot_seed": row["mot_seed"]}
                        for row in mot_3d_campaign.freeze_inputs(input_dir)["discovery"]
                    ]
                },
                "input_roles": {
                    "discovery": mot_3d_campaign.freeze_inputs(input_dir)[
                        "discovery"
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    payload = json.loads(manifest.read_text())
    payload["provenance"] = {"git_commit": "abc", "physical_model_sha256": "hash"}
    manifest.write_text(json.dumps(payload))
    monkeypatch.setattr(mot_3d_campaign, "_revision", lambda: "abc")
    monkeypatch.setattr(mot_3d_campaign, "_relevant_hash", lambda: "hash")
    from studies.mot_3d.discovery.optimize import _manifest_input_files

    paths = _manifest_input_files(manifest, "discovery")

    assert len(paths) == 12
    assert all("mot_2d_survivors" in path for path in paths)


def test_execution_revalidation_rejects_metadata_tampering(input_dir, tmp_path, monkeypatch):
    roles = mot_3d_campaign.freeze_inputs(input_dir)
    manifest = tmp_path / "campaign.json"
    manifest.write_text(json.dumps({
        "provenance": {"git_commit": "abc", "physical_model_sha256": "hash"},
        "upstream_2d_campaign": {"sealed_seed_pairs": [
            {"zeeman_seed": row["zeeman_seed"], "mot_seed": row["mot_seed"]}
            for rows in roles.values() for row in rows
        ]},
        "input_roles": roles,
    }))
    monkeypatch.setattr(mot_3d_campaign, "_revision", lambda: "abc")
    monkeypatch.setattr(mot_3d_campaign, "_relevant_hash", lambda: "hash")
    Path(roles["discovery"][0]["metadata_path"]).write_text("{}")

    with pytest.raises(ValueError, match="metadata SHA-256 mismatch"):
        mot_3d_campaign.validate_frozen_inputs(manifest, "discovery")


def test_execution_revalidation_requires_exact_ordered_role(input_dir, tmp_path, monkeypatch):
    roles = mot_3d_campaign.freeze_inputs(input_dir)
    roles["discovery"] = list(reversed(roles["discovery"]))
    manifest = tmp_path / "campaign.json"
    manifest.write_text(json.dumps({
        "provenance": {"git_commit": "abc", "physical_model_sha256": "hash"},
        "upstream_2d_campaign": {"sealed_seed_pairs": [
            {"zeeman_seed": row["zeeman_seed"], "mot_seed": row["mot_seed"]}
            for rows in roles.values() for row in rows
        ]},
        "input_roles": roles,
    }))
    monkeypatch.setattr(mot_3d_campaign, "_revision", lambda: "abc")
    monkeypatch.setattr(mot_3d_campaign, "_relevant_hash", lambda: "hash")

    with pytest.raises(ValueError, match="exact ordered seeds"):
        mot_3d_campaign.validate_frozen_inputs(manifest, "discovery")


def test_create_rejects_dirty_relevant_code(
    input_dir, upstream_campaign, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        mot_3d_campaign, "_dirty_relevant_files", lambda: ("utils/RK4StHybridCustom.py",)
    )
    with pytest.raises(RuntimeError, match="dirty relevant files"):
        mot_3d_campaign.create(Namespace(
            name="dirty",
            input_dir=str(input_dir),
            upstream_campaign=str(upstream_campaign),
            output_dir=str(tmp_path / "campaign"),
        ))


def test_model_closure_includes_vendored_physics_engine():
    files = mot_3d_campaign.relevant_files()
    assert any(path.startswith("atomsmltr/src/atomsmltr/") for path in files)
    assert "studies/mot_2d/optimization.py" in files
    assert "studies/mot_2d/production.py" in files


def test_final_input_jobs_use_domain_module_paths(tmp_path, monkeypatch):
    import studies.mot_3d.discovery.optimize as optimizer

    monkeypatch.setattr(
        optimizer,
        "build_profile_from_parameters",
        lambda family, parameters: ({"family": family}, parameters, {}),
    )
    root = tmp_path / "campaign"
    (root / "selection").mkdir(parents=True)
    parameters = {"green_s0": 1.0}
    for family in mot_3d_campaign.FAMILIES:
        path = root / "finalist_selection" / family / "merged"
        path.mkdir(parents=True)
        (path / "finalist_summary.json").write_text(
            json.dumps(
                {
                    "ranked_candidates": [
                        {"candidate_id": f"{family}_winner", "parameters": parameters}
                    ]
                }
            )
        )
    manifest = {
        "provenance": {"git_commit": "abc123"},
        "upstream_2d_campaign": {
            "expected_survivor_parameters": {
                "s0": 1.3,
                "detuning_gamma": -1.0,
                "magnet_radius": 0.046,
            },
            "expected_survivor_design": {"zeeman_profile": "corrected"},
        },
        "stages": {},
    }
    (root / "campaign.json").write_text(json.dumps(manifest))

    mot_3d_campaign.prepare_final_validation_inputs(root, manifest)

    zeeman = (root / "jobs/final_validation_inputs/01_generate_zeeman.pbs").read_text()
    mot_2d = (root / "jobs/final_validation_inputs/02_generate_2d_survivors.pbs").read_text()
    combined = zeeman + mot_2d
    assert "studies.zeeman.generate_ensembles" in zeeman
    assert "studies.mot_2d.production" in mot_2d
    assert "studies.generate_corrected_zeeman_ensembles" not in combined
    assert "studies.run_2d_mot_final_production" not in combined


def test_upstream_report_must_be_registered(input_dir, upstream_campaign):
    manifest_path = upstream_campaign / "campaign.json"
    payload = json.loads(manifest_path.read_text())
    payload["stages"]["final_report"] = "some/other/report.json"
    manifest_path.write_text(json.dumps(payload))

    with pytest.raises(ValueError, match="does not register"):
        mot_3d_campaign.validate_upstream_2d_campaign(
            upstream_campaign, input_dir
        )


def test_runtime_rejects_pair_changed_from_upstream(input_dir, tmp_path, monkeypatch):
    roles = mot_3d_campaign.freeze_inputs(input_dir)
    registry = [
        {"zeeman_seed": row["zeeman_seed"], "mot_seed": row["mot_seed"]}
        for rows in roles.values() for row in rows
    ]
    registry[0]["mot_seed"] += 1
    manifest = tmp_path / "campaign.json"
    manifest.write_text(json.dumps({
        "provenance": {"git_commit": "abc", "physical_model_sha256": "hash"},
        "upstream_2d_campaign": {"sealed_seed_pairs": registry},
        "input_roles": roles,
    }))
    monkeypatch.setattr(mot_3d_campaign, "_revision", lambda: "abc")
    monkeypatch.setattr(mot_3d_campaign, "_relevant_hash", lambda: "hash")

    with pytest.raises(ValueError, match="differs from upstream"):
        mot_3d_campaign.validate_frozen_inputs(manifest, "discovery")


def test_submission_records_raw_array_ids_and_rejects_duplicate(
    input_dir, upstream_campaign, tmp_path, monkeypatch
):
    monkeypatch.setattr(mot_3d_campaign, "_revision", lambda: "abc123")
    monkeypatch.setattr(mot_3d_campaign, "_relevant_hash", lambda: "physics-hash")
    monkeypatch.setattr(mot_3d_campaign, "_dirty_relevant_files", lambda: ())
    root = tmp_path / "campaign"
    mot_3d_campaign.create(Namespace(
        name="submit", input_dir=str(input_dir),
        upstream_campaign=str(upstream_campaign), output_dir=str(root),
    ))
    manifest_path = root / "campaign.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["stage"] = "discovery"
    manifest_path.write_text(json.dumps(manifest))
    commands = []
    ids = iter(["101[].zeus", "102[].zeus", "201[].zeus", "202[].zeus", "203[].zeus"])
    def fake_qsub(command):
        commands.append(command)
        return next(ids)
    record = mot_3d_campaign.submit_discovery(root, qsub=fake_qsub)
    assert record["status"] == "submitted"
    assert record["families"]["angled_donut"]["final_job_id"] == "102[].zeus"
    assert commands[1][4] == "depend=afterok:101[].zeus"
    with pytest.raises(FileExistsError, match="already submitted"):
        mot_3d_campaign.submit_discovery(root, qsub=fake_qsub)


def test_submission_preserves_partial_failure_record(
    input_dir, upstream_campaign, tmp_path, monkeypatch
):
    monkeypatch.setattr(mot_3d_campaign, "_revision", lambda: "abc123")
    monkeypatch.setattr(mot_3d_campaign, "_relevant_hash", lambda: "physics-hash")
    monkeypatch.setattr(mot_3d_campaign, "_dirty_relevant_files", lambda: ())
    root = tmp_path / "campaign"
    mot_3d_campaign.create(Namespace(
        name="partial", input_dir=str(input_dir),
        upstream_campaign=str(upstream_campaign), output_dir=str(root),
    ))
    manifest_path = root / "campaign.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["stage"] = "discovery"
    manifest_path.write_text(json.dumps(manifest))
    calls = 0
    def fake_qsub(command):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("scheduler unavailable")
        return "101[].zeus"
    with pytest.raises(RuntimeError, match="scheduler unavailable"):
        mot_3d_campaign.submit_discovery(root, qsub=fake_qsub)
    saved = json.loads((root / "discovery_submission.json").read_text())
    assert saved["status"] == "partial_failure"
    assert saved["families"]["angled_donut"]["rounds"][0]["job_id"] == "101[].zeus"


def test_early_submission_does_not_poison_later_valid_submission(
    input_dir, upstream_campaign, tmp_path, monkeypatch
):
    monkeypatch.setattr(mot_3d_campaign, "_revision", lambda: "abc123")
    monkeypatch.setattr(mot_3d_campaign, "_relevant_hash", lambda: "physics-hash")
    monkeypatch.setattr(mot_3d_campaign, "_dirty_relevant_files", lambda: ())
    root = tmp_path / "campaign"
    mot_3d_campaign.create(Namespace(
        name="early", input_dir=str(input_dir),
        upstream_campaign=str(upstream_campaign), output_dir=str(root),
    ))
    calls = []
    with pytest.raises(RuntimeError, match="blocked at stage"):
        mot_3d_campaign.submit_discovery(root, qsub=lambda command: calls.append(command))
    assert calls == []
    assert not (root / "discovery_submission.json").exists()

    manifest_path = root / "campaign.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["stage"] = "discovery"
    manifest_path.write_text(json.dumps(manifest))
    identifiers = iter([f"{index}[].zeus" for index in range(5)])
    result = mot_3d_campaign.submit_discovery(
        root, qsub=lambda command: next(identifiers)
    )
    assert result["status"] == "submitted"


def test_role_loader_uses_only_frozen_role_and_balances_particles(
    input_dir, tmp_path, monkeypatch
):
    roles = mot_3d_campaign.freeze_inputs(input_dir)
    manifest = tmp_path / "campaign.json"
    manifest.write_text(json.dumps({
        "provenance": {"git_commit": "abc", "physical_model_sha256": "hash"},
        "upstream_2d_campaign": {"sealed_seed_pairs": [
            {"zeeman_seed": row["zeeman_seed"], "mot_seed": row["mot_seed"]}
            for rows in roles.values() for row in rows
        ]},
        "input_roles": roles,
    }))
    monkeypatch.setattr(mot_3d_campaign, "_revision", lambda: "abc")
    monkeypatch.setattr(mot_3d_campaign, "_relevant_hash", lambda: "hash")
    states, ensemble_ids, provenance = mot_3d_campaign.load_role_particles(
        manifest, "refinement", 7, 123
    )
    assert states.shape == (28, 6)
    assert np.bincount(ensemble_ids).tolist() == [7, 7, 7, 7]
    assert [row["zeeman_seed"] for row in provenance] == list(range(3027, 3031))


def test_selection_stage_submission_records_array_and_merge_ids(tmp_path):
    root = tmp_path / "campaign"
    root.mkdir()
    (root / "campaign.json").write_text(json.dumps({
        "stage": "refinement",
        "stages": {"refinement": {
            "worker_jobs": {family: f"{family}.pbs" for family in mot_3d_campaign.FAMILIES},
            "merge_jobs": {family: f"{family}_merge.pbs" for family in mot_3d_campaign.FAMILIES},
        }},
    }))
    commands = []
    identifiers = iter(["11[].zeus", "12.zeus", "21[].zeus", "22.zeus"])
    def fake_qsub(command):
        commands.append(command)
        return next(identifiers)
    record = mot_3d_campaign.submit_selection_stage(root, qsub=fake_qsub)
    assert record["status"] == "submitted"
    assert commands[1][2] == "depend=afterok:11[].zeus"
    assert record["families"]["single_pass"]["merge_job_id"] == "22.zeus"


def test_selection_stage_partial_failure_preserves_submitted_array_id(tmp_path):
    root = tmp_path / "campaign"
    root.mkdir()
    (root / "campaign.json").write_text(json.dumps({
        "stage": "refinement",
        "stages": {"refinement": {
            "worker_jobs": {family: f"{family}.pbs" for family in mot_3d_campaign.FAMILIES},
            "merge_jobs": {family: f"{family}_merge.pbs" for family in mot_3d_campaign.FAMILIES},
        }},
    }))
    calls = 0
    def fake_qsub(command):
        nonlocal calls
        calls += 1
        if calls == 1:
            return "11[].zeus"
        raise RuntimeError("merge submission failed")
    with pytest.raises(RuntimeError, match="merge submission failed"):
        mot_3d_campaign.submit_selection_stage(root, qsub=fake_qsub)
    record = json.loads((root / "refinement_submission.json").read_text())
    assert record["status"] == "partial_failure"
    assert record["families"]["angled_donut"]["array_job_id"] == "11[].zeus"
    assert record["families"]["angled_donut"]["merge_job_id"] is None


def test_artifact_registry_rejects_duplicate_stems(tmp_path):
    candidates = [{"candidate_id": "candidate_00"}]
    npz_a = tmp_path / "a" / "candidate_00_seed_1.npz"
    npz_b = tmp_path / "b" / "candidate_00_seed_1.npz"
    npz_a.parent.mkdir()
    npz_b.parent.mkdir()
    np.savez(npz_a, usable_at_end=[True], usable_ever=[True], ensemble_ids=[0])
    np.savez(npz_b, usable_at_end=[True], usable_ever=[True], ensemble_ids=[0])
    json_a = npz_a.with_suffix(".json")
    json_b = npz_b.with_suffix(".json")
    json_a.write_text("{}")
    json_b.write_text("{}")
    with pytest.raises(RuntimeError, match="duplicated"):
        validate_artifact_registry(
            [json_a, json_b], [npz_a, npz_b], candidates=candidates,
            recoil_seeds=(1,), kind="result", family="angled_donut",
        )


def test_simultaneous_intervals_cover_all_centered_bootstrap_coordinates():
    bootstrap = np.array([[0.1, 0.4], [0.3, 0.2], [0.2, 0.3], [0.4, 0.1]])
    means = bootstrap.mean(axis=0)
    lower, upper, critical = simultaneous_intervals(bootstrap, means, alpha=0.25)
    standard_errors = bootstrap.std(axis=0, ddof=1)
    studentized = np.abs((bootstrap - means) / standard_errors)
    expected_critical = np.quantile(studentized.max(axis=1), 0.75)
    assert critical == pytest.approx(expected_critical)
    assert np.allclose(lower, means - critical * standard_errors)
    assert np.allclose(upper, means + critical * standard_errors)


def test_stage_design_changes_with_particle_sampling_identity(tmp_path):
    frozen_input = tmp_path / "input.npy"
    selection = tmp_path / "selection.json"
    manifest = tmp_path / "campaign.json"
    np.save(frozen_input, np.zeros((2, 6)))
    selection.write_text(json.dumps({"candidates": []}))
    manifest.write_text(json.dumps({
        "provenance": {"git_commit": "abc", "physical_model_sha256": "physics"},
        "design": {"solver": "RK4StHybridCustom"},
        "input_roles": {"refinement": [{"path": str(frozen_input)}]},
    }))
    provenance = [{"file": str(frozen_input), "selected_indices": [0]}]
    first = frozen_stage_design(
        manifest, selection, "refinement", 1.25e-6, 0.1,
        particle_selection=provenance, particles_per_ensemble=1, selection_seed=10,
    )
    changed_seed = frozen_stage_design(
        manifest, selection, "refinement", 1.25e-6, 0.1,
        particle_selection=provenance, particles_per_ensemble=1, selection_seed=11,
    )
    changed_provenance = frozen_stage_design(
        manifest, selection, "refinement", 1.25e-6, 0.1,
        particle_selection=[{"file": str(frozen_input), "selected_indices": [1]}],
        particles_per_ensemble=1, selection_seed=10,
    )
    assert first != changed_seed
    assert first["particle_selection_sha256"] != changed_provenance["particle_selection_sha256"]


def test_timestep_gate_requires_exact_approved_frozen_design(tmp_path):
    root = tmp_path / "campaign"
    root.mkdir()
    (root / "campaign.json").write_text(json.dumps({
        "stage": "dt_validation_required",
        "design": {
            "screening_dt_s": 1.25e-6, "production_dt_s": 0.625e-6,
            "dt_validation_reference_s": 0.3125e-6,
            "dt_validation_candidates_s": [2.5e-6, 1.25e-6, 0.625e-6],
            "timestep_status": "provisional_pending_3d_validation",
        },
    }))
    evidence = tmp_path / "dt.json"
    evidence.write_text(json.dumps({
        "kind": "mot_3d_timestep_validation", "status": "approved",
        "screening_dt_s": 1.25e-6, "production_dt_s": 0.625e-6,
        "reference_dt_s": 0.3125e-6,
        "tested_dt_s": [2.5e-6, 1.25e-6, 0.625e-6],
        "capture_bias_passed": True, "paired_decision_passed": True,
    }))
    mot_3d_campaign.approve_timestep(
        Namespace(campaign=str(root), evidence=str(evidence))
    )
    updated = json.loads((root / "campaign.json").read_text())
    assert updated["stage"] == "discovery"
    assert updated["design"]["timestep_evidence"]["sha256"]


def test_timestep_gate_rejects_wrong_production_dt(tmp_path):
    root = tmp_path / "campaign"
    root.mkdir()
    (root / "campaign.json").write_text(json.dumps({
        "stage": "dt_validation_required",
        "design": {
            "screening_dt_s": 1.25e-6, "production_dt_s": 0.625e-6,
            "dt_validation_reference_s": 0.3125e-6,
            "dt_validation_candidates_s": [1.25e-6, 0.625e-6],
        },
    }))
    evidence = tmp_path / "dt.json"
    evidence.write_text(json.dumps({
        "kind": "mot_3d_timestep_validation", "status": "approved",
        "screening_dt_s": 1.25e-6, "production_dt_s": 1.25e-6,
        "reference_dt_s": 0.3125e-6,
        "tested_dt_s": [1.25e-6, 0.625e-6],
        "capture_bias_passed": True, "paired_decision_passed": True,
    }))
    with pytest.raises(ValueError, match="does not approve"):
        mot_3d_campaign.approve_timestep(
            Namespace(campaign=str(root), evidence=str(evidence))
        )
