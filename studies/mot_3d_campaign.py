"""Create and inspect the canonical corrected-input 3D-MOT campaign.

Creation is plan-only: it validates and freezes the 20 final 2D-MOT survivor
ensembles and writes guarded PBS files, but never calls ``qsub``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
from pathlib import Path

import numpy as np

from config import (
    DEFAULT_RANDOM_SEED,
    MOT_2D_SIM_CONFIG,
    MOT_3D_OPTIMIZATION_CONFIG,
    MOT_3D_SIM_CONFIG,
)
from utils.file_helpers import save_file_json
from utils.data_paths import load_particle_states


FAMILIES = ("angled_donut", "single_pass")
CAMPAIGN_FILES = (
    "config.py",
    "lab_setup/laser_setup_3d.py",
    "simulations/mot_3d.py",
    "studies/mot_3d_campaign.py",
    "studies/optimize_3d_mot_full.py",
    "studies/compare_3d_mot_retention.py",
    "studies/merge_3d_mot_full_optimization.py",
    "studies/select_3d_mot_discovery_candidates.py",
    "studies/run_3d_mot_early_independent_check.py",
    "studies/merge_3d_mot_early_independent_check.py",
    "studies/select_3d_mot_refinement_candidates.py",
    "studies/run_3d_mot_focused_refinement.py",
    "studies/merge_3d_mot_focused_refinement.py",
    "studies/select_3d_mot_closure_candidates.py",
    "studies/select_3d_mot_finalists.py",
    "studies/run_3d_mot_finalist_selection.py",
    "studies/merge_3d_mot_finalist_selection.py",
    "studies/mot_3d_stage_integrity.py",
    "studies/mot_3d_final_validation.py",
    "studies/generate_corrected_zeeman_ensembles.py",
    "studies/run_2d_mot_final_production.py",
)


def relevant_files():
    """Return the conservative closure of code that can affect 3D dynamics."""
    paths = {Path(name) for name in CAMPAIGN_FILES}
    for directory in ("lab_setup", "simulations", "utils", "atomsmltr/src/atomsmltr"):
        paths.update(Path(directory).rglob("*.py"))
    return tuple(path.as_posix() for path in sorted(paths))
EXPECTED_SEEDS = tuple(range(3015, 3035))
ROLE_SEEDS = {
    "discovery": EXPECTED_SEEDS[:12],
    "refinement": EXPECTED_SEEDS[12:16],
    "preliminary_check": EXPECTED_SEEDS[16:20],
}
SAMPLER_SEEDS = (271_001, 271_002, 271_003)
DISCOVERY_ROUNDS = {"angled_donut": 2, "single_pass": 3}
FINAL_VALIDATION_ZEEMAN_SEEDS = tuple(range(3035, 3055))
FINAL_VALIDATION_MOT_SEEDS = tuple(range(43035, 43055))


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _revision():
    return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()


def _relevant_hash():
    digest = hashlib.sha256()
    for name in relevant_files():
        path = Path(name)
        digest.update(name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _dirty_relevant_files():
    result = subprocess.run(
        ["git", "status", "--porcelain", "--", *relevant_files()],
        check=True,
        capture_output=True,
        text=True,
    )
    return tuple(line[3:] for line in result.stdout.splitlines() if line.strip())


def validate_upstream_2d_campaign(campaign_directory, survivor_directory):
    root = Path(campaign_directory).resolve()
    manifest_path = root / "campaign.json"
    report_path = root / "final_report.json"
    if not manifest_path.is_file() or not report_path.is_file():
        raise FileNotFoundError("Completed 2D campaign manifest/final report is missing.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if manifest.get("kind") != "mot_2d_s0_campaign" or manifest.get("stage") != "complete":
        raise ValueError("Upstream 2D campaign is not complete and canonical.")
    if report.get("kind") != "mot_2d_s0_campaign_final_report":
        raise ValueError("Unexpected upstream 2D final-report kind.")
    registered_report = manifest.get("stages", {}).get("final_report")
    if not registered_report or Path(registered_report).resolve() != report_path:
        raise ValueError("Upstream manifest does not register this final report.")
    seeds = tuple(manifest.get("seed_roles", {}).get("sealed_validation", ()))
    mot_seeds = tuple(manifest.get("mot_seeds", {}).get("sealed_validation", ()))
    if seeds != EXPECTED_SEEDS or len(mot_seeds) != len(EXPECTED_SEEDS):
        raise ValueError("Upstream sealed seed registry does not match the 3D handoff.")
    results = report.get("results", [])
    matching = [
        row for row in results
        if Path(row.get("survivor_states_directory", "")).resolve()
        == Path(survivor_directory).resolve()
    ]
    if len(matching) != 1:
        raise ValueError("Survivor directory is not the unique selected 2D production output.")
    if matching[0].get("s0") not in manifest.get("s0_values", []):
        raise ValueError("Selected 2D result has an unregistered s0 value.")
    fixed = manifest.get("fixed_design", {})
    source = manifest.get("ensemble_source", {})
    expected_design = {
        "git_commit": manifest.get("provenance", {}).get("git_commit"),
        "dt_s": fixed.get("final_dt_s"),
        "stochastic_solver": fixed.get("solver"),
        "ensemble_dir": source.get("directory"),
        "zeeman_profile": source.get("zeeman_profile"),
    }
    if any(value is None for value in expected_design.values()):
        raise ValueError("Upstream 2D manifest has incomplete production design.")
    return {
        "campaign_path": str(manifest_path),
        "campaign_sha256": _sha256(manifest_path),
        "final_report_path": str(report_path),
        "final_report_sha256": _sha256(report_path),
        "git_commit": manifest.get("provenance", {}).get("git_commit"),
        "physical_model_sha256": manifest.get("provenance", {}).get(
            "physical_model_sha256"
        ),
        "sealed_seed_pairs": [
            {"zeeman_seed": int(seed), "mot_seed": int(mot_seed)}
            for seed, mot_seed in zip(seeds, mot_seeds)
        ],
        "selected_result": matching[0],
        "expected_survivor_design": expected_design,
        "expected_survivor_parameters": matching[0].get("recommended_parameters"),
    }


def freeze_inputs(
    directory,
    expected_seed_pairs=None,
    expected_design=None,
    expected_parameters=None,
):
    directory = Path(directory).resolve()
    records = {}
    for seed in EXPECTED_SEEDS:
        matches = sorted(
            directory.glob(
                f"mot_2d_survivors_zeeman_seed{seed}_mot_seed*.npy"
            )
        )
        if len(matches) != 1:
            raise ValueError(
                f"Expected exactly one final 2D-MOT ensemble for seed {seed}; "
                f"found {len(matches)} in {directory}."
            )
        path = matches[0]
        metadata_path = path.with_suffix(".json")
        if not metadata_path.exists():
            raise FileNotFoundError(f"Missing survivor metadata: {metadata_path}")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        states = np.load(path, mmap_mode="r")
        if metadata.get("kind") != "mot_2d_final_survivor_ensemble":
            raise ValueError(f"Unexpected metadata kind in {metadata_path}.")
        if int(metadata.get("zeeman_seed", -1)) != seed:
            raise ValueError(f"Zeeman seed mismatch in {metadata_path}.")
        if states.ndim != 2 or states.shape[1] != 6 or not np.all(np.isfinite(states)):
            raise ValueError(f"Invalid particle-state array: {path}")
        digest = _sha256(path)
        if digest != metadata.get("output_sha256"):
            raise ValueError(f"SHA-256 mismatch for {path}.")
        if list(states.shape) != metadata.get("shape"):
            raise ValueError(f"Shape mismatch for {path}.")
        if str(states.dtype) != metadata.get("dtype"):
            raise ValueError(f"Dtype mismatch for {path}.")
        if len(states) != int(metadata.get("n_survivors", -1)):
            raise ValueError(f"Survivor-count mismatch for {path}.")
        records[seed] = {
            "path": str(path),
            "metadata_path": str(metadata_path),
            "metadata_sha256": _sha256(metadata_path),
            "sha256": digest,
            "shape": list(states.shape),
            "dtype": str(states.dtype),
            "zeeman_seed": seed,
            "mot_seed": int(metadata["mot_seed"]),
            "n_survivors": len(states),
            "source_git_commit": metadata.get("design", {}).get("git_commit"),
            "source_design": metadata.get("design"),
            "source_parameters": metadata.get("parameters"),
        }
        if expected_seed_pairs is not None:
            expected_mot_seed = expected_seed_pairs.get(seed)
            if expected_mot_seed is None or int(metadata["mot_seed"]) != int(expected_mot_seed):
                raise ValueError(f"Unexpected Zeeman/MOT seed pair in {metadata_path}.")
    designs = [records[seed]["source_design"] for seed in EXPECTED_SEEDS]
    if not designs[0] or any(design != designs[0] for design in designs[1:]):
        raise ValueError("2D survivor ensembles have missing or mixed source designs.")
    if expected_design is not None and designs[0] != expected_design:
        raise ValueError("2D survivor design does not match the completed campaign.")
    parameters = [records[seed]["source_parameters"] for seed in EXPECTED_SEEDS]
    if not parameters[0] or any(value != parameters[0] for value in parameters[1:]):
        raise ValueError("2D survivor ensembles have missing or mixed parameters.")
    if expected_parameters is not None and parameters[0] != expected_parameters:
        raise ValueError("2D survivor parameters do not match the selected result.")
    return {
        role: [records[seed] for seed in seeds]
        for role, seeds in ROLE_SEEDS.items()
    }


def validate_frozen_inputs(manifest_path, role, *, verify_design=True):
    """Revalidate frozen campaign inputs immediately before simulation."""
    manifest_path = Path(manifest_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = payload.get("input_roles", {}).get(role)
    if not isinstance(records, list) or not records:
        raise ValueError(f"Campaign has no non-empty input role {role!r}.")
    if role not in ROLE_SEEDS:
        raise ValueError(f"Unknown input role {role!r}.")
    observed_seeds = tuple(int(record.get("zeeman_seed", -1)) for record in records)
    if observed_seeds != ROLE_SEEDS[role]:
        raise ValueError(
            f"Frozen role {role!r} must contain exact ordered seeds "
            f"{ROLE_SEEDS[role]}; found {observed_seeds}."
        )
    if verify_design:
        expected_revision = payload.get("provenance", {}).get("git_commit")
        if expected_revision != _revision():
            raise ValueError(
                f"Campaign commit mismatch: expected {expected_revision}, found {_revision()}."
            )
        expected_hash = payload.get("provenance", {}).get("physical_model_sha256")
        observed_hash = _relevant_hash()
        if expected_hash != observed_hash:
            raise ValueError("Campaign physical-model hash mismatch.")
    validated = []
    seen_pairs = set()
    seen_mot_seeds = set()
    upstream_pairs = {
        int(row["zeeman_seed"]): int(row["mot_seed"])
        for row in payload.get("upstream_2d_campaign", {}).get(
            "sealed_seed_pairs", []
        )
    }
    for record in records:
        path = Path(record["path"])
        metadata_path = Path(record["metadata_path"])
        if not path.is_file() or not metadata_path.is_file():
            raise FileNotFoundError(f"Frozen input is missing: {path}")
        if _sha256(path) != record["sha256"]:
            raise ValueError(f"Frozen array SHA-256 mismatch: {path}")
        if _sha256(metadata_path) != record["metadata_sha256"]:
            raise ValueError(f"Frozen metadata SHA-256 mismatch: {metadata_path}")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        states = np.load(path, mmap_mode="r")
        pair = (int(record["zeeman_seed"]), int(record["mot_seed"]))
        if upstream_pairs.get(pair[0]) != pair[1]:
            raise ValueError(f"Frozen pair {pair} differs from upstream 2D registry.")
        if pair in seen_pairs:
            raise ValueError(f"Duplicate frozen seed pair: {pair}")
        seen_pairs.add(pair)
        if pair[1] in seen_mot_seeds:
            raise ValueError(f"Duplicate frozen MOT seed: {pair[1]}")
        seen_mot_seeds.add(pair[1])
        if metadata.get("kind") != "mot_2d_final_survivor_ensemble":
            raise ValueError(f"Unexpected metadata kind in {metadata_path}.")
        if (int(metadata.get("zeeman_seed", -1)), int(metadata.get("mot_seed", -1))) != pair:
            raise ValueError(f"Frozen seed-pair mismatch in {metadata_path}.")
        if list(states.shape) != record["shape"] or str(states.dtype) != record["dtype"]:
            raise ValueError(f"Frozen shape/dtype mismatch: {path}")
        if len(states) != int(record["n_survivors"]) or not np.all(np.isfinite(states)):
            raise ValueError(f"Frozen survivor data are invalid: {path}")
        validated.append(record)
    return validated


def load_role_particles(manifest_path, role, per_ensemble, selection_seed):
    """Load a deterministic balanced subset from one frozen campaign role."""
    records = validate_frozen_inputs(manifest_path, role)
    states, ensemble_ids, provenance = [], [], []
    for ensemble_id, record in enumerate(records):
        available = np.asarray(load_particle_states(record["path"]), dtype=float)
        if len(available) < per_ensemble:
            raise ValueError(
                f"{record['path']} has {len(available)} particles; need {per_ensemble}."
            )
        rng = np.random.default_rng(
            np.random.SeedSequence([selection_seed, record["zeeman_seed"]])
        )
        indices = np.sort(
            rng.choice(len(available), size=per_ensemble, replace=False)
        )
        states.append(available[indices])
        ensemble_ids.extend([ensemble_id] * per_ensemble)
        provenance.append({
            "ensemble_id": ensemble_id,
            "file": record["path"],
            "array_sha256": record["sha256"],
            "zeeman_seed": record["zeeman_seed"],
            "mot_seed": record["mot_seed"],
            "available_count": len(available),
            "selected_indices": indices.tolist(),
        })
    return np.concatenate(states), np.asarray(ensemble_ids), provenance


def load_all_frozen_particles(manifest_path):
    """Load every one of the 20 existing selection ensembles exactly once."""
    records = []
    for role in ("discovery", "refinement", "preliminary_check"):
        records.extend(validate_frozen_inputs(manifest_path, role))
    if tuple(row["zeeman_seed"] for row in records) != EXPECTED_SEEDS:
        raise ValueError("Combined selection roles do not form the exact 20-seed registry.")
    states, ensemble_ids, provenance = [], [], []
    for ensemble_id, record in enumerate(records):
        available = np.asarray(load_particle_states(record["path"]), dtype=float)
        states.append(available)
        ensemble_ids.extend([ensemble_id] * len(available))
        provenance.append({
            "ensemble_id": ensemble_id,
            "file": record["path"],
            "array_sha256": record["sha256"],
            "zeeman_seed": record["zeeman_seed"],
            "mot_seed": record["mot_seed"],
            "particle_count": len(available),
        })
    return np.concatenate(states), np.asarray(ensemble_ids), provenance


def _header(name, revision, walltime="24:00:00", ncpus=200, memory="64gb"):
    return f"""#!/bin/bash
#PBS -N {name}
#PBS -q zeus_combined_q
#PBS -l select=1:ncpus={ncpus}:mem={memory}
#PBS -l walltime={walltime}

set -euo pipefail
cd ~/ytterbium_lab_simulation_new
EXPECTED_COMMIT={revision}
ACTUAL_COMMIT=$(git rev-parse HEAD)
if [ "${{ACTUAL_COMMIT}}" != "${{EXPECTED_COMMIT}}" ]; then
  echo "Commit mismatch: expected ${{EXPECTED_COMMIT}}, found ${{ACTUAL_COMMIT}}" >&2
  exit 42
fi
source ~/venvs/atomsmltr/bin/activate
RUN_TMP="/tmp/${{USER}}_{name}_${{PBS_JOBID}}_${{PBS_ARRAY_INDEX:-0}}"
mkdir -p "${{RUN_TMP}}"
export TMPDIR="${{RUN_TMP}}" TMP="${{RUN_TMP}}" TEMP="${{RUN_TMP}}"
trap 'rm -rf -- "${{RUN_TMP}}"' EXIT

"""


def _write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _targets(total):
    base, remainder = divmod(total, 3)
    return tuple(base + (index < remainder) for index in range(3))


def _cumulative_targets(final_targets, round_index, round_count):
    return tuple(
        min(target, math.ceil(target * round_index / round_count))
        for target in final_targets
    )


def write_discovery_jobs(root, revision):
    jobs = root / "jobs"
    manifest_path = root / "campaign.json"
    dt = MOT_3D_SIM_CONFIG["screening_dt_s"]
    smoke_paths = {}
    for index, family in enumerate(FAMILIES):
        short = "don" if family == "angled_donut" else "sp"
        smoke_paths[family] = _write(
            jobs / f"01_smoke_{family}.pbs",
            _header(f"m3d2_{short}_smoke", revision, "01:00:00", 12, "8gb")
            + f"python -u -m studies.optimize_3d_mot_full --family {family} "
            f"--worker-index 0 --target-completed-trials 1 "
            f"--sampler-seed {281001 + index} --output-dir {root/'smoke'/family} "
            f"--input-manifest {manifest_path} --input-role discovery "
            f"--particles-per-ensemble 1 --npools 12 --dt {dt} --timeout-s 3000\n",
        )

    round_paths = {}
    for family in FAMILIES:
        total = MOT_3D_OPTIMIZATION_CONFIG[family]["total_discovery_trials"]
        targets = _targets(total)
        family_paths = []
        round_count = DISCOVERY_ROUNDS[family]
        short = "don" if family == "angled_donut" else "sp"
        for round_index in range(1, round_count + 1):
            cumulative = _cumulative_targets(targets, round_index, round_count)
            target_values = " ".join(str(value) for value in cumulative)
            sampler_values = " ".join(str(value) for value in SAMPLER_SEEDS)
            family_paths.append(
                _write(
                    jobs / family / f"round_{round_index:02d}.pbs",
                    _header(f"m3d2_{short}_r{round_index}", revision)
                    + "# Array directive is supplied by the submission chain.\n"
                    + f"targets=({target_values})\n"
                    + f"samplers=({sampler_values})\n"
                    + 'worker="${PBS_ARRAY_INDEX}"\n'
                    + 'target="${targets[$worker]}"\n'
                    + 'sampler="${samplers[$worker]}"\n'
                    + f"python -u -m studies.optimize_3d_mot_full "
                    f"--family {family} --worker-index \"$worker\" "
                    f"--target-completed-trials \"$target\" "
                    f"--sampler-seed \"$sampler\" "
                    f"--output-dir {root/'discovery'/family} "
                    f"--input-manifest {manifest_path} --input-role discovery "
                    f"--particles-per-ensemble 50 --npools 200 --dt {dt} "
                    f"--timeout-s 68400\n",
                )
            )
        round_paths[family] = family_paths
    submitter = jobs / "02_submit_discovery_chain.sh"
    # Convenience wrapper only; the Python command is the single submission
    # authority and owns duplicate prevention plus durable job-ID recording.
    lines = [
        "#!/bin/bash",
        "set -euo pipefail",
        "python -u -m studies.mot_3d_campaign submit-discovery "
        f'--campaign "{root}"',
    ]
    _write(submitter, "\n".join(lines) + "\n")
    return smoke_paths, round_paths, submitter


def submit_discovery(campaign, qsub=None):
    """Submit once, atomically recording every raw Zeus job identifier."""
    root = Path(campaign)
    manifest = json.loads((root / "campaign.json").read_text(encoding="utf-8"))
    destination = root / "discovery_submission.json"
    if manifest.get("stage") != "discovery":
        raise RuntimeError(
            f"Discovery submission is blocked at stage {manifest.get('stage')!r}."
        )
    try:
        descriptor = os.open(
            destination,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o644,
        )
    except FileExistsError:
        raise FileExistsError(f"Discovery was already submitted: {destination}")
    else:
        os.close(descriptor)
    runner = qsub or (
        lambda command: subprocess.check_output(command, text=True).strip()
    )
    record = {
        "kind": "mot_3d_discovery_submission",
        "status": "submitting",
        "dependency": "afterok",
        "families": {},
    }
    save_file_json(destination, record)
    try:
        for family in FAMILIES:
            previous = None
            rounds = []
            for path in manifest["jobs"]["discovery_rounds"][family]:
                command = ["qsub", "-J", "0-2:1"]
                if previous is not None:
                    command += ["-W", f"depend=afterok:{previous}"]
                command.append(path)
                job_id = runner(command)
                if not job_id:
                    raise RuntimeError("qsub returned an empty job identifier.")
                rounds.append({"job_file": path, "job_id": job_id})
                previous = job_id
                record["families"][family] = {
                    "rounds": rounds,
                    "final_job_id": previous,
                }
                save_file_json(destination, record)
        record["status"] = "submitted"
        save_file_json(destination, record)
    except BaseException as error:
        record["status"] = "partial_failure"
        record["error"] = f"{type(error).__name__}: {error}"
        save_file_json(destination, record)
        raise
    print(f"Discovery submission recorded: {destination}")
    return record


def _selection_stage_jobs(
    root,
    manifest,
    stage,
    selection_paths,
    role,
    particles_per_ensemble,
    selection_seed,
    recoil_seed,
):
    jobs = root / "jobs" / stage
    manifest_path = root / "campaign.json"
    dt = manifest["design"]["screening_dt_s"]
    runner_module = (
        "studies.run_3d_mot_early_independent_check"
        if stage == "preliminary_check"
        else "studies.run_3d_mot_focused_refinement"
    )
    merger_module = (
        "studies.merge_3d_mot_early_independent_check"
        if stage == "preliminary_check"
        else "studies.merge_3d_mot_focused_refinement"
    )
    worker_jobs, merge_jobs = {}, {}
    for family in FAMILIES:
        short = "don" if family == "angled_donut" else "sp"
        stage_root = root / stage / family
        selection = selection_paths[family]
        worker_jobs[family] = _write(
            jobs / f"{family}_array.pbs",
            _header(f"m3d2_{short}_{stage[:3]}", manifest["provenance"]["git_commit"])
            + f"python -u -m {runner_module} --family {family} "
            '--worker-index "$PBS_ARRAY_INDEX" --num-workers 3 '
            f"--selection {selection} --input-manifest {manifest_path} "
            f"--particles-per-ensemble {particles_per_ensemble} "
            f"--selection-seed {selection_seed} --npools 200 --dt {dt} "
            f"--output-dir {stage_root}/worker_${{PBS_ARRAY_INDEX}}\n",
        )
        summary_name = (
            "early_check_summary.json"
            if stage == "preliminary_check"
            else "refinement_summary.json"
        )
        merge_jobs[family] = _write(
            jobs / f"{family}_merge.pbs",
            _header(
                f"m3d2_{short}_{stage[:3]}m",
                manifest["provenance"]["git_commit"],
                "01:00:00",
                1,
                "4gb",
            )
            + f"python -u -m {merger_module} --selection {selection} "
            f"--input-root {stage_root} --output-dir {stage_root}/merged "
            f"--bootstrap-seed {recoil_seed}\n"
            + f'test -s "{stage_root}/merged/{summary_name}"\n',
        )
    return worker_jobs, merge_jobs


def validate_discovery_complete(root, manifest, family):
    """Reject incomplete, foreign, or stale discovery trial registries."""
    from studies.optimize_3d_mot_full import load_balanced_discovery_particles

    root = Path(root)
    family_root = root / "discovery" / family
    all_paths = sorted(family_root.glob("worker_*/trials/trial_*.json"))
    total = MOT_3D_OPTIMIZATION_CONFIG[family]["total_discovery_trials"]
    targets = _targets(total)
    if len(all_paths) != total:
        raise RuntimeError(
            f"Discovery {family} has {len(all_paths)}/{total} registered trials."
        )
    input_files = [row["path"] for row in validate_frozen_inputs(root / "campaign.json", "discovery")]
    _, expected_selection = load_balanced_discovery_particles(
        input_files[0],
        ensemble_count=len(input_files),
        per_ensemble=50,
        seed=DEFAULT_RANDOM_SEED,
        input_files=input_files,
    )
    upstream = manifest["upstream_2d_campaign"]
    expected_common = {
        "family": family,
        "startup_trials": 24,
        "selection_seed": DEFAULT_RANDOM_SEED,
        "simulation_seed": DEFAULT_RANDOM_SEED,
        "particles_per_ensemble": 50,
        "dt_s": manifest["design"]["screening_dt_s"],
        "t_max_s": 0.1,
        "solver": manifest["design"]["solver"],
        "bounds": MOT_3D_OPTIMIZATION_CONFIG,
        "particle_selection": expected_selection,
        "campaign_commit": manifest["provenance"]["git_commit"],
        "physical_model_sha256": manifest["provenance"]["physical_model_sha256"],
        "input_role": "discovery",
        "frozen_inputs": manifest["input_roles"]["discovery"],
        "upstream_campaign_sha256": upstream["campaign_sha256"],
        "upstream_final_report_sha256": upstream["final_report_sha256"],
    }
    for worker, target in enumerate(targets):
        trials_dir = family_root / f"worker_{worker}" / "trials"
        paths = sorted(trials_dir.glob("trial_*.json"))
        unexpected = [path for path in trials_dir.iterdir() if path not in paths]
        if unexpected:
            raise RuntimeError(
                f"Unexpected discovery artifacts for {family} worker {worker}: "
                + ", ".join(path.name for path in unexpected)
            )
        if len(paths) != target:
            raise RuntimeError(
                f"Discovery {family} worker {worker} has {len(paths)}/{target} trials."
            )
        seen_trials = set()
        expected_design = dict(expected_common, worker_index=worker, sampler_seed=SAMPLER_SEEDS[worker])
        encoded = json.dumps(expected_design, sort_keys=True, separators=(",", ":"))
        expected_id = hashlib.sha256(encoded.encode()).hexdigest()
        for path in paths:
            row = json.loads(path.read_text(encoding="utf-8"))
            if row.get("family") != family or row.get("worker_index") != worker:
                raise ValueError(f"Discovery registry metadata mismatch: {path}")
            trial_number = row.get("trial_number")
            if path.name != f"trial_{int(trial_number):04d}.json":
                raise ValueError(f"Discovery filename/metadata mismatch: {path}")
            if trial_number in seen_trials:
                raise ValueError(f"Duplicate discovery trial number in worker {worker}.")
            seen_trials.add(trial_number)
            if row.get("scientific_design") != expected_design or row.get("design_id") != expected_id:
                raise ValueError(f"Foreign or stale discovery design: {path}")
    return True


def prepare_preliminary_check(root, manifest):
    from studies.merge_3d_mot_full_optimization import merge
    from studies.select_3d_mot_discovery_candidates import select_candidates

    selections = {}
    for family in FAMILIES:
        discovery_root = root / "discovery" / family
        validate_discovery_complete(root, manifest, family)
        merged = discovery_root / "merged"
        total = MOT_3D_OPTIMIZATION_CONFIG[family]["total_discovery_trials"]
        summary_path, _ = merge(
            discovery_root,
            merged,
            total,
            expected_worker_count=3,
            campaign_manifest_sha256=_sha256(root / "campaign.json"),
        )
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        selection = select_candidates(summary, family, count=12)
        destination = root / "selection" / "discovery" / f"{family}.json"
        save_file_json(destination, selection)
        selections[family] = destination
    workers, merges = _selection_stage_jobs(
        root, manifest, "preliminary_check", selections,
        "preliminary_check", 150, 51_001, 52_001,
    )
    manifest["stage"] = "preliminary_check"
    manifest.setdefault("stages", {})["preliminary_check"] = {
        "classification": "candidate_selection_not_final_validation",
        "selection_files": {key: str(value) for key, value in selections.items()},
        "worker_jobs": {key: str(value) for key, value in workers.items()},
        "merge_jobs": {key: str(value) for key, value in merges.items()},
        "input_role": "preliminary_check",
    }
    save_file_json(root / "campaign.json", manifest)


def prepare_refinement(root, manifest):
    from studies.select_3d_mot_refinement_candidates import select

    selections = {}
    for family in FAMILIES:
        summary = root / "preliminary_check" / family / "merged" / "early_check_summary.json"
        if not summary.is_file():
            raise RuntimeError(f"Preliminary check incomplete: {summary}")
        payload = select(family, summary)
        destination = root / "selection" / "refinement" / f"{family}.json"
        save_file_json(destination, payload)
        selections[family] = destination
    workers, merges = _selection_stage_jobs(
        root, manifest, "refinement", selections,
        "refinement", 750, 61_001, 62_001,
    )
    manifest["stage"] = "refinement"
    manifest.setdefault("stages", {})["refinement"] = {
        "classification": "candidate_selection_not_final_validation",
        "selection_files": {key: str(value) for key, value in selections.items()},
        "worker_jobs": {key: str(value) for key, value in workers.items()},
        "merge_jobs": {key: str(value) for key, value in merges.items()},
        "input_role": "refinement",
    }
    save_file_json(root / "campaign.json", manifest)


def prepare_closure(root, manifest):
    from studies.select_3d_mot_closure_candidates import select

    selections = {}
    for family in FAMILIES:
        summary = root / "refinement" / family / "merged" / "refinement_summary.json"
        if not summary.is_file():
            raise RuntimeError(f"Refinement incomplete: {summary}")
        payload = select(family, summary)
        destination = root / "selection" / "closure" / f"{family}.json"
        save_file_json(destination, payload)
        selections[family] = destination
    workers, merges = _selection_stage_jobs(
        root, manifest, "closure", selections,
        "refinement", 750, 71_001, 72_001,
    )
    manifest["stage"] = "closure"
    manifest.setdefault("stages", {})["closure"] = {
        "classification": "candidate_selection_not_final_validation",
        "selection_files": {key: str(value) for key, value in selections.items()},
        "worker_jobs": {key: str(value) for key, value in workers.items()},
        "merge_jobs": {key: str(value) for key, value in merges.items()},
        "input_role": "refinement",
    }
    save_file_json(root / "campaign.json", manifest)


def prepare_finalist_selection(root, manifest):
    from studies.select_3d_mot_finalists import select

    selections, worker_jobs, merge_jobs = {}, {}, {}
    jobs = root / "jobs" / "finalist_selection"
    manifest_path = root / "campaign.json"
    dt = manifest["design"]["production_dt_s"]
    for family in FAMILIES:
        summary = root / "closure" / family / "merged" / "refinement_summary.json"
        if not summary.is_file():
            raise RuntimeError(f"Closure incomplete: {summary}")
        payload = select(family, summary, count=3)
        selection = root / "selection" / "finalists" / f"{family}.json"
        save_file_json(selection, payload)
        selections[family] = selection
        short = "don" if family == "angled_donut" else "sp"
        family_root = root / "finalist_selection" / family
        worker_jobs[family] = _write(
            jobs / f"{family}_array.pbs",
            _header(f"m3d2_{short}_fin", manifest["provenance"]["git_commit"])
            + f"python -u -m studies.run_3d_mot_finalist_selection "
            f"--family {family} --selection {selection} "
            '--finalist-index "$PBS_ARRAY_INDEX" '
            f"--input-manifest {manifest_path} --npools 200 --dt {dt} "
            f"--output-dir {family_root}/finalist_${{PBS_ARRAY_INDEX}}\n",
        )
        merge_jobs[family] = _write(
            jobs / f"{family}_merge.pbs",
            _header(f"m3d2_{short}_finm", manifest["provenance"]["git_commit"], "01:00:00", 1, "4gb")
            + f"python -u -m studies.merge_3d_mot_finalist_selection "
            f"--selection {selection} --input-root {family_root} "
            f"--output-dir {family_root}/merged --bootstrap-seed 82001\n",
        )
    manifest["stage"] = "finalist_selection"
    manifest.setdefault("stages", {})["finalist_selection"] = {
        "classification": "final_candidate_selection_not_unbiased_validation",
        "selection_files": {key: str(value) for key, value in selections.items()},
        "worker_jobs": {key: str(value) for key, value in worker_jobs.items()},
        "merge_jobs": {key: str(value) for key, value in merge_jobs.items()},
        "input_roles": ["discovery", "refinement", "preliminary_check"],
    }
    save_file_json(root / "campaign.json", manifest)


def prepare_final_validation_inputs(root, manifest):
    """Lock nominal winners before creating any new validation ensemble."""
    from studies.optimize_3d_mot_full import build_profile_from_parameters

    locked = {
        "kind": "mot_3d_locked_nominals",
        "classification": "locked_before_new_validation_inputs",
        "campaign_manifest_sha256_before_stage": _sha256(root / "campaign.json"),
        "families": {},
    }
    for family in FAMILIES:
        summary_path = root / "finalist_selection" / family / "merged" / "finalist_summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        winner = summary["ranked_candidates"][0]
        profile, parameters, derived = build_profile_from_parameters(
            family, winner["parameters"]
        )
        locked["families"][family] = {
            "candidate_id": winner["candidate_id"],
            "parameters": parameters,
            "derived_parameters": derived,
            "resolved_profile": profile,
            "selection_summary_sha256": _sha256(summary_path),
        }
    locked_path = root / "selection" / "locked_nominals.json"
    save_file_json(locked_path, locked)
    base = root / "final_validation_inputs"
    zeeman_dir = base / "after_zeeman"
    states_dir = base / "after_2d_mot"
    output_2d = base / "mot_2d_records"
    jobs = root / "jobs" / "final_validation_inputs"
    revision = manifest["provenance"]["git_commit"]
    params = manifest["upstream_2d_campaign"]["expected_survivor_parameters"]
    profile = manifest["upstream_2d_campaign"]["expected_survivor_design"]["zeeman_profile"]
    zeeman_job = _write(
        jobs / "01_generate_zeeman.pbs",
        _header("m3d2_val_z", revision, "08:00:00")
        + 'seed=$((3035 + PBS_ARRAY_INDEX))\n'
        + f"python -u -m studies.generate_corrected_zeeman_ensembles --seed \"$seed\" "
        f"--npools 200 --output-dir {zeeman_dir}\n",
    )
    mot_job = _write(
        jobs / "02_generate_2d_survivors.pbs",
        _header("m3d2_val_2d", revision, "12:00:00")
        + 'zseed=$((3035 + PBS_ARRAY_INDEX))\n'
        + 'mseed=$((43035 + PBS_ARRAY_INDEX))\n'
        + f"python -u -m studies.run_2d_mot_final_production --zeeman-seeds \"$zseed\" "
        f"--mot-seeds \"$mseed\" --ensemble-dir {zeeman_dir} "
        f"--expected-zeeman-profile {profile} --expected-git-commit {revision} "
        f"--s0 {params['s0']} --detuning-gamma {params['detuning_gamma']} "
        f"--magnet-radius-mm {1000 * params['magnet_radius']} --npools 200 "
        f"--output-dir {output_2d} --save-survivor-states --states-dir {states_dir}\n",
    )
    freeze_job = _write(
        jobs / "03_freeze_inputs.pbs",
        _header("m3d2_val_frz", revision, "00:30:00", 1, "8gb")
        + f"python -u -m studies.mot_3d_campaign freeze-final-inputs --campaign {root}\n",
    )
    manifest["stage"] = "final_validation_input_generation"
    manifest.setdefault("stages", {})["final_validation_input_generation"] = {
        "classification": "new_unopened_inputs_after_nominal_lock",
        "locked_nominals": str(locked_path),
        "zeeman_seeds": list(FINAL_VALIDATION_ZEEMAN_SEEDS),
        "mot_seeds": list(FINAL_VALIDATION_MOT_SEEDS),
        "zeeman_job": str(zeeman_job),
        "mot_job": str(mot_job),
        "freeze_job": str(freeze_job),
        "input_manifest": str(base / "input_manifest.json"),
    }
    save_file_json(root / "campaign.json", manifest)


def _collect_final_validation_inputs(root, manifest):
    stage = manifest["stages"]["final_validation_input_generation"]
    states_dir = root / "final_validation_inputs" / "after_2d_mot"
    zeeman_dir = root / "final_validation_inputs" / "after_zeeman"
    replicate_dir = root / "final_validation_inputs" / "mot_2d_records" / "replicates"
    expected_zeeman_names = {
        f"production_zeeman_n50000_dt40us_seed{seed}{suffix}"
        for seed in FINAL_VALIDATION_ZEEMAN_SEEDS for suffix in (".npy", ".json")
    }
    expected_state_names = {
        f"mot_2d_survivors_zeeman_seed{zseed}_mot_seed{mseed}{suffix}"
        for zseed, mseed in zip(FINAL_VALIDATION_ZEEMAN_SEEDS, FINAL_VALIDATION_MOT_SEEDS)
        for suffix in (".npy", ".json")
    }
    expected_replicates = {
        f"zeeman_seed{seed}.json" for seed in FINAL_VALIDATION_ZEEMAN_SEEDS
    }
    if (
        {path.name for path in zeeman_dir.iterdir() if path.is_file()} != expected_zeeman_names
        or {path.name for path in states_dir.iterdir() if path.is_file()} != expected_state_names
        or {path.name for path in replicate_dir.iterdir() if path.is_file()} != expected_replicates
    ):
        raise RuntimeError("Final-validation generation registry is incomplete or contaminated.")
    expected_params = manifest["upstream_2d_campaign"]["expected_survivor_parameters"]
    ensembles = []
    for zseed, mseed in zip(FINAL_VALIDATION_ZEEMAN_SEEDS, FINAL_VALIDATION_MOT_SEEDS):
        zeeman_path = root / "final_validation_inputs" / "after_zeeman" / (
            f"production_zeeman_n50000_dt40us_seed{zseed}.npy"
        )
        zeeman_metadata_path = zeeman_path.with_suffix(".json")
        if not zeeman_path.is_file() or not zeeman_metadata_path.is_file():
            raise FileNotFoundError(f"Missing new Zeeman ensemble: {zeeman_path}")
        zeeman_metadata = json.loads(zeeman_metadata_path.read_text(encoding="utf-8"))
        if (
            zeeman_metadata.get("parameters", {}).get("seed") != zseed
            or zeeman_metadata.get("parameters", {}).get("resolved_zeeman_magnet_profile")
            != manifest["upstream_2d_campaign"]["expected_survivor_design"]["zeeman_profile"]
            or zeeman_metadata.get("output_sha256") != _sha256(zeeman_path)
        ):
            raise ValueError(f"Invalid new Zeeman ensemble: {zeeman_path}")
        path = states_dir / f"mot_2d_survivors_zeeman_seed{zseed}_mot_seed{mseed}.npy"
        metadata_path = path.with_suffix(".json")
        if not path.is_file() or not metadata_path.is_file():
            raise FileNotFoundError(f"Missing new sealed survivor ensemble: {path}")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        replicate_path = replicate_dir / f"zeeman_seed{zseed}.json"
        replicate = json.loads(replicate_path.read_text(encoding="utf-8"))
        values = np.load(path, mmap_mode="r")
        design = metadata.get("design", {})
        expected_design = {
            "dt_s": MOT_2D_SIM_CONFIG["dt_s"],
            "stochastic_solver": manifest["upstream_2d_campaign"]["expected_survivor_design"]["stochastic_solver"],
            "uses_all_available_particles": True,
            "npools": 200,
            "ensemble_dir": str(zeeman_dir),
            "zeeman_profile": manifest["upstream_2d_campaign"]["expected_survivor_design"]["zeeman_profile"],
            "git_commit": manifest["provenance"]["git_commit"],
        }
        if (
            metadata.get("kind") != "mot_2d_final_survivor_ensemble"
            or metadata.get("zeeman_seed") != zseed
            or metadata.get("mot_seed") != mseed
            or metadata.get("parameters") != expected_params
            or design != expected_design
            or Path(metadata.get("source_zeeman_ensemble", "")).resolve() != zeeman_path.resolve()
            or replicate.get("kind") != "mot_2d_final_production_replicate"
            or replicate.get("parameters") != expected_params
            or replicate.get("design") != expected_design
            or replicate.get("replicate", {}).get("zeeman_seed") != zseed
            or replicate.get("replicate", {}).get("mot_seed") != mseed
            or Path(replicate.get("replicate", {}).get("ensemble_file", "")).resolve()
            != zeeman_path.resolve()
            or replicate.get("replicate", {}).get("captured") != len(values)
            or list(values.shape) != metadata.get("shape")
            or metadata.get("output_sha256") != _sha256(path)
            or len(values) == 0
            or not np.all(np.isfinite(values))
        ):
            raise ValueError(f"Invalid new sealed survivor ensemble: {path}")
        ensembles.append({
            "zeeman_seed": zseed,
            "mot_seed": mseed,
            "path": str(path.resolve()),
            "metadata_path": str(metadata_path.resolve()),
            "sha256": _sha256(path),
            "metadata_sha256": _sha256(metadata_path),
            "replicate_path": str(replicate_path.resolve()),
            "replicate_sha256": _sha256(replicate_path),
            "zeeman_path": str(zeeman_path.resolve()),
            "zeeman_sha256": _sha256(zeeman_path),
            "zeeman_metadata_path": str(zeeman_metadata_path.resolve()),
            "zeeman_metadata_sha256": _sha256(zeeman_metadata_path),
            "shape": list(values.shape),
            "n_survivors": len(values),
        })
    return ensembles


def freeze_final_validation_inputs(campaign):
    root = Path(campaign)
    manifest = json.loads((root / "campaign.json").read_text(encoding="utf-8"))
    if manifest.get("stage") != "final_validation_input_generation":
        raise RuntimeError("Campaign is not awaiting final-validation inputs.")
    stage = manifest["stages"]["final_validation_input_generation"]
    destination = Path(stage["input_manifest"])
    if destination.exists():
        raise FileExistsError(f"Final-validation inputs are already frozen: {destination}")
    ensembles = _collect_final_validation_inputs(root, manifest)
    submission = root / "final_validation_input_generation_submission.json"
    payload = {
        "kind": "mot_3d_final_validation_inputs",
        "classification": "newly_generated_sealed_after_nominal_lock",
        "locked_nominals_sha256": _sha256(stage["locked_nominals"]),
        "solver": manifest["design"]["solver"],
        "campaign_name": manifest["name"],
        "git_commit": manifest["provenance"]["git_commit"],
        "physical_model_sha256": manifest["provenance"]["physical_model_sha256"],
        "generation_submission_sha256": _sha256(submission),
        "generation_jobs": json.loads(submission.read_text(encoding="utf-8")),
        "ensembles": ensembles,
        "total_survivors": sum(row["n_survivors"] for row in ensembles),
    }
    save_file_json(destination, payload)
    return payload


def validate_final_validation_inputs(root, manifest):
    stage = manifest["stages"]["final_validation_input_generation"]
    path = Path(stage["input_manifest"])
    if not path.is_file():
        raise FileNotFoundError("Final-validation input manifest has not been frozen.")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        payload.get("kind") != "mot_3d_final_validation_inputs"
        or payload.get("locked_nominals_sha256") != _sha256(stage["locked_nominals"])
        or payload.get("campaign_name") != manifest["name"]
        or payload.get("git_commit") != manifest["provenance"]["git_commit"]
        or payload.get("physical_model_sha256") != manifest["provenance"]["physical_model_sha256"]
        or payload.get("solver") != manifest["design"]["solver"]
        or payload.get("generation_submission_sha256")
        != _sha256(root / "final_validation_input_generation_submission.json")
        or len(payload.get("ensembles", [])) != len(FINAL_VALIDATION_ZEEMAN_SEEDS)
    ):
        raise ValueError("Invalid final-validation input manifest.")
    observed = _collect_final_validation_inputs(Path(root), manifest)
    if observed != payload["ensembles"]:
        raise ValueError("Frozen final-validation metadata no longer matches its artifacts.")
    for row, zseed, mseed in zip(
        payload["ensembles"], FINAL_VALIDATION_ZEEMAN_SEEDS, FINAL_VALIDATION_MOT_SEEDS
    ):
        if (
            row.get("zeeman_seed") != zseed
            or row.get("mot_seed") != mseed
            or _sha256(row["path"]) != row.get("sha256")
            or _sha256(row["metadata_path"]) != row.get("metadata_sha256")
            or _sha256(row["replicate_path"]) != row.get("replicate_sha256")
            or _sha256(row["zeeman_path"]) != row.get("zeeman_sha256")
            or _sha256(row["zeeman_metadata_path"]) != row.get("zeeman_metadata_sha256")
        ):
            raise ValueError("Frozen final-validation ensemble registry mismatch.")
    return payload


def prepare_final_validation(root, manifest):
    stage = manifest["stages"]["final_validation_input_generation"]
    input_manifest = Path(stage["input_manifest"])
    submission = root / "final_validation_input_generation_submission.json"
    if not submission.is_file() or json.loads(submission.read_text()).get("status") != "submitted":
        raise RuntimeError("Final-validation input generation has no complete submission record.")
    validate_final_validation_inputs(root, manifest)
    locked = Path(stage["locked_nominals"])
    jobs = root / "jobs" / "final_validation"
    worker_jobs, merge_jobs = {}, {}
    dt = manifest["design"]["production_dt_s"]
    for family in FAMILIES:
        short = "don" if family == "angled_donut" else "sp"
        family_root = root / "final_validation" / family
        worker_jobs[family] = _write(
            jobs / f"{family}_array.pbs",
            _header(f"m3d2_{short}_val", manifest["provenance"]["git_commit"])
            + 'seeds=(44001 44002 44003)\nseed="${seeds[$PBS_ARRAY_INDEX]}"\n'
            + f"python -u -m studies.mot_3d_final_validation run --family {family} "
            f"--recoil-seed \"$seed\" --locked-nominals {locked} "
            f"--input-manifest {input_manifest} --campaign-manifest {root/'campaign.json'} "
            f"--output {family_root}/seed_${{seed}}.json --npools 200 --dt {dt}\n",
        )
        merge_jobs[family] = _write(
            jobs / f"{family}_merge.pbs",
            _header(f"m3d2_{short}_valm", manifest["provenance"]["git_commit"], "02:00:00", 1, "8gb")
            + f"python -u -m studies.mot_3d_final_validation merge "
            f"--family {family} --input-root {family_root} "
            f"--locked-nominals {locked} --input-manifest {input_manifest} "
            f"--campaign-manifest {root/'campaign.json'} --dt {dt} "
            f"--output {family_root}/final_validation_summary.json "
            "--bootstrap-replicates 20000 --bootstrap-seed 92001\n",
        )
    manifest["stage"] = "final_validation"
    manifest.setdefault("stages", {})["final_validation"] = {
        "classification": "sealed_unbiased_final_validation",
        "locked_nominals": str(locked),
        "input_manifest": str(input_manifest),
        "worker_jobs": {key: str(value) for key, value in worker_jobs.items()},
        "merge_jobs": {key: str(value) for key, value in merge_jobs.items()},
    }
    save_file_json(root / "campaign.json", manifest)


def _validate_precision_decision(interval, stored_half_width, stored_decision, target=0.0075):
    if len(interval) != 2 or not all(np.isfinite(value) for value in interval):
        raise ValueError("Final-validation confidence interval is invalid.")
    recomputed = float((interval[1] - interval[0]) / 2)
    if (
        not isinstance(stored_half_width, (int, float))
        or not np.isfinite(stored_half_width)
        or not np.isclose(stored_half_width, recomputed, rtol=0.0, atol=1e-12)
        or bool(stored_decision) != (recomputed <= target)
    ):
        raise ValueError("Final-validation precision decision is inconsistent.")
    return recomputed, recomputed <= target


def _final_report_artifact(precision_met):
    if precision_met:
        return (
            "final_report.json",
            "mot_3d_campaign_final_report",
            "unbiased_claim_from_newly_generated_sealed_ensembles",
            "complete",
            "final_report",
        )
    return (
        "final_validation_status.json",
        "mot_3d_final_validation_extension_status",
        "unbiased_estimate_precision_target_not_met_not_final_claim",
        "final_validation_extension_required",
        "final_validation_status",
    )


def complete_final_validation(root, manifest):
    stage = manifest["stages"]["final_validation"]
    submission = root / "final_validation_submission.json"
    if not submission.is_file() or json.loads(submission.read_text()).get("status") != "submitted":
        raise RuntimeError("Final validation has no complete submission record.")
    results = {}
    result_hashes = {}
    precision_met = True
    locked = json.loads(Path(stage["locked_nominals"]).read_text(encoding="utf-8"))
    inputs = validate_final_validation_inputs(root, manifest)
    for family in FAMILIES:
        path = root / "final_validation" / family / "final_validation_summary.json"
        if not path.is_file():
            raise RuntimeError(f"Missing sealed final-validation summary: {path}")
        summary = json.loads(path.read_text(encoding="utf-8"))
        interval = summary.get("bootstrap_95_ci", [])
        half_width = summary.get("ci_half_width")
        recomputed_half_width, computed_precision = _validate_precision_decision(
            interval, half_width, summary.get("precision_target_met")
        )
        expected_design = {
            "campaign_manifest_sha256": _sha256(root / "campaign.json"),
            "locked_nominals_sha256": _sha256(stage["locked_nominals"]),
            "input_manifest_sha256": _sha256(stage["input_manifest"]),
            "family": family,
            "dt_s": manifest["design"]["production_dt_s"],
            "t_max_s": 0.1,
            "solver": manifest["design"]["solver"],
            "classification": "sealed_unbiased_final_validation",
        }
        efficiency = summary.get("conditional_efficiency")
        predictive = summary.get("new_equivalent_ensemble_predictive_95_interval", [])
        if (
            summary.get("kind") != "mot_3d_sealed_final_validation_summary"
            or summary.get("family") != family
            or summary.get("classification")
            != "sealed_unbiased_estimate_pending_precision_gate"
            or summary.get("bootstrap_replicates") != 20_000
            or summary.get("bootstrap_seed") != 92_001
            or summary.get("candidate_id") != locked["families"][family]["candidate_id"]
            or summary.get("ensemble_count") != len(inputs["ensembles"])
            or summary.get("recoil_seed_count") != 3
            or summary.get("input_particle_count") != inputs["total_survivors"]
            or summary.get("estimand") != "survivor-weighted conditional capture fraction"
            or summary.get("target_half_width") != 0.0075
            or summary.get("precision_target_met") != computed_precision
            or len(interval) != 2
            or not all(np.isfinite(value) for value in interval)
            or not isinstance(efficiency, (int, float))
            or not np.isfinite(efficiency)
            or not (0.0 <= interval[0] <= efficiency <= interval[1] <= 1.0)
            or summary.get("design") != expected_design
            or summary.get("bootstrap_method")
            != "crossed ensemble/recoil bootstrap with within-ensemble particle resampling"
            or summary.get("expected_usable_per_10m_2d_survivors") != 10_000_000 * efficiency
            or summary.get("expected_usable_per_10m_95_ci")
            != [10_000_000 * value for value in interval]
            or summary.get("predictive_method")
            != "empirical random-effects bootstrap of ensemble and recoil effects plus finite-particle binomial variation"
            or len(predictive) != 2
            or not all(np.isfinite(value) for value in predictive)
            or not (0.0 <= predictive[0] <= predictive[1] <= 1.0)
        ):
            raise ValueError(f"Invalid sealed final-validation summary: {path}")
        precision_met &= bool(summary.get("precision_target_met"))
        results[family] = summary
        result_hashes[family] = _sha256(path)
    filename, kind, classification, next_stage, registry_key = _final_report_artifact(
        precision_met
    )
    report = {
        "kind": kind,
        "classification": classification,
        "conditional_efficiency_denominator": "survivors leaving the selected 2D MOT",
        "results": results,
        "result_summary_sha256": result_hashes,
        "precision_target_met_for_both_families": precision_met,
        "selection_data_excluded_from_claim": True,
    }
    destination = root / filename
    save_file_json(destination, report)
    manifest["stage"] = next_stage
    manifest.setdefault("stages", {})[registry_key] = str(destination)
    save_file_json(root / "campaign.json", manifest)


def validate_stage_complete(root, manifest, stage):
    submission = root / f"{stage}_submission.json"
    if not submission.is_file():
        raise RuntimeError(f"Missing submission record for {stage}.")
    submitted = json.loads(submission.read_text(encoding="utf-8"))
    if submitted.get("status") != "submitted" or submitted.get("stage") != stage:
        raise RuntimeError(f"Stage {stage} was not completely submitted.")
    design = manifest.get("stages", {}).get(stage, {})
    summary_name = {
        "preliminary_check": "early_check_summary.json",
        "refinement": "refinement_summary.json",
        "closure": "refinement_summary.json",
        "finalist_selection": "finalist_summary.json",
    }[stage]
    expected_kind = {
        "preliminary_check": "merged_mot_3d_early_independent_check",
        "refinement": "merged_mot_3d_focused_refinement",
        "closure": "merged_mot_3d_focused_refinement",
        "finalist_selection": "merged_mot_3d_finalist_selection",
    }[stage]
    expected_bootstrap_seed = {
        "preliminary_check": 52_001,
        "refinement": 62_001,
        "closure": 72_001,
        "finalist_selection": 82_001,
    }[stage]
    for family in FAMILIES:
        summary_path = root / stage / family / "merged" / summary_name
        if not summary_path.is_file():
            raise RuntimeError(f"Stage {stage} incomplete: {summary_path}")
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if summary.get("kind") != expected_kind or summary.get("family") != family:
            raise ValueError(f"Stage {stage} summary family mismatch.")
        selection_path = Path(design["selection_files"][family])
        selection = json.loads(selection_path.read_text(encoding="utf-8"))
        if summary.get("candidate_count") != selection.get("candidate_count"):
            raise ValueError(f"Stage {stage} summary candidate count mismatch.")
        if (
            summary.get("bootstrap_replicates") != 10_000
            or summary.get("bootstrap_seed") != expected_bootstrap_seed
            or summary.get("multiplicity_method")
            != "paired centered-bootstrap max-T simultaneous intervals"
        ):
            raise ValueError(f"Stage {stage} summary inference design mismatch.")
        if summary.get("selection_sha256") != _sha256(selection_path):
            raise ValueError(f"Stage {stage} summary selection hash mismatch.")
        result_design = summary.get("design", {})
        if result_design.get("campaign_manifest_sha256") != _sha256(root / "campaign.json"):
            raise ValueError(f"Stage {stage} summary campaign hash mismatch.")


def advance_campaign(args):
    root = Path(args.campaign)
    manifest = json.loads((root / "campaign.json").read_text(encoding="utf-8"))
    stage = manifest.get("stage")
    if stage == "discovery":
        submission = root / "discovery_submission.json"
        if not submission.is_file() or json.loads(submission.read_text()).get("status") != "submitted":
            raise RuntimeError("Discovery has no complete submission record.")
        prepare_preliminary_check(root, manifest)
    elif stage == "preliminary_check":
        validate_stage_complete(root, manifest, stage)
        prepare_refinement(root, manifest)
    elif stage == "refinement":
        validate_stage_complete(root, manifest, stage)
        prepare_closure(root, manifest)
    elif stage == "closure":
        validate_stage_complete(root, manifest, stage)
        prepare_finalist_selection(root, manifest)
    elif stage == "finalist_selection":
        validate_stage_complete(root, manifest, stage)
        prepare_final_validation_inputs(root, manifest)
    elif stage == "final_validation_input_generation":
        prepare_final_validation(root, manifest)
    elif stage == "final_validation":
        complete_final_validation(root, manifest)
    else:
        raise RuntimeError(f"No Stage-C transition is available from {stage!r}.")


def submit_selection_stage(campaign, qsub=None):
    root = Path(campaign)
    manifest = json.loads((root / "campaign.json").read_text(encoding="utf-8"))
    stage = manifest.get("stage")
    if stage not in (
        "preliminary_check", "refinement", "closure", "finalist_selection",
        "final_validation",
    ):
        raise RuntimeError(f"No selection-stage submission at {stage!r}.")
    design = manifest.get("stages", {}).get(stage)
    if not design:
        raise RuntimeError(f"Stage {stage!r} has no frozen job design.")
    destination = root / f"{stage}_submission.json"
    try:
        descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        raise FileExistsError(f"Stage was already submitted: {destination}")
    else:
        os.close(descriptor)
    runner = qsub or (
        lambda command: subprocess.check_output(command, text=True).strip()
    )
    record = {
        "kind": "mot_3d_selection_stage_submission",
        "stage": stage,
        "status": "submitting",
        "dependency": "afterok",
        "families": {},
    }
    save_file_json(destination, record)
    try:
        for family in FAMILIES:
            array_id = runner(["qsub", "-J", "0-2:1", design["worker_jobs"][family]])
            record["families"][family] = {
                "array_job_id": array_id,
                "merge_job_id": None,
            }
            save_file_json(destination, record)
            merge_id = runner([
                "qsub", "-W", f"depend=afterok:{array_id}",
                design["merge_jobs"][family],
            ])
            record["families"][family]["merge_job_id"] = merge_id
            save_file_json(destination, record)
        record["status"] = "submitted"
        save_file_json(destination, record)
    except BaseException as error:
        record["status"] = "partial_failure"
        record["error"] = f"{type(error).__name__}: {error}"
        save_file_json(destination, record)
        raise
    return record


def submit_final_validation_inputs(campaign, qsub=None):
    root = Path(campaign)
    manifest = json.loads((root / "campaign.json").read_text(encoding="utf-8"))
    if manifest.get("stage") != "final_validation_input_generation":
        raise RuntimeError("Campaign is not ready to generate final-validation inputs.")
    stage = manifest["stages"]["final_validation_input_generation"]
    artifact_root = root / "final_validation_inputs"
    if artifact_root.exists() and any(
        path.is_file() for path in artifact_root.rglob("*")
    ):
        raise RuntimeError(
            "Final-validation input directory is not empty; refuse to mix or overwrite artifacts."
        )
    destination = root / "final_validation_input_generation_submission.json"
    try:
        descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        raise FileExistsError(f"Input generation was already submitted: {destination}")
    else:
        os.close(descriptor)
    runner = qsub or (lambda command: subprocess.check_output(command, text=True).strip())
    record = {"kind": "mot_3d_final_validation_input_submission", "status": "submitting"}
    save_file_json(destination, record)
    try:
        zeeman = runner(["qsub", "-J", "0-19:1", stage["zeeman_job"]])
        record["zeeman_array_job_id"] = zeeman
        save_file_json(destination, record)
        mot = runner(["qsub", "-W", f"depend=afterok:{zeeman}", "-J", "0-19:1", stage["mot_job"]])
        record["mot_array_job_id"] = mot
        save_file_json(destination, record)
        freeze = runner(["qsub", "-W", f"depend=afterok:{mot}", stage["freeze_job"]])
        record["freeze_job_id"] = freeze
        record["status"] = "submitted"
        save_file_json(destination, record)
    except BaseException as error:
        record["status"] = "partial_failure"
        record["error"] = f"{type(error).__name__}: {error}"
        save_file_json(destination, record)
        raise
    return record


def submit_stage_command(args):
    submit_selection_stage(args.campaign)


def submit_final_inputs_command(args):
    submit_final_validation_inputs(args.campaign)


def freeze_final_inputs_command(args):
    freeze_final_validation_inputs(args.campaign)


def create(args):
    dirty = _dirty_relevant_files()
    if dirty:
        raise RuntimeError(
            "Refusing to freeze a campaign with dirty relevant files: "
            + ", ".join(dirty)
        )
    root = Path(args.output_dir)
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(f"Campaign directory is not empty: {root}")
    upstream = validate_upstream_2d_campaign(args.upstream_campaign, args.input_dir)
    expected_pairs = {
        row["zeeman_seed"]: row["mot_seed"] for row in upstream["sealed_seed_pairs"]
    }
    roles = freeze_inputs(
        args.input_dir,
        expected_seed_pairs=expected_pairs,
        expected_design=upstream["expected_survivor_design"],
        expected_parameters=upstream["expected_survivor_parameters"],
    )
    revision = _revision()
    root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "kind": "mot_3d_campaign_v2",
        "name": args.name,
        # Discovery is deliberately blocked until the new 2D survivors have
        # been used for a paired 3D-MOT timestep-convergence check.
        "stage": "dt_validation_required",
        "provenance": {
            "git_commit": revision,
            "physical_model_sha256": _relevant_hash(),
        },
        "input_directory": str(Path(args.input_dir).resolve()),
        "upstream_2d_campaign": upstream,
        "input_roles": roles,
        "design": {
            "families": list(FAMILIES),
            "solver": MOT_3D_SIM_CONFIG["solver"],
            "screening_dt_s": MOT_3D_SIM_CONFIG["screening_dt_s"],
            "production_dt_s": MOT_3D_SIM_CONFIG["production_dt_s"],
            "timestep_status": "provisional_pending_3d_validation",
            "dt_validation_candidates_s": list(
                MOT_3D_SIM_CONFIG["dt_validation_candidates_s"]
            ),
            "dt_validation_reference_s": MOT_3D_SIM_CONFIG[
                "dt_validation_reference_s"
            ],
            "green_full_angle_deg": 62.0,
            "donut_shared_aperture_radius_m": 0.005,
            "single_pass_green_aperture_radius_m": 0.005,
            "single_pass_blue_aperture_radius_m": 0.0075,
            "power_feasibility_status": "unknown_no_experimental_power_cap_provided",
            "power_policy": (
                "record per-candidate power proxies and boundary hits; do not "
                "reject trials or claim laboratory feasibility"
            ),
            "selection_statistics": {
                "estimand": "survivor-weighted conditional capture fraction",
                "alpha": 0.05,
                "bootstrap_replicates": 10_000,
                "multiplicity": "paired max-T simultaneous confidence bounds",
                "ranking_rule": "largest lower endpoint of the simultaneous two-sided 95% interval",
            },
            "optimization_bounds": MOT_3D_OPTIMIZATION_CONFIG,
            "final_validation_inputs": "newly generated and sealed after finalist selection",
        },
    }
    save_file_json(root / "campaign.json", manifest)
    smoke, rounds, submitter = write_discovery_jobs(root, revision)
    manifest["jobs"] = {
        "smoke": {key: str(value) for key, value in smoke.items()},
        "discovery_rounds": {
            family: [str(path) for path in paths]
            for family, paths in rounds.items()
        },
        "discovery_submit_chain": str(submitter),
        "dependency": "afterok",
    }
    save_file_json(root / "campaign.json", manifest)
    print(f"Campaign created: {root/'campaign.json'}")
    print("No jobs were submitted.")


def status(args):
    manifest = json.loads((Path(args.campaign) / "campaign.json").read_text())
    print(f"Campaign: {manifest['name']}")
    print(f"Current stage: {manifest['stage']}")
    for role, rows in manifest["input_roles"].items():
        print(f"{role}: {len(rows)} ensembles, {sum(row['n_survivors'] for row in rows)} atoms")


def approve_timestep(args):
    root = Path(args.campaign)
    manifest_path = root / "campaign.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("stage") != "dt_validation_required":
        raise RuntimeError("Campaign is not awaiting timestep validation.")
    evidence_path = Path(args.evidence).resolve()
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    expected = manifest["design"]
    if (
        evidence.get("kind") != "mot_3d_timestep_validation"
        or evidence.get("status") != "approved"
        or evidence.get("screening_dt_s") != expected["screening_dt_s"]
        or evidence.get("production_dt_s") != expected["production_dt_s"]
        or evidence.get("reference_dt_s") != expected["dt_validation_reference_s"]
        or evidence.get("tested_dt_s") != expected["dt_validation_candidates_s"]
        or evidence.get("capture_bias_passed") is not True
        or evidence.get("paired_decision_passed") is not True
    ):
        raise ValueError("Timestep evidence does not approve the frozen campaign design.")
    manifest["design"]["timestep_status"] = "approved_by_paired_convergence_validation"
    manifest["design"]["timestep_evidence"] = {
        "path": str(evidence_path),
        "sha256": _sha256(evidence_path),
    }
    manifest["stage"] = "discovery"
    save_file_json(manifest_path, manifest)


def submit_discovery_command(args):
    submit_discovery(args.campaign)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("create")
    command.add_argument("--name", required=True)
    command.add_argument("--input-dir", required=True)
    command.add_argument("--upstream-campaign", required=True)
    command.add_argument("--output-dir", required=True)
    command.set_defaults(func=create)
    command = commands.add_parser("status")
    command.add_argument("--campaign", required=True)
    command.set_defaults(func=status)
    command = commands.add_parser("approve-dt")
    command.add_argument("--campaign", required=True)
    command.add_argument("--evidence", required=True)
    command.set_defaults(func=approve_timestep)
    command = commands.add_parser("submit-discovery")
    command.add_argument("--campaign", required=True)
    command.set_defaults(func=submit_discovery_command)
    command = commands.add_parser("advance")
    command.add_argument("--campaign", required=True)
    command.set_defaults(func=advance_campaign)
    command = commands.add_parser("submit-stage")
    command.add_argument("--campaign", required=True)
    command.set_defaults(func=submit_stage_command)
    command = commands.add_parser("submit-final-inputs")
    command.add_argument("--campaign", required=True)
    command.set_defaults(func=submit_final_inputs_command)
    command = commands.add_parser("freeze-final-inputs")
    command.add_argument("--campaign", required=True)
    command.set_defaults(func=freeze_final_inputs_command)
    return parser.parse_args(argv)


if __name__ == "__main__":
    arguments = parse_args()
    arguments.func(arguments)
