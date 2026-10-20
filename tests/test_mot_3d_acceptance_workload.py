"""Explicit test workloads keep canonical physics and scientific defaults intact."""

from argparse import Namespace
from copy import deepcopy
from pathlib import Path

import pytest

from workflow_api.acceptance_profile import load_acceptance_profile
from workflow_api import mot_3d_workload as workload
from studies.mot_3d_campaign import render_discovery_jobs, render_selection_stage_jobs
from workflow_api.mot_3d_final_input_results import expected_paths


def manifest():
    from studies.mot_3d_campaign import build_campaign_manifest

    return build_campaign_manifest(
        name="disposable",
        input_directory="data/acceptance/survivors",
        upstream={},
        roles={},
        revision="a" * 40,
        physical_model_sha256="b" * 64,
        acceptance_profile_id="ui_acceptance_v1",
    )


def test_profile_discovery_uses_normal_round_topology_and_small_workload():
    value = manifest()
    before = deepcopy(value)
    files, _, rounds, _ = render_discovery_jobs(
        Path("data/optimization/mot_3d/ui_acceptance/disposable"),
        "a" * 40,
        Path("data/acceptance/survivors"),
        manifest=value,
    )
    assert {key: len(rows) for key, rows in rounds.items()} == {
        "angled_donut": 2,
        "single_pass": 3,
    }
    for name, text in files.items():
        if name.endswith(".pbs"):
            assert (
                f"#PBS -l select=1:ncpus={workload.stage(value, 'discovery')['ncpus']}:mem=4gb"
                in text
            )
            assert "#PBS -l walltime=01:00:00" in text
            assert "cd ~/ytterbium_lab_simulation_ui_acceptance" in text
            assert "source ~/venvs/atomsmltr-ui-test/bin/activate" in text
            assert "cd ~/ytterbium_lab_simulation_new" not in text
            assert (
                f"--particles-per-ensemble 1 --npools {workload.stage(value, 'discovery')['npools']}"
                in text
            )
            assert "--dt 1e-05 --t-max 0.05" in text
    assert "targets=(4 4 4)" in files["jobs/angled_donut/round_02.pbs"]
    assert "targets=(4 4 4)" in files["jobs/single_pass/round_03.pbs"]
    assert value == before


@pytest.mark.parametrize("stage", ["preliminary_check", "refinement", "closure"])
def test_selection_rendering_and_review_science_use_same_profile(stage):
    value = manifest()
    files = render_selection_stage_jobs(
        Path("data/optimization/mot_3d/ui_acceptance/disposable"),
        value,
        stage,
        {
            family: Path(f"selection/{family}.json")
            for family in ("angled_donut", "single_pass")
        },
        "preliminary_check" if stage == "preliminary_check" else "refinement",
        750,
        61001,
        62001,
    )
    for family in files.values():
        assert "--particles-per-ensemble 1" in family["array"]
        assert f"--npools {workload.stage(value, stage)['npools']}" in family["array"]
        for kind, text in family.items():
            key = "ncpus" if kind == "array" else "merge_ncpus"
            assert f"ncpus={workload.stage(value, stage)[key]}:mem=4gb" in text
            assert "walltime=01:00:00" in text
    science = workload.submission_science(
        value,
        stage,
        {"input_ensembles": 4, "particles_per_ensemble": 750, "total_particles": 3000},
    )
    assert science["particles_per_ensemble"] == 1 and science["total_particles"] == 4
    assert (
        workload.topology(value, stage).array_ncpus
        == workload.stage(value, stage)["ncpus"]
    )


def test_scientific_workload_is_byte_identical_and_rejects_mixed_marker():
    value = manifest()
    value["kind"] = "mot_3d_campaign_v2"
    del value["acceptance"]
    text = "#PBS -l select=1:ncpus=200:mem=64gb\n--npools 200 --particles-per-ensemble 750\n"
    assert workload.rendered_job(text, value, "refinement") == text
    assert workload.particles_per_ensemble(value, "refinement", 750) == 750
    assert workload.topology(value, "refinement").array_ncpus == 200
    value["acceptance"] = load_acceptance_profile().provenance()
    with pytest.raises(ValueError):
        workload.rendered_job(text, value, "refinement")


def test_fresh_validation_registry_names_reflect_real_profile_particle_count():
    paths = expected_paths(manifest())
    assert len(paths) == 101
    assert (
        "final_validation_inputs/after_zeeman/production_zeeman_n32_dt40us_seed3035.npy"
        in paths
    )
    assert not any("n50000" in path for path in paths)
    assert any("n50000" in path for path in expected_paths())


def test_acceptance_location_and_science_cannot_be_crossed():
    value = manifest()
    workload.validate_location(
        value, "data/optimization/mot_3d/ui_acceptance/disposable"
    )
    with pytest.raises(ValueError):
        workload.validate_location(value, "data/optimization/mot_3d/disposable")
    value["kind"] = "mot_3d_campaign_v2"
    del value["acceptance"]
    with pytest.raises(ValueError):
        workload.validate_location(
            value, "data/optimization/mot_3d/ui_acceptance/disposable"
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("solver", "other"),
        ("screening_dt_s", 2e-5),
        ("production_dt_s", 1e-5),
        ("t_max_s", 0.001),
        ("families", ["single_pass"]),
        ("optimization_bounds", {}),
        ("selection_statistics", {}),
    ],
)
def test_authenticated_profile_cannot_override_frozen_physics(field, value):
    model = manifest()
    model["design"][field] = value
    with pytest.raises(ValueError, match="physical design"):
        workload.stage(model, "discovery")
    with pytest.raises(ValueError, match="physical design"):
        workload.rendered_job("--npools 200", model, "discovery")


@pytest.mark.parametrize("family", ["angled_donut", "single_pass"])
def test_zero_discovery_still_selects_unique_deterministic_candidates(family):
    from studies.mot_3d.discovery.select import parameter_bounds, select_candidates

    bounds = parameter_bounds(family)
    rows = []
    for worker in range(3):
        for trial in range(4):
            fraction = (worker * 4 + trial + 1) / 14
            rows.append(
                {
                    "worker_index": worker,
                    "trial_number": trial,
                    "usable_at_end_fraction": 0.0,
                    "usable_at_end_count": 0,
                    "parameters": {
                        key: low + fraction * (high - low)
                        for key, (low, high) in bounds.items()
                    },
                    "resolved_profile": {},
                }
            )
    first = select_candidates({"ranked_trials": rows}, family)
    assert first == select_candidates({"ranked_trials": rows}, family)
    assert first["selected_candidate_count"] == 12
    assert (
        len({(row["worker_index"], row["trial_number"]) for row in first["candidates"]})
        == 12
    )
    assert all(
        row["discovery_usable_at_end_fraction"] == 0
        and row["discovery_usable_at_end_count"] == 0
        for row in first["candidates"]
    )


def test_profile_and_workload_are_in_the_campaign_revision_freeze():
    from studies.mot_3d_campaign import relevant_files

    assert {
        "workflow_api/mot_3d_workload.py",
        "workflow_api/acceptance_inputs.py",
        "workflow_api/acceptance_profile.py",
        "workflow_api/specifications/ui_acceptance_v1.json",
    } <= set(relevant_files())


def test_nested_manifest_edits_cannot_mutate_the_canonical_design():
    value = manifest()
    key = next(iter(value["design"]["optimization_bounds"]))
    value["design"]["optimization_bounds"][key] = {}
    with pytest.raises(ValueError, match="physical design"):
        workload.policy(value)
    assert workload.policy(manifest()) is not None


def test_dirty_acceptance_workload_files_are_caught_by_normal_revision_freeze(
    tmp_path, monkeypatch
):
    import subprocess
    from studies.mot_3d_campaign import _dirty_relevant_files

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    names = (
        "workflow_api/mot_3d_workload.py",
        "workflow_api/acceptance_inputs.py",
        "workflow_api/acceptance_profile.py",
        "workflow_api/specifications/ui_acceptance_v1.json",
    )
    for name in names:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("changed acceptance workload")
    monkeypatch.chdir(tmp_path)
    assert set(names) <= set(_dirty_relevant_files())


def test_frozen_acceptance_sources_cannot_alias_scientific_lineage_or_paths():
    from workflow_api.mot_3d_preliminary_results import (
        validate_frozen_role_records,
        PreliminaryResultError,
    )

    marker = load_acceptance_profile().provenance()
    project = "/home/test/ytterbium_lab_simulation_ui_acceptance"
    source = f"{project}/data/acceptance/source/ensemble.npy"
    record = {
        "path": source,
        "metadata_path": source.removesuffix(".npy") + ".json",
        "sha256": "a" * 64,
        "metadata_sha256": "b" * 64,
        "n_survivors": 2,
        "shape": [2, 6],
        "dtype": "float64",
        "zeeman_seed": 3015,
        "mot_seed": 43015,
        "source_git_commit": "c" * 40,
        "source_design": {"acceptance": marker},
        "source_parameters": {},
    }
    options = {
        "project_directory": project,
        "expected_zeeman_seeds": (3015,),
        "source_git_commit": "c" * 40,
    }
    assert validate_frozen_role_records(
        [record], **options, acceptance_provenance=marker
    ) == [record]
    with pytest.raises(PreliminaryResultError):
        validate_frozen_role_records([record], **options)
    mixed = deepcopy(record)
    mixed["source_design"] = {}
    with pytest.raises(PreliminaryResultError):
        validate_frozen_role_records([mixed], **options, acceptance_provenance=marker)
    production_path = deepcopy(record)
    production_path["path"] = f"{project}/data/particle_states/production.npy"
    production_path["metadata_path"] = f"{project}/data/particle_states/production.json"
    with pytest.raises(PreliminaryResultError):
        validate_frozen_role_records(
            [production_path], **options, acceptance_provenance=marker
        )


@pytest.mark.parametrize(
    "project",
    [
        "/home/test/ytterbium_lab_simulation_new",
        "/home/test/ytterbium_lab_simulation_ui_acceptance",
    ],
)
@pytest.mark.parametrize("kind", [None, "unknown_campaign"])
def test_real_receiver_authentication_never_accepts_missing_or_unknown_kind(
    project, kind
):
    value = {} if kind is None else {"kind": kind}
    with pytest.raises(ValueError):
        workload.assert_receiver_target(
            value, "test", project, "data/optimization/mot_3d/example"
        )
    if kind is not None or project.endswith("ui_acceptance"):
        with pytest.raises(ValueError):
            workload.assert_receiver_target(
                value,
                "test",
                project,
                "data/optimization/mot_3d/example",
                trusted_root_override=Path("/private/tmp/explicit-fixture"),
            )


def test_kindless_legacy_projection_requires_explicit_scientific_fixture_override():
    workload.assert_receiver_target(
        {},
        "test",
        "/home/test/ytterbium_lab_simulation_new",
        "data/optimization/mot_3d/example",
        trusted_root_override=Path("/private/tmp/explicit-fixture"),
    )


def test_acceptance_physical_worker_rejects_unversioned_arguments_before_running():
    import json
    import tempfile
    from config import DEFAULT_RANDOM_SEED

    root = Path(__file__).resolve().parents[1]
    base = root / "data/acceptance"
    base.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=base, prefix="worker-contract-") as directory:
        folder = Path(directory)
        path = folder / "campaign.json"
        value = manifest()
        path.write_text(json.dumps(value))
        args = Namespace(
            output_dir=str(folder / "results"),
            npools=workload.stage(value, "discovery")["npools"],
            dt=1e-5,
            t_max=0.05,
            particles_per_ensemble=1,
            worker_index=0,
            family="angled_donut",
            target_completed_trials=4,
            sampler_seed=271001,
            input_role="discovery",
            startup_trials=24,
            selection_seed=DEFAULT_RANDOM_SEED,
            simulation_seed=DEFAULT_RANDOM_SEED,
        )
        workload.validate_worker(args, path, "discovery")
        for field, value in [
            ("target_completed_trials", 100),
            ("npools", 2),
            ("t_max", 0.1),
            ("sampler_seed", 999),
            ("input_role", "refinement"),
        ]:
            invalid = deepcopy(args)
            setattr(invalid, field, value)
            with pytest.raises(ValueError):
                workload.validate_worker(invalid, path, "discovery")
        assert not (folder / "results").exists()


@pytest.mark.parametrize("acceptance", [False, True])
def test_discovery_review_matches_exact_frozen_job_bytes_and_rejects_resource_drift(
    acceptance,
):
    model = manifest()
    if not acceptance:
        model["kind"] = "mot_3d_campaign_v2"
        del model["acceptance"]
    relative = (
        "data/optimization/mot_3d/"
        + ("ui_acceptance/" if acceptance else "")
        + model["name"]
    )
    rendered, _, _, _ = render_discovery_jobs(
        Path(relative),
        "a" * 40,
        model["input_directory"],
        command_campaign=Path(relative),
        command_input=Path(model["input_directory"]),
        manifest=model,
    )
    raw = {name: text.encode() for name, text in rendered.items()}
    workload.validate_discovery_job_bytes(model, "a" * 40, relative, raw)
    resources, science = workload.discovery_review(model)
    assert resources["array"]["ncpus_per_task"] == (
        workload.stage(model, "discovery")["ncpus"] if acceptance else 200
    )
    assert science["total_particles_per_trial"] == (12 if acceptance else 600)
    assert science["total_trials"] == (24 if acceptance else 950)
    assert science["dt_s"] == 1e-5 and science["t_max_s"] == 0.05
    for token in (b"--npools ", b"ncpus="):
        changed = dict(raw)
        name = "jobs/angled_donut/round_01.pbs"
        changed[name] = changed[name].replace(token, token + b"9", 1)
        with pytest.raises(ValueError, match="reviewed workload"):
            workload.validate_discovery_job_bytes(model, "a" * 40, relative, changed)


@pytest.mark.parametrize(
    "name,npools,ncpus", [("zeeman", 1, 1), ("mot_2d", 10, 10), ("freeze", 1, 1)]
)
def test_generation_renderer_uses_each_jobs_reviewed_resource_contract(
    monkeypatch, name, npools, ncpus
):
    value = manifest()
    descriptor = {
        "npools": npools,
        "ncpus": ncpus,
        "memory_gb": 4,
        "walltime_seconds": 3600,
    }
    # Resource unit fixture only: the manifest and physical design remain authenticated.
    monkeypatch.setattr(
        workload,
        "generation_job",
        lambda manifest, job_name: descriptor if job_name == name else None,
    )
    raw = "#PBS -l select=1:ncpus=200:mem=64gb\n#PBS -l walltime=12:00:00\nset -euo pipefail\ncd ~/ytterbium_lab_simulation_new\npython -m ordinary_physical_worker --npools 200\n"
    rendered = workload.rendered_generation_job(raw, value, name)
    assert f"select=1:ncpus={ncpus}:mem=4gb" in rendered
    assert f"--npools {npools}" in rendered
    assert "walltime=01:00:00" in rendered
    assert "ordinary_physical_worker" in rendered
    assert "TEST ONLY" in rendered


def test_frozen_final_input_jobs_and_review_match_generation_policy(monkeypatch):
    from studies.mot_3d_campaign import render_final_validation_input_transition
    import studies.mot_3d.discovery.optimize as optimizer

    value = manifest()
    value["stage"] = "finalist_selection"
    value["upstream_2d_campaign"] = {
        "expected_survivor_parameters": {
            "s0": 1.3,
            "detuning_gamma": -1.0,
            "magnet_radius": 0.046,
        },
        "expected_survivor_design": {"zeeman_profile": "corrected"},
    }
    # Geometry rendering unit fixture, not a simulated or submitted campaign.
    monkeypatch.setattr(
        optimizer,
        "build_profile_from_parameters",
        lambda family, parameters: ({"family": family}, parameters, {}),
    )
    summaries = {
        family: {
            "kind": "merged_mot_3d_finalist_selection",
            "family": family,
            "ranked_candidates": [
                {"candidate_id": f"{family}_{i}", "parameters": {}} for i in range(3)
            ],
        }
        for family in ("angled_donut", "single_pass")
    }
    root = f"data/optimization/mot_3d/ui_acceptance/{value['name']}"
    files, updated = render_final_validation_input_transition(
        root, value, summaries, {family: "a" * 64 for family in summaries}, "b" * 64
    )
    review = workload.generation_science(value, {})
    assert review["npools"] == 10
    for filename, name in [
        ("01_generate_zeeman.pbs", "zeeman"),
        ("02_generate_2d_survivors.pbs", "mot_2d"),
        ("03_freeze_inputs.pbs", "freeze"),
    ]:
        job = workload.generation_job(value, name)
        text = files[f"jobs/final_validation_inputs/{filename}"].decode()
        assert f"#PBS -l select=1:ncpus={job['ncpus']}:mem=4gb:vnode=gd002" in text
        assert "#PBS -l walltime=01:00:00" in text
        assert review["resources"][name] == {
            "ncpus": job["ncpus"],
            "memory_gb": 4,
            "walltime": "01:00:00",
            "vnode": "gd002",
        }
        if name != "freeze":
            assert f"--npools {job['npools']}" in text
            assert (
                f"--acceptance-profile ui_acceptance_v1 --input-manifest {root}/campaign.json"
                in text
            )
    assert updated["acceptance"] == value["acceptance"]
    assert updated["stage"] == "final_validation_input_generation"
