"""Paired 3D-MOT timestep convergence on frozen canonical 2D survivors."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import time
from pathlib import Path

import numpy as np

from config import MOT_3D_SIM_CONFIG
from simulations.mot_3d import mot_3d_simulation
from studies.mot_3d.analysis.retention import analyze_results
from studies.mot_3d.discovery.optimize import build_profile_from_parameters
from studies.mot_3d_campaign import load_role_particles
from utils.file_helpers import save_file_json


FAMILIES = ("angled_donut", "single_pass")
RECOIL_SEEDS = (47001, 47002, 47003, 47004, 47005)
ANCHORS_PER_FAMILY = 3
PARTICLES_PER_ENSEMBLE = 30
BOOTSTRAP_REPLICATES = 20_000
SCREENING_TOLERANCE = 0.005
PRODUCTION_TOLERANCE = 0.0025
DISAGREEMENT_TOLERANCE = 0.020
T_MAX_S = 0.1
EVIDENCE_FORMAT_VERSION = 1

SENTINEL_PARAMETERS = {
    "angled_donut": (
        dict(green_s0=30.0, green_detuning_gamma=-25.0, green_waist_m=0.0075,
             blue_s0=1.5, blue_waist_m=0.0075, magnetic_gradient_G_cm=2.5,
             blue_detuning_gamma=-3.0, core_shell_split_radius_m=0.0030),
        dict(green_s0=150.0, green_detuning_gamma=-5.0, green_waist_m=0.003,
             blue_s0=1.5, blue_waist_m=0.003, magnetic_gradient_G_cm=100.0,
             blue_detuning_gamma=-0.5, core_shell_split_radius_m=0.0010),
        dict(green_s0=8.0, green_detuning_gamma=-12.0, green_waist_m=0.006,
             blue_s0=0.25, blue_waist_m=0.006, magnetic_gradient_G_cm=5.0,
             blue_detuning_gamma=-2.0, core_shell_split_radius_m=0.0040),
    ),
    "single_pass": (
        dict(green_s0=30.0, green_detuning_gamma=-25.0, green_waist_m=0.0075,
             blue_s0=0.25, blue_waist_m=0.0075, magnetic_gradient_G_cm=2.5,
             blue_detuning_anchor_gamma=-2.75, blue_crossing_angle_deg=45.0,
             blue_crossing_z_offset_m=-0.050),
        dict(green_s0=150.0, green_detuning_gamma=-5.0, green_waist_m=0.003,
             blue_s0=1.5, blue_waist_m=0.003, magnetic_gradient_G_cm=100.0,
             blue_detuning_anchor_gamma=-1.75, blue_crossing_angle_deg=70.0,
             blue_crossing_z_offset_m=-0.040),
        dict(green_s0=8.0, green_detuning_gamma=-12.0, green_waist_m=0.006,
             blue_s0=0.20, blue_waist_m=0.006, magnetic_gradient_G_cm=5.0,
             blue_detuning_anchor_gamma=-2.5, blue_crossing_angle_deg=55.0,
             blue_crossing_z_offset_m=-0.045),
    ),
}


def _root(campaign):
    return Path(campaign).resolve()


def _manifest(campaign):
    path = _root(campaign) / "campaign.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("kind") != "mot_3d_campaign_v2":
        raise ValueError("Unexpected 3D campaign manifest kind.")
    if payload.get("stage") != "dt_validation_required":
        raise RuntimeError("Campaign is not awaiting timestep validation.")
    return path, payload


def _tasks(manifest):
    design = manifest["design"]
    timesteps = [*design["dt_validation_candidates_s"], design["dt_validation_reference_s"]]
    return [
        {
            "task_index": index,
            "family": family,
            "anchor_index": anchor,
            "recoil_seed": recoil_seed,
            "dt_s": dt,
        }
        for index, (family, anchor, recoil_seed, dt) in enumerate(
            (family, anchor, recoil_seed, dt)
            for family in FAMILIES
            for anchor in range(ANCHORS_PER_FAMILY)
            for recoil_seed in RECOIL_SEEDS
            for dt in timesteps
        )
    ]


def _atomic_npz(path, **arrays):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.npz")
    np.savez_compressed(temporary, **arrays)
    with temporary.open("rb") as stream:
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_sha256(payload):
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _load_balanced_all_inputs(manifest_path):
    states, ensemble_ids, provenance = [], [], []
    offset = 0
    for role in ("discovery", "refinement", "preliminary_check"):
        role_states, role_ids, role_provenance = load_role_particles(
            manifest_path, role, PARTICLES_PER_ENSEMBLE, 57001
        )
        states.append(role_states)
        ensemble_ids.append(role_ids + offset)
        provenance.extend(
            {"role": role, **row, "ensemble_id": offset + index}
            for index, row in enumerate(role_provenance)
        )
        offset += len(role_provenance)
    combined = np.concatenate(states)
    combined_ids = np.concatenate(ensemble_ids)
    if len(provenance) != 20 or len(combined) != 20 * PARTICLES_PER_ENSEMBLE:
        raise AssertionError("Timestep validation must balance all 20 frozen ensembles.")
    return combined, combined_ids, provenance


def _task_design(manifest_path, manifest, task, provenance, parameters, profile, derived):
    return {
        "format_version": EVIDENCE_FORMAT_VERSION,
        "campaign_manifest": str(Path(manifest_path).resolve()),
        "campaign_manifest_sha256": _sha256(manifest_path),
        "campaign_commit": manifest["provenance"]["git_commit"],
        "physical_model_sha256": manifest["provenance"]["physical_model_sha256"],
        "task": task,
        "parameters": parameters,
        "derived_parameters": derived,
        "profile_sha256": _json_sha256(profile),
        "particle_selection": provenance,
        "particle_selection_sha256": _json_sha256(provenance),
        "solver": manifest["design"]["solver"],
        "t_max_s": T_MAX_S,
        "input_particle_count": 20 * PARTICLES_PER_ENSEMBLE,
    }


def _validate_completed_task(json_path, npz_path, expected_design):
    if not json_path.exists() and not npz_path.exists():
        return False
    if not json_path.exists() or not npz_path.exists():
        raise RuntimeError(f"Partial timestep result requires inspection: {json_path}")
    row = json.loads(json_path.read_text(encoding="utf-8"))
    if row.get("kind") != "mot_3d_timestep_validation_task" or row.get("design") != expected_design:
        raise RuntimeError(f"Stale or foreign timestep result: {json_path}")
    if row.get("outcomes") != str(npz_path) or row.get("outcomes_sha256") != _sha256(npz_path):
        raise RuntimeError(f"Timestep outcome registry mismatch: {json_path}")
    with np.load(npz_path) as arrays:
        if set(arrays.files) != {"captured", "usable_ever", "ensemble_ids"}:
            raise RuntimeError(f"Unexpected timestep outcome schema: {npz_path}")
        expected_count = expected_design["input_particle_count"]
        captured = np.asarray(arrays["captured"])
        usable_ever = np.asarray(arrays["usable_ever"])
        ids = np.asarray(arrays["ensemble_ids"])
    if any(array.shape != (expected_count,) for array in (captured, usable_ever, ids)):
        raise RuntimeError(f"Unexpected timestep outcome shape: {npz_path}")
    if captured.dtype != np.bool_ or usable_ever.dtype != np.bool_:
        raise RuntimeError(f"Timestep outcome masks must be boolean: {npz_path}")
    if not np.issubdtype(ids.dtype, np.integer) or not np.array_equal(
        np.bincount(ids, minlength=20), np.full(20, PARTICLES_PER_ENSEMBLE)
    ):
        raise RuntimeError(f"Unexpected timestep ensemble balance: {npz_path}")
    if row.get("input_particle_count") != expected_count:
        raise RuntimeError(f"Timestep input count mismatch: {json_path}")
    if row.get("captured_count") != int(captured.sum()) or row.get("usable_ever_count") != int(usable_ever.sum()):
        raise RuntimeError(f"Timestep summary count mismatch: {json_path}")
    if not np.isclose(row.get("capture_fraction", -1.0), captured.mean(), rtol=0.0, atol=1e-15):
        raise RuntimeError(f"Timestep capture fraction mismatch: {json_path}")
    for name in ("peak_usable_count", "entered_capture_region_count", "slow_inside_count"):
        value = row.get(name)
        if not isinstance(value, int) or not 0 <= value <= expected_count:
            raise RuntimeError(f"Invalid {name}: {json_path}")
    if not np.isfinite(float(row.get("runtime_s", float("nan")))):
        raise RuntimeError(f"Invalid timestep runtime: {json_path}")
    return True


def prepare(campaign):
    root = _root(campaign)
    _, manifest = _manifest(root)
    tasks = _tasks(manifest)
    work = root / "dt_validation"
    work.mkdir(parents=True, exist_ok=True)
    save_file_json(work / "tasks.json", {
        "kind": "mot_3d_timestep_validation_tasks",
        "campaign": str(root),
        "particles_per_ensemble": PARTICLES_PER_ENSEMBLE,
        "recoil_seeds": list(RECOIL_SEEDS),
        "anchors_per_family": ANCHORS_PER_FAMILY,
        "t_max_s": T_MAX_S,
        "screening_absolute_bias_tolerance": SCREENING_TOLERANCE,
        "production_absolute_bias_tolerance": PRODUCTION_TOLERANCE,
        "classification_disagreement_tolerance": DISAGREEMENT_TOLERANCE,
        "tasks": tasks,
    })
    revision = manifest["provenance"]["git_commit"]
    project_root = Path(__file__).resolve().parents[2]
    observed_revision = subprocess.check_output(
        ["git", "-C", str(project_root), "rev-parse", "HEAD"], text=True
    ).strip()
    if observed_revision != revision:
        raise RuntimeError(
            f"Repository HEAD {observed_revision} does not match campaign commit {revision}."
        )
    quoted_project = shlex.quote(str(project_root))
    quoted_campaign = shlex.quote(str(root))
    scratch = (
        'RUN_TMP="/tmp/${USER}_m3d_dt_${PBS_JOBID}_${PBS_ARRAY_INDEX:-merge}"\n'
        'mkdir -p "$RUN_TMP"\nexport TMPDIR="$RUN_TMP" TMP="$RUN_TMP" TEMP="$RUN_TMP"\n'
        "trap 'rm -rf -- \"$RUN_TMP\"' EXIT\n"
    )
    job = work / "run.pbs"
    job_text = (
        "#!/bin/bash\n"
        "#PBS -N m3d_dt_pair\n#PBS -q zeus_combined_q\n"
        f"#PBS -J 0-{len(tasks)-1}%3\n"
        "#PBS -l select=1:ncpus=200:mem=64gb\n#PBS -l walltime=24:00:00\n"
        f"set -euo pipefail\ncd {quoted_project}\n"
        "module load SPACK/apps\nmodule load gcc/14.1.0\nmodule load python/3.14.2\n"
        "source ~/venvs/atomsmltr/bin/activate\n"
        + scratch
        +
        f"test \"$(git rev-parse HEAD)\" = \"{revision}\" || exit 42\n"
        f"python -u -m studies.mot_3d.timestep_validation run-task --campaign {quoted_campaign} --task-index \"$PBS_ARRAY_INDEX\"\n"
    )
    job.write_text(job_text, encoding="utf-8")
    merge = work / "merge.pbs"
    merge_text = (
        "#!/bin/bash\n#PBS -N m3d_dt_merge\n#PBS -q zeus_combined_q\n"
        "#PBS -l select=1:ncpus=1:mem=8gb\n#PBS -l walltime=01:00:00\n"
        f"set -euo pipefail\ncd {quoted_project}\n"
        "module load SPACK/apps\nmodule load gcc/14.1.0\nmodule load python/3.14.2\n"
        "source ~/venvs/atomsmltr/bin/activate\n"
        + scratch
        +
        f"test \"$(git rev-parse HEAD)\" = \"{revision}\" || exit 42\n"
        f"python -u -m studies.mot_3d.timestep_validation merge --campaign {quoted_campaign}\n"
    )
    merge.write_text(merge_text, encoding="utf-8")
    print(f"Prepared {len(tasks)} paired timestep tasks.")
    print(f"Array job: {job}")


def run_task(campaign, task_index):
    root = _root(campaign)
    manifest_path, manifest = _manifest(root)
    tasks_payload = json.loads((root / "dt_validation/tasks.json").read_text())
    task = tasks_payload["tasks"][task_index]
    family = task["family"]
    states, ensemble_ids, provenance = _load_balanced_all_inputs(manifest_path)
    parameters = dict(SENTINEL_PARAMETERS[family][task["anchor_index"]])
    profile, parameters, derived = build_profile_from_parameters(family, parameters)
    design = _task_design(
        manifest_path, manifest, task, provenance, parameters, profile, derived
    )
    result_dir = root / "dt_validation/results"
    stem = f"task_{task_index:03d}"
    json_path = result_dir / f"{stem}.json"
    outcome = result_dir / f"{stem}.npz"
    if _validate_completed_task(json_path, outcome, design):
        print(f"Skipping completed timestep task {task_index}")
        return
    start = time.monotonic()
    trajectories, _ = mot_3d_simulation(
        states, _3d_mot_config=profile, gravity_enabled=True, npools=200,
        dt=task["dt_s"], t_max=T_MAX_S, seed=task["recoil_seed"],
    )
    time_points = np.linspace(
        0.0, T_MAX_S,
        int(np.ceil(T_MAX_S / task["dt_s"])) + 1,
    )
    analysis = analyze_results(trajectories, time_points)
    mask = np.asarray(analysis["eligible_masks"][:, -1], dtype=bool)
    usable_ever = np.any(analysis["eligible_masks"], axis=1)
    _atomic_npz(
        outcome, captured=mask, usable_ever=usable_ever, ensemble_ids=ensemble_ids
    )
    diagnostics = analysis["diagnostics"]
    save_file_json(json_path, {
        "kind": "mot_3d_timestep_validation_task",
        "design": design,
        "input_particle_count": len(mask),
        "captured_count": int(mask.sum()),
        "capture_fraction": float(mask.mean()),
        "runtime_s": time.monotonic() - start,
        "usable_ever_count": int(usable_ever.sum()),
        "peak_usable_count": int(analysis["peak_count"]),
        "entered_capture_region_count": int(diagnostics["entered_capture_region_count"]),
        "slow_inside_count": int(diagnostics["slow_inside_count"]),
        "outcomes": str(outcome),
        "outcomes_sha256": _sha256(outcome),
    })
    print(f"DT_RESULT task={task_index} captured={mask.sum()}/{len(mask)}")


def _crossed_interval(cell_values, alpha, rng):
    values = np.asarray(cell_values, dtype=float)
    if values.shape != (len(RECOIL_SEEDS), 20):
        raise ValueError("Crossed bootstrap requires recoil-by-ensemble cells.")
    recoil_draws = rng.integers(0, len(RECOIL_SEEDS), (BOOTSTRAP_REPLICATES, len(RECOIL_SEEDS)))
    ensemble_draws = rng.integers(0, 20, (BOOTSTRAP_REPLICATES, 20))
    means = np.empty(BOOTSTRAP_REPLICATES)
    for index in range(BOOTSTRAP_REPLICATES):
        means[index] = values[np.ix_(recoil_draws[index], ensemble_draws[index])].mean()
    return [float(np.quantile(means, alpha / 2)), float(np.quantile(means, 1 - alpha / 2))]


def merge(campaign, write=True):
    root = _root(campaign)
    manifest_path, manifest = _manifest(root)
    tasks = _tasks(manifest)
    result_dir = root / "dt_validation/results"
    expected_names = {
        f"task_{task['task_index']:03d}{suffix}"
        for task in tasks for suffix in (".json", ".npz")
    }
    observed_names = {path.name for path in result_dir.iterdir() if path.is_file()}
    if observed_names != expected_names:
        raise ValueError(
            f"Timestep artifact registry mismatch; missing={sorted(expected_names-observed_names)}, "
            f"unexpected={sorted(observed_names-expected_names)}"
        )
    _, _, provenance = _load_balanced_all_inputs(manifest_path)
    records = {}
    for task in tasks:
        path = result_dir / f"task_{task['task_index']:03d}.json"
        npz_path = result_dir / f"task_{task['task_index']:03d}.npz"
        parameters = dict(SENTINEL_PARAMETERS[task["family"]][task["anchor_index"]])
        profile, parameters, derived = build_profile_from_parameters(task["family"], parameters)
        design = _task_design(
            manifest_path, manifest, task, provenance, parameters, profile, derived
        )
        _validate_completed_task(path, npz_path, design)
        row = json.loads(path.read_text())
        with np.load(row["outcomes"]) as arrays:
            captured = np.asarray(arrays["captured"], bool).copy()
            ensemble_ids = np.asarray(arrays["ensemble_ids"], int).copy()
        records[(task["family"], task["anchor_index"], task["recoil_seed"], task["dt_s"])] = (
            row, captured, ensemble_ids
        )
    reference = manifest["design"]["dt_validation_reference_s"]
    candidates = manifest["design"]["dt_validation_candidates_s"]
    comparison_count = len(FAMILIES) * ANCHORS_PER_FAMILY * len(candidates)
    alpha = 0.05 / comparison_count
    rng = np.random.default_rng(67001)
    comparisons = []
    for family in FAMILIES:
        for anchor in range(ANCHORS_PER_FAMILY):
            for dt in candidates:
                cells = np.empty((len(RECOIL_SEEDS), 20))
                disagreement_cells = np.empty_like(cells)
                runtimes, reference_runtimes = [], []
                for recoil_index, recoil_seed in enumerate(RECOIL_SEEDS):
                    row, mask, ensemble_ids = records[(family, anchor, recoil_seed, dt)]
                    ref_row, ref_mask, ref_ids = records[(family, anchor, recoil_seed, reference)]
                    if not np.array_equal(ensemble_ids, ref_ids):
                        raise ValueError("Paired timestep tasks used different particles.")
                    for ensemble_id in range(20):
                        selected = ensemble_ids == ensemble_id
                        cells[recoil_index, ensemble_id] = np.mean(
                            mask[selected].astype(float) - ref_mask[selected].astype(float)
                        )
                        disagreement_cells[recoil_index, ensemble_id] = np.mean(
                            mask[selected] != ref_mask[selected]
                        )
                    runtimes.append(row["runtime_s"])
                    reference_runtimes.append(ref_row["runtime_s"])
                interval = _crossed_interval(cells, alpha, rng)
                disagreement_interval = _crossed_interval(disagreement_cells, alpha, rng)
                comparisons.append({
                    "family": family, "anchor_index": anchor, "dt_s": dt,
                    "paired_capture_difference": float(np.mean(cells)),
                    "bonferroni_familywise_95_interval": interval,
                    "absolute_bias_upper_bound": max(abs(interval[0]), abs(interval[1])),
                    "classification_disagreement_diagnostic": float(np.mean(disagreement_cells)),
                    "classification_disagreement_familywise_95_upper_diagnostic": disagreement_interval[1],
                    "mean_runtime_s": float(np.mean(runtimes)),
                    "runtime_relative_to_reference": float(np.mean(runtimes) / np.mean(reference_runtimes)),
                })
    def all_pass(dt, tolerance):
        selected = [row for row in comparisons if row["dt_s"] == dt]
        return bool(selected) and all(row["absolute_bias_upper_bound"] <= tolerance for row in selected)
    reference_capture = {}
    for family in FAMILIES:
        for anchor in range(ANCHORS_PER_FAMILY):
            fractions = [
                records[(family, anchor, seed, reference)][0]["capture_fraction"]
                for seed in RECOIL_SEEDS
            ]
            reference_capture[f"{family}:{anchor}"] = float(np.mean(fractions))
    informative = all(0.05 <= value <= 0.95 for value in reference_capture.values())
    screening = manifest["design"]["screening_dt_s"]
    production = manifest["design"]["production_dt_s"]
    screening_passed = informative and all_pass(screening, SCREENING_TOLERANCE)
    production_passed = informative and all_pass(production, PRODUCTION_TOLERANCE)
    passing_screening = [
        dt for dt in candidates if informative and all_pass(dt, SCREENING_TOLERANCE)
    ]
    passing_production = [
        dt for dt in candidates
        if informative and all_pass(dt, PRODUCTION_TOLERANCE)
        and (not passing_screening or dt <= max(passing_screening))
    ]
    evidence = {
        "kind": "mot_3d_timestep_validation",
        "format_version": EVIDENCE_FORMAT_VERSION,
        "status": "approved" if screening_passed and production_passed else (
            "inconclusive_degenerate_sentinel" if not informative else "not_approved"
        ),
        "screening_dt_s": screening,
        "production_dt_s": production,
        "reference_dt_s": reference,
        "tested_dt_s": candidates,
        "capture_bias_passed": screening_passed,
        "paired_decision_passed": production_passed,
        "screening_absolute_bias_tolerance": SCREENING_TOLERANCE,
        "production_absolute_bias_tolerance": PRODUCTION_TOLERANCE,
        "classification_disagreement_is_diagnostic_only": True,
        "reference_capture_fraction_by_sentinel": reference_capture,
        "sentinels_informative": informative,
        "largest_approved_screening_dt_s": max(passing_screening) if passing_screening else None,
        "largest_approved_production_dt_s": max(passing_production) if passing_production else None,
        "multiplicity": f"Bonferroni familywise paired crossed bootstrap ({comparison_count} comparisons)",
        "per_comparison_alpha": alpha,
        "bootstrap_replicates": BOOTSTRAP_REPLICATES,
        "campaign_manifest_sha256": _sha256(root / "campaign.json"),
        "tasks_sha256": _sha256(root / "dt_validation/tasks.json"),
        "raw_result_registry_sha256": _json_sha256([
            {
                "task_index": task["task_index"],
                "json_sha256": _sha256(result_dir / f"task_{task['task_index']:03d}.json"),
                "npz_sha256": _sha256(result_dir / f"task_{task['task_index']:03d}.npz"),
            }
            for task in tasks
        ]),
        "campaign_commit": manifest["provenance"]["git_commit"],
        "physical_model_sha256": manifest["provenance"]["physical_model_sha256"],
        "particles_per_ensemble": PARTICLES_PER_ENSEMBLE,
        "ensemble_count": 20,
        "recoil_seeds": list(RECOIL_SEEDS),
        "t_max_s": T_MAX_S,
        "comparisons": comparisons,
        "new_campaign_required_if_selected_dt_changes": True,
    }
    if write:
        output = root / "dt_validation/evidence.json"
        save_file_json(output, evidence)
        print(json.dumps(evidence, indent=2))
        print(f"Timestep evidence saved to: {output}")
    return evidence


def submit(campaign):
    root = _root(campaign)
    _, manifest = _manifest(root)
    submission = root / "dt_validation/submission.json"
    if not (root / "dt_validation/tasks.json").is_file():
        prepare(root)
    record = json.loads(submission.read_text()) if submission.exists() else {
        "status": "submitting", "array_job_id": None, "merge_job_id": None
    }
    if record.get("merge_job_id"):
        raise RuntimeError("Timestep validation was already fully submitted.")
    if not record.get("array_job_id"):
        array_id = subprocess.check_output(
            ["qsub", str(root / "dt_validation/run.pbs")], text=True
        ).strip()
        if not array_id:
            raise RuntimeError("qsub returned an empty timestep-array job ID.")
        record["array_job_id"] = array_id
        save_file_json(submission, record)
    else:
        array_id = record["array_job_id"]
    try:
        merge_id = subprocess.check_output([
            "qsub", "-W", f"depend=afterok:{array_id}", str(root / "dt_validation/merge.pbs")
        ], text=True).strip()
        if not merge_id:
            raise RuntimeError("qsub returned an empty timestep-merge job ID.")
    except Exception:
        record["status"] = "partial_failure_merge_not_submitted"
        save_file_json(submission, record)
        raise
    record.update(status="submitted", merge_job_id=merge_id)
    save_file_json(submission, record)
    print(f"Submitted timestep array: {array_id}")
    print(f"Submitted timestep merge: {merge_id}")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, function in (("prepare", prepare), ("merge", merge), ("submit", submit)):
        command = commands.add_parser(name)
        command.add_argument("--campaign", required=True)
        command.set_defaults(function=function)
    command = commands.add_parser("run-task")
    command.add_argument("--campaign", required=True)
    command.add_argument("--task-index", required=True, type=int)
    command.set_defaults(function=lambda args: run_task(args.campaign, args.task_index))
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    if args.command == "run-task":
        args.function(args)
    else:
        args.function(args.campaign)
