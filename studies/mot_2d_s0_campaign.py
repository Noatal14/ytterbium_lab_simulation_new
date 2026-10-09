"""Resumable corrected-Zeeman 2D-MOT optimization at supplied fixed s0 values."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shlex
import subprocess
import sys
from pathlib import Path

from config import MOT_2D_SIM_CONFIG
from studies.mot_2d.optimization import BOUNDS_DETUNING, BOUNDS_MAGNET_RADIUS_M
from studies.mot_2d.optimization import evaluate_configuration
from studies.mot_2d.production import summarize
from utils.RK4StHybridCustom import RK4StHybridCustom
from utils.file_helpers import save_file_json
from utils.mot_2d_study import load_production_ensembles, student_mean_interval
from workflow_api.mot_2d_spec import RELEVANT_FILES, ROLE_SEEDS
from workflow_api.mot_2d_smoke import validate_smoke_outputs
from workflow_api.mot_2d_screen import validate_screen_outputs
from workflow_api.repository_paths import canonical_repo_relative, resolve_repo_relative

FINAL_DT_S = MOT_2D_SIM_CONFIG["dt_s"]
WORKING_DT_S = 1.25e-6
TARGET = 0.0005
D_RES = 0.01
R_RES = 0.01e-3
SCREEN_TRIALS = 17
REFINE_TRIALS = 10
REFINEMENT_CUMULATIVE_TARGETS = (3, 6, 9, 10)
SCREEN_WALLTIME = "24:00:00"
REFINEMENT_ROUND_WALLTIME = "20:00:00"
CONFIRMATION_CANDIDATES = 5
CAPTURE_CRITERION_VERSION = "mot_2d_extract_survivors_v1"
DEFAULT_PROFILE = "corrected_projectant_19ring_20261005"
DEFAULT_ENSEMBLE_DIR = str(Path("data/particle_states/after_zeeman") / DEFAULT_PROFILE)
SEED_ROLES = ROLE_SEEDS
STAGE_ROLE = {"smoke": "discovery", "screen": "discovery",
              "refine": "refinement", "confirmation": "held_out_confirmation",
              "sensitivity": "held_out_confirmation", "production": "sealed_validation"}
RELEVANT_CODE_FILES = list(RELEVANT_FILES)
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def repository_relative(path, *, require):
    return canonical_repo_relative(
        REPOSITORY_ROOT, path,
        allowed_root="data/particle_states/after_zeeman", require=require,
    )


def repository_path(value):
    return resolve_repo_relative(
        REPOSITORY_ROOT, value,
        allowed_root="data/particle_states/after_zeeman", require="dir",
    )


def campaign_identity(path):
    return canonical_repo_relative(
        REPOSITORY_ROOT, path,
        allowed_root="data/optimization/mot_2d", require="dir",
    )


def git_commit():
    return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()


def physical_model_hash():
    digest = hashlib.sha256()
    paths = [Path(path) for path in RELEVANT_CODE_FILES]
    paths.extend(sorted(Path("lab_setup").rglob("*.py")))
    for path in paths:
        digest.update(path.as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def relevant_code_files():
    return RELEVANT_CODE_FILES + [
        path.as_posix() for path in sorted(Path("lab_setup").rglob("*.py"))
    ]


def assert_relevant_worktree_clean():
    dirty = subprocess.check_output(
        ["git", "status", "--porcelain", "--", *relevant_code_files()], text=True
    ).strip()
    if dirty:
        raise RuntimeError("Relevant campaign/scientific files are dirty:\n" + dirty)


def freeze_input_ensembles(directory, profile, seed_roles):
    directory = repository_path(repository_relative(directory, require="dir"))
    records = {}
    for role, seeds in seed_roles.items():
        ensembles = load_production_ensembles(
            directory=directory, zeeman_seeds=seeds, expected_profile=profile
        )
        records[role] = []
        for row in ensembles:
            metadata = read(row["metadata_path"])
            parameters = metadata["parameters"]
            required = (row["sha256"], metadata.get("shape"), metadata.get("dtype"),
                        metadata.get("n_survivors"), row["source_git_commit"],
                        parameters.get("dt_s"), parameters.get("n_initial_atoms"))
            if any(value is None for value in required):
                raise ValueError(f"Incomplete immutable provenance in {row['metadata_path']}")
            records[role].append({
                "zeeman_seed": row["zeeman_seed"],
                "path": repository_relative(row["path"], require="file"),
                "metadata_path": repository_relative(row["metadata_path"], require="file"),
                "sha256": row["sha256"],
                "metadata_sha256": hashlib.sha256(Path(row["metadata_path"]).read_bytes()).hexdigest(),
                "shape": metadata["shape"],
                "dtype": metadata["dtype"], "survivor_count": metadata["n_survivors"],
                "zeeman_profile": row["zeeman_profile"],
                "source_git_commit": row["source_git_commit"],
                "generation": {"n_initial_atoms": parameters["n_initial_atoms"],
                               "dt_s": parameters["dt_s"],
                               "stochastic": parameters.get("stochastic"),
                               "collimation_angle_deg": parameters.get("collimation_angle_deg")},
            })
    return records


def assert_design(manifest):
    assert_relevant_worktree_clean()
    if git_commit() != manifest["provenance"]["git_commit"]:
        raise RuntimeError("Git revision differs from the immutable campaign revision.")
    if physical_model_hash() != manifest["provenance"]["physical_model_sha256"]:
        raise RuntimeError("Physical-model files differ from the campaign design.")


def stage_ensembles(manifest, stage, particles):
    if manifest.get("provenance", {}).get("path_contract") != "repository-relative-v1":
        raise RuntimeError(
            "This legacy campaign is not portable and cannot be continued by the current runner."
        )
    role = STAGE_ROLE[stage]
    seeds = manifest["seed_roles"][role]
    ensembles = load_production_ensembles(
        particles_per_ensemble=particles,
        directory=repository_path(manifest["ensemble_source"]["directory"]),
        zeeman_seeds=seeds,
        expected_profile=manifest["ensemble_source"]["zeeman_profile"],
    )
    frozen = {row["zeeman_seed"]: row for row in manifest["input_ensembles"][role]}
    for row in ensembles:
        record = frozen.get(row["zeeman_seed"])
        observed = {"path": repository_relative(row["path"], require="file"),
                    "metadata_path": repository_relative(row["metadata_path"], require="file"),
                    "sha256": row["sha256"], "shape": row["shape"],
                    "metadata_sha256": hashlib.sha256(
                        Path(row["metadata_path"]).read_bytes()
                    ).hexdigest(),
                    "dtype": row["dtype"], "survivor_count": row["n_available"],
                    "zeeman_profile": row["zeeman_profile"],
                    "source_git_commit": row["source_git_commit"],
                    "generation": row["generation"]}
        if record is None or any(record[field] != value for field, value in observed.items()):
            raise RuntimeError(f"Frozen Zeeman input changed for seed {row['zeeman_seed']}")
    return ensembles


def key(value):
    return f"s0_{float(value):.6f}".replace(".", "p")


def label(value):
    return f"{float(value):.6f}".rstrip("0").rstrip(".")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def paths(root):
    root = Path(root)
    return root, root / "campaign.json", root / "jobs"


def write_pbs(path, name, array, ncpus, walltime, command, revision=None):
    throttle = 3 if ncpus == 200 else 4 if ncpus == 150 else 1
    array_line = ""
    scalar_index_line = ""
    if array:
        single_index = re.fullmatch(r"(\d+)-(\d+)", array)
        if single_index and single_index.group(1) == single_index.group(2):
            index = single_index.group(1)
            scalar_index_line = f"export PBS_ARRAY_INDEX={index}\n"
        else:
            array_line = f"#PBS -J {array}%{throttle}\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"""#!/bin/bash
#PBS -N {name}
#PBS -q zeus_combined_q
{array_line}#PBS -l select=1:ncpus={ncpus}:mem=64gb
#PBS -l walltime={walltime}

set -euo pipefail
PROJECT_ROOT="${{HOME}}/ytterbium_lab_simulation_new"
cd -- "${{PROJECT_ROOT}}" || exit 1
module load SPACK/apps
module load gcc/14.1.0
module load python/3.14.2
source "${{HOME}}/venvs/atomsmltr/bin/activate"
{scalar_index_line}EXPECTED_COMMIT={revision or git_commit()}
ACTUAL_COMMIT=$(git rev-parse HEAD)
if [ "${{ACTUAL_COMMIT}}" != "${{EXPECTED_COMMIT}}" ]; then
  echo "Commit mismatch: expected ${{EXPECTED_COMMIT}}, found ${{ACTUAL_COMMIT}}" >&2
  exit 42
fi
RUN_TMP="/tmp/${{USER}}_{name}_${{PBS_JOBID}}_${{PBS_ARRAY_INDEX:-0}}"
mkdir -p "${{RUN_TMP}}"
export TMPDIR="${{RUN_TMP}}" TMP="${{RUN_TMP}}" TEMP="${{RUN_TMP}}"
trap 'rm -rf -- "${{RUN_TMP}}"' EXIT
{command}
""", encoding="utf-8")


def create(args):
    root, manifest_path, jobs = paths(args.output_dir)
    values = []
    for value in args.s0:
        value = float(value)
        if not math.isfinite(value) or value <= 0:
            raise ValueError("Every s0 value must be finite and positive.")
        if value not in values:
            values.append(value)
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(f"Campaign already exists: {manifest_path}")
    assert_relevant_worktree_clean()
    revision = git_commit()
    model_hash = physical_model_hash()
    roles = {name: list(values_) for name, values_ in SEED_ROLES.items()}
    all_seeds = [seed for seeds in roles.values() for seed in seeds]
    if len(all_seeds) != len(set(all_seeds)):
        raise ValueError("Campaign seed roles must be non-overlapping.")
    frozen_inputs = freeze_input_ensembles(args.ensemble_dir, args.zeeman_profile, roles)
    # Campaign creation uses the same pure renderer and atomic materializer as
    # the local UI; later campaign stages retain the established writers.
    from workflow_api.mot_2d_plan import materialize, plan_from_frozen_manifest
    from workflow_api.mot_2d_spec import build_manifest
    if roles != ROLE_SEEDS:
        raise RuntimeError("Canonical seed roles drifted from the shared design.")
    manifest = build_manifest(
        name=args.name, s0_values=values,
        ensemble_directory=repository_relative(args.ensemble_dir, require="dir"),
        zeeman_profile=args.zeeman_profile, frozen_inputs=frozen_inputs,
        git_commit=revision, physical_model_sha256=model_hash,
        hashed_files=relevant_code_files(),
    )
    repository_root = REPOSITORY_ROOT
    materialize(plan_from_frozen_manifest(
        repository_root=repository_root, destination=root, manifest=manifest,
    ))
    print(f"Campaign created: {manifest_path}")
    print(f"First job: qsub {jobs / '01_smoke.pbs'}")


def smoke(args):
    root = Path(args.campaign)
    manifest = read(root / "campaign.json")
    assert_design(manifest)
    stage_ensembles(manifest, "smoke", 2)
    value = manifest["s0_values"][args.s0_index]
    output = root / "smoke" / key(value)
    subprocess.run([
        sys.executable, "-m", "studies.mot_2d.optimization", "--fixed-s0", str(value),
        "--n-trials", "1", "--n-ensembles", "1", "--particles-per-ensemble", "2",
        "--npools", "1", "--dt", str(WORKING_DT_S),
        "--stochastic-solver", "hybrid",
        "--ensemble-dir", str(repository_path(manifest["ensemble_source"]["directory"])),
        "--ensemble-identity", manifest["ensemble_source"]["directory"],
        "--zeeman-seeds", str(manifest["seed_roles"]["discovery"][0]),
        "--mot-seeds", str(manifest["mot_seeds"]["discovery"][0]),
        "--campaign-design-id", manifest["provenance"]["physical_model_sha256"],
        "--study-name", f"{manifest['name']}_{key(value)}_smoke", "--output-dir", str(output),
    ], check=True)
    assert read(output / "summary.json")["n_finished_trials"] == 1
    print(f"SMOKE PASS s0={value}")


def prepare(root, manifest, stage, specs, number, ncpus, walltime):
    root_identity = campaign_identity(root)
    save_file_json(root / stage / "tasks.json", specs)
    job = root / "jobs" / f"{number}_{stage}.pbs"
    write_pbs(job, f"mot2d_{stage[:5]}", f"0-{len(specs)-1}", ncpus, walltime,
              f"python -m studies.mot_2d_s0_campaign {stage}-task "
              f"--campaign {shlex.quote(root_identity)} --task-index $PBS_ARRAY_INDEX",
              manifest["provenance"]["git_commit"])
    manifest["stage"] = stage
    manifest["stages"][stage] = {
        "tasks": len(specs),
        "job_file": job.relative_to(REPOSITORY_ROOT).as_posix(),
    }
    save_file_json(root / "campaign.json", manifest)
    print(f"Next job: qsub {job}")


def prepare_screen(root, manifest):
    # A summary file alone is not evidence that the smoke calculation was
    # complete or used the frozen scientific design.  Keep the CLI and UI on
    # one strict validation boundary.
    validate_smoke_outputs(root, manifest)
    specs = [{"s0": value, "worker": worker}
             for value in manifest["s0_values"] for worker in range(3)]
    prepare(root, manifest, "screen", specs, "02", 200, SCREEN_WALLTIME)


def optuna_task(root, stage, spec, trials, particles, sampler_seed, bounds=None):
    manifest = read(root / "campaign.json")
    assert_design(manifest)
    stage_ensembles(manifest, stage, particles)
    role = STAGE_ROLE[stage]
    output = root / stage / key(spec["s0"]) / f"worker{spec['worker']}"
    command = [
        sys.executable, "-m", "studies.mot_2d.optimization", "--fixed-s0", str(spec["s0"]),
        "--n-trials", str(trials), "--n-ensembles", str(len(manifest["seed_roles"][role])),
        "--particles-per-ensemble", str(particles), "--npools", "200",
        "--dt", str(WORKING_DT_S), "--stochastic-solver", "hybrid",
        "--sampler-seed", str(sampler_seed + spec["worker"]),
        "--ensemble-dir", str(repository_path(manifest["ensemble_source"]["directory"])),
        "--ensemble-identity", manifest["ensemble_source"]["directory"],
        "--zeeman-seeds", *map(str, manifest["seed_roles"][role]),
        "--mot-seeds", *map(str, manifest["mot_seeds"][role]),
        "--campaign-design-id", manifest["provenance"]["physical_model_sha256"],
        # All candidate points use the same MOT seeds, including candidates
        # generated by different Optuna workers, so comparisons stay paired.
        "--mot-seed-start", "24000",
        "--study-name", f"{read(root/'campaign.json')['name']}_{stage}_{key(spec['s0'])}_w{spec['worker']}",
        "--output-dir", str(output),
    ]
    if bounds:
        command += ["--detuning-bounds", *map(str, bounds["detuning"]),
                    "--magnet-radius-bounds-m", *map(str, bounds["radius"])]
    subprocess.run(command, check=True)


def screen_task(args):
    root = Path(args.campaign)
    spec = read(root / "screen" / "tasks.json")[args.task_index]
    optuna_task(root, "screen", spec, SCREEN_TRIALS, 2000, 137)


def trial_rows(root, stage, value):
    rows = []
    manifest = read(root / "campaign.json")
    role = STAGE_ROLE[stage]
    for path in (root / stage / key(value)).glob("worker*/trials/trial_*.json"):
        item = read(path)
        design = item.get("design", {})
        expected = {
            "dt_s": WORKING_DT_S,
            "stochastic_solver": "RK4StHybridCustom",
            "ensemble_dir": manifest["ensemble_source"]["directory"],
            "zeeman_seeds": manifest["seed_roles"][role],
            "mot_seeds": manifest["mot_seeds"][role],
            "git_commit": manifest["provenance"]["git_commit"],
        }
        for field, expected_value in expected.items():
            if design.get(field) != expected_value:
                raise RuntimeError(f"Incompatible {stage} trial {path}: {field}")
        rows.append({"s0": value, **item["parameters"],
                     "mean_conditional_efficiency": item["statistics"]["mean_conditional_efficiency"],
                     "source": str(path)})
    return sorted(rows, key=lambda row: (-row["mean_conditional_efficiency"],
                                         row["detuning_gamma"], row["magnet_radius"]))


def distinct(rows, count=3):
    chosen, cells = [], set()
    for row in rows:
        cell = (round(row["detuning_gamma"] / D_RES), round(row["magnet_radius"] / R_RES))
        if cell in cells:
            continue
        cells.add(cell)
        chosen.append(row)
        if len(chosen) == count:
            break
    if len(chosen) < count:
        raise RuntimeError(f"Only {len(chosen)} distinguishable candidates found")
    return chosen


def prepare_refine(root, manifest):
    validated_rows = validate_screen_outputs(root, manifest)
    from workflow_api.mot_2d_plan import render_refine_transition
    files = render_refine_transition(manifest, root, REPOSITORY_ROOT, validated_rows)
    for name, content in files.items():
        path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(content)
    print(f"Next jobs: bash {root/'jobs/03_submit_refinement_chain.sh'}")


def refine_task(args):
    root = Path(args.campaign)
    spec = read(root / "refine" / "tasks.json")[args.task_index]
    if args.target_trials not in REFINEMENT_CUMULATIVE_TARGETS:
        raise ValueError(
            f"Invalid refinement cumulative target: {args.target_trials}"
        )
    optuna_task(
        root, "refine", spec, args.target_trials, 10000, 701, spec["bounds"]
    )


def prepare_confirmation(root, manifest):
    from workflow_api.mot_2d_screen import validate_refine_outputs
    from workflow_api.mot_2d_plan import render_confirmation_transition
    files=render_confirmation_transition(manifest,root,REPOSITORY_ROOT,validate_refine_outputs(root,manifest))
    for name,content in files.items():
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(content)
    print(f"Next job: qsub {root/'jobs/04_confirmation.pbs'}")


def evaluate_task(root, stage, task_index):
    manifest = read(root / "campaign.json")
    assert_design(manifest)
    spec = read(root / stage / "tasks.json")[task_index]
    point = spec.get("candidate_index", spec.get("point_index", 0))
    output = root / stage / key(spec["s0"]) / f"point_{point:02d}.json"
    if output.exists():
        print(f"Already complete: {output}")
        return
    ensembles = stage_ensembles(manifest, stage, 10000)
    role = STAGE_ROLE[stage]
    evaluation = evaluate_configuration(
        **spec["parameters"], ensembles=ensembles, mot_seed_start=manifest["mot_seeds"][role][0],
        mot_seeds=manifest["mot_seeds"][role],
        npools=200, dt_s=FINAL_DT_S,
        stochastic_sim_function=RK4StHybridCustom)
    save_file_json(output, {"kind": f"mot_2d_campaign_{stage}", **spec,
                            "design": {"n_ensembles": len(ensembles), "particles_per_ensemble": 10000,
                                       "zeeman_seeds": manifest["seed_roles"][role],
                                       "mot_seeds": manifest["mot_seeds"][role], "npools": 200,
                                       "dt_s": FINAL_DT_S,
                                       "solver": "RK4StHybridCustom",
                                       "ensemble_source": manifest["ensemble_source"],
                                       "git_commit": manifest["provenance"]["git_commit"],
                                       "physical_model_sha256": manifest["provenance"]["physical_model_sha256"]},
                            "evaluation": evaluation})


def confirmation_task(args):
    evaluate_task(Path(args.campaign), "confirmation", args.task_index)


def paired(candidate, reference, confidence=0.95):
    differences = []
    for left, right in zip(candidate["evaluation"]["replicates"],
                           reference["evaluation"]["replicates"]):
        if any(left[k] != right[k] for k in ("zeeman_seed", "mot_seed", "n_input", "subset_seed")):
            raise ValueError("Replicates are not paired")
        differences.append(left["conditional_efficiency"] - right["conditional_efficiency"])
    mean, low, high, half = student_mean_interval(differences, confidence=confidence)
    return {"mean_difference_fraction": mean, "95_ci_fraction": [low, high],
            "95_ci_half_width_fraction": half, "differences_fraction": differences}


def boundary(parameters):
    flags = []
    for name, value, bounds, tolerance in (
        ("detuning", parameters["detuning_gamma"], BOUNDS_DETUNING, D_RES/2),
        ("radius", parameters["magnet_radius"], BOUNDS_MAGNET_RADIUS_M, R_RES/2),
    ):
        if abs(value-bounds[0]) <= tolerance: flags.append(f"{name}_lower")
        if abs(value-bounds[1]) <= tolerance: flags.append(f"{name}_upper")
    return flags


def prepare_sensitivity(root, manifest):
    winners, specs = {}, []
    for value in manifest["s0_values"]:
        files = sorted((root / "confirmation" / key(value)).glob("point_*.json"))
        if len(files) != CONFIRMATION_CANDIDATES:
            raise RuntimeError(
                f"Confirmation incomplete for s0={value}: "
                f"{len(files)}/{CONFIRMATION_CANDIDATES}"
            )
        rows = [read(path) for path in files]
        rows.sort(key=lambda row: (-row["evaluation"]["statistics"]["conditional_95_ci"][0],
                                   -row["evaluation"]["statistics"]["mean_conditional_efficiency"],
                                   row["candidate_index"]))
        winner = rows[0]
        winner["boundary_flags"] = boundary(winner["parameters"])
        winner["comparisons_to_other_candidates"] = [paired(row, winner) for row in rows[1:]]
        winners[key(value)] = winner
        unique = {}
        neighborhoods = {
            "provisional_control_resolution": (-D_RES, D_RES, -R_RES, R_RES),
            "broader_stress_test": (-0.02, 0.02, -0.1e-3, 0.1e-3),
        }
        for neighborhood, (d_low, d_high, r_low, r_high) in neighborhoods.items():
          for d_offset in (d_low, 0.0, d_high):
            for r_offset in (r_low, 0.0, r_high):
                reference = winner["parameters"]
                parameters = {"s0": value,
                    "detuning_gamma": min(max(reference["detuning_gamma"]+d_offset, BOUNDS_DETUNING[0]), BOUNDS_DETUNING[1]),
                    "magnet_radius": min(max(reference["magnet_radius"]+r_offset, BOUNDS_MAGNET_RADIUS_M[0]), BOUNDS_MAGNET_RADIUS_M[1])}
                identity = (parameters["detuning_gamma"], parameters["magnet_radius"])
                requested = {"neighborhood": neighborhood, "detuning_gamma": d_offset,
                             "magnet_radius_m": r_offset}
                if identity in unique:
                    unique[identity]["requested_offsets"].append(requested)
                else:
                    unique[identity] = {"s0": value, "parameters": parameters,
                                        "offsets": {"detuning_gamma": parameters["detuning_gamma"]-reference["detuning_gamma"],
                                                    "magnet_radius_m": parameters["magnet_radius"]-reference["magnet_radius"]},
                                        "requested_offsets": [requested]}
        for point, spec in enumerate(unique.values()):
            specs.append({"point_index": point, **spec})
    save_file_json(root / "winners.json", winners)
    prepare(root, manifest, "sensitivity", specs, "05", 200, "10:00:00")


def sensitivity_task(args):
    evaluate_task(Path(args.campaign), "sensitivity", args.task_index)


def select_production_point(rows, reference):
    """Choose a clearly superior sensitivity neighbor, otherwise the center."""
    point_summaries = []
    clearly_better = []
    familywise_confidence = 1.0 - 0.05 / max(1, len(rows) - 1)
    for row in rows:
        comparison = paired(row, reference, confidence=familywise_confidence)
        summary = {
            "parameters": row["parameters"],
            "offsets": row["offsets"],
            "mean_efficiency": row["evaluation"]["statistics"][
                "mean_conditional_efficiency"
            ],
            "comparison_to_reference": comparison,
            "within_loss_margin_at_95_percent": bool(
                comparison["95_ci_fraction"][0] >= -TARGET
            ),
        }
        point_summaries.append(summary)
        if comparison["95_ci_fraction"][0] > 0.0:
            clearly_better.append(summary)

    if clearly_better:
        selected = max(
            clearly_better,
            key=lambda item: (
                item["comparison_to_reference"]["95_ci_fraction"][0],
                item["mean_efficiency"],
            ),
        )
        reason = "sensitivity_neighbor_clearly_better_at_95_percent"
    else:
        selected = next(
            item
            for item in point_summaries
            if item["offsets"]
            == {"detuning_gamma": 0.0, "magnet_radius_m": 0.0}
        )
        reason = "no_sensitivity_neighbor_clearly_better_at_95_percent"

    return point_summaries, {
        "parameters": selected["parameters"],
        "offsets_from_confirmed_winner": selected["offsets"],
        "mean_efficiency": selected["mean_efficiency"],
        "comparison_to_confirmed_winner": selected["comparison_to_reference"],
        "selection_reason": reason,
        "familywise_method": "Bonferroni simultaneous paired intervals",
        "familywise_confidence_per_comparison": familywise_confidence,
    }


def prepare_production(root, manifest):
    winners, sensitivity = read(root / "winners.json"), {}
    for value in manifest["s0_values"]:
        rows = [read(p) for p in sorted((root / "sensitivity" / key(value)).glob("point_*.json"))]
        expected_count = sum(1 for task in read(root / "sensitivity" / "tasks.json")
                             if task["s0"] == value)
        if len(rows) != expected_count:
            raise RuntimeError(f"Sensitivity incomplete for s0={value}: {len(rows)}/{expected_count}")
        reference = next(row for row in rows if row["offsets"] == {"detuning_gamma": 0.0, "magnet_radius_m": 0.0})
        points, production_selection = select_production_point(rows, reference)
        sensitivity[key(value)] = {
            "reference": winners[key(value)]["parameters"],
            "points": points,
            "production_selection": production_selection,
            "robustness_status": "not_established_pending_adaptive_challenger_validation",
            "near_optimality_status": "not_established_pending_domain_challenger_elimination",
        }
    save_file_json(root / "sensitivity_summary.json", sensitivity)
    specs = [{"s0": value, "zeeman_seed": seed,
              "mot_seed": manifest["mot_seeds"]["sealed_validation"][
                  manifest["seed_roles"]["sealed_validation"].index(seed)
              ],
              "parameters": sensitivity[key(value)]["production_selection"][
                  "parameters"
              ]}
             for value in manifest["s0_values"]
             for seed in manifest["seed_roles"]["sealed_validation"]]
    prepare(root, manifest, "production", specs, "06", 150, "12:00:00")


def production_task(args):
    root = Path(args.campaign)
    manifest = read(root / "campaign.json")
    assert_design(manifest)
    stage_ensembles(manifest, "production", None)
    spec = read(root / "production" / "tasks.json")[args.task_index]
    output = root / "production" / key(spec["s0"])
    states = Path("data/particle_states/after_2d_mot") / f"final_ensemble_s0_{label(spec['s0'])}"
    result = output / "replicates" / f"zeeman_seed{spec['zeeman_seed']}.json"
    state = states / f"mot_2d_survivors_zeeman_seed{spec['zeeman_seed']}_mot_seed{spec['mot_seed']}.npy"
    if result.exists() and state.exists():
        print(f"Already complete: {result}")
        return
    p = spec["parameters"]
    subprocess.run([sys.executable, "-m", "studies.mot_2d.production",
                    "--zeeman-seeds", str(spec["zeeman_seed"]), "--s0", str(spec["s0"]),
                    "--mot-seeds", str(spec["mot_seed"]),
                    "--detuning-gamma", str(p["detuning_gamma"]),
                    "--magnet-radius-mm", str(1000*p["magnet_radius"]), "--npools", "150",
                    "--ensemble-dir", str(repository_path(manifest["ensemble_source"]["directory"])),
                    "--ensemble-identity", manifest["ensemble_source"]["directory"],
                    "--expected-zeeman-profile", manifest["ensemble_source"]["zeeman_profile"],
                    "--expected-git-commit", manifest["provenance"]["git_commit"],
                    "--output-dir", str(output), "--save-survivor-states", "--states-dir", str(states)],
                   check=True)


def finish(root, manifest):
    assert_design(manifest)
    sensitivity = read(root / "sensitivity_summary.json")
    results = []
    for value in manifest["s0_values"]:
        output = root / "production" / key(value)
        expected = manifest["seed_roles"]["sealed_validation"]
        states = Path("data/particle_states/after_2d_mot") / f"final_ensemble_s0_{label(value)}"
        expected_pairs = dict(zip(
            expected,
            manifest["mot_seeds"]["sealed_validation"],
        ))
        summary = summarize(output, expected_seeds=expected,
                            expected_seed_pairs=expected_pairs, states_dir=states,
                            expected_design={"dt_s": FINAL_DT_S,
                                             "stochastic_solver": "RK4StHybridCustom",
                                             "ensemble_dir": manifest["ensemble_source"]["directory"],
                                             "zeeman_profile": manifest["ensemble_source"]["zeeman_profile"],
                                             "git_commit": manifest["provenance"]["git_commit"]})
        recommended = sensitivity[key(value)]["production_selection"]["parameters"]
        warnings = boundary(recommended)
        if not summary["stopping_rule_passes"]:
            warnings.append("target_95_prediction_half_width_not_met")
        if sensitivity[key(value)]["robustness_status"] != "established":
            warnings.append("robust_operating_region_not_established")
        if sensitivity[key(value)]["near_optimality_status"] != "established":
            warnings.append("epsilon_near_optimality_not_established")
        results.append({"s0": value, "recommended_parameters": recommended,
                        "warnings": warnings, "sensitivity": sensitivity[key(value)],
                        "prediction": summary["prediction_for_10m_zeeman_survivors"],
                        "target_uncertainty_passes": summary["stopping_rule_passes"],
                        "survivor_states_directory": str(Path("data/particle_states/after_2d_mot") / f"final_ensemble_s0_{label(value)}")})
    report = root / "final_report.json"
    save_file_json(report, {"kind": "mot_2d_s0_campaign_final_report",
                            "always_returns_best_tested_result": True, "results": results})
    manifest["stage"] = "complete"
    manifest["stages"]["final_report"] = str(report)
    save_file_json(root / "campaign.json", manifest)
    print(f"CAMPAIGN COMPLETE: {report}")


def advance(args):
    root = Path(args.campaign)
    manifest = read(root / "campaign.json")
    assert_design(manifest)
    transitions = {"smoke": prepare_screen, "screen": prepare_refine,
                   "refine": prepare_confirmation, "confirmation": prepare_sensitivity,
                   "sensitivity": prepare_production, "production": finish}
    if manifest["stage"] == "complete":
        print(f"Campaign already complete: {root/'final_report.json'}")
    else:
        transitions[manifest["stage"]](root, manifest)


def status(args):
    root = Path(args.campaign)
    manifest = read(root / "campaign.json")
    print(f"Campaign: {manifest['name']}\nCurrent stage: {manifest['stage']}\ns0 values: {manifest['s0_values']}")
    stage = manifest["stage"]
    for value in manifest["s0_values"]:
        if stage in {"screen", "refine"}:
            print(f"s0={value}: {len(trial_rows(root, stage, value))} completed trials")
        elif stage in {"confirmation", "sensitivity"}:
            print(f"s0={value}: {len(list((root/stage/key(value)).glob('point_*.json')))} completed points")
        elif stage == "production":
            done = len(list((root/stage/key(value)/'replicates').glob('zeeman_seed*.json')))
            expected = len(manifest["seed_roles"]["sealed_validation"])
            print(f"s0={value}: {done}/{expected} production ensembles")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("create")
    command.add_argument("--name", required=True); command.add_argument("--s0", nargs="+", type=float, required=True)
    command.add_argument("--output-dir", required=True)
    command.add_argument("--ensemble-dir", default=DEFAULT_ENSEMBLE_DIR)
    command.add_argument("--zeeman-profile", default=DEFAULT_PROFILE)
    command.set_defaults(func=create)
    command = sub.add_parser("smoke")
    command.add_argument("--campaign", required=True); command.add_argument("--s0-index", type=int, required=True)
    command.set_defaults(func=smoke)
    for name, function in (("screen-task", screen_task), ("refine-task", refine_task),
                           ("confirmation-task", confirmation_task), ("sensitivity-task", sensitivity_task),
                           ("production-task", production_task)):
        command = sub.add_parser(name); command.add_argument("--campaign", required=True)
        command.add_argument("--task-index", type=int, required=True)
        if name == "refine-task":
            command.add_argument("--target-trials", type=int, required=True)
        command.set_defaults(func=function)
    for name, function in (("advance", advance), ("status", status)):
        command = sub.add_parser(name); command.add_argument("--campaign", required=True); command.set_defaults(func=function)
    return parser.parse_args(argv)


if __name__ == "__main__":
    arguments = parse_args()
    arguments.func(arguments)
