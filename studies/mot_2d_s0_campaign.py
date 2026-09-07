"""Resumable, decision-free 2D-MOT optimization for a list of fixed s0 values."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

from studies.optimize_2d_mot_joint import BOUNDS_DETUNING, BOUNDS_MAGNET_RADIUS_M
from studies.optimize_2d_mot_joint import evaluate_configuration
from studies.run_2d_mot_final_production import summarize
from utils.RK4StHybridCustom import RK4StHybridCustom
from utils.file_helpers import save_file_json
from utils.mot_2d_study import load_production_ensembles, student_mean_interval

DT = 0.625e-6
TARGET = 0.0005
D_RES = 0.01
R_RES = 0.01e-3
SCREEN_TRIALS = 17
REFINE_TRIALS = 10
PRODUCTION_SEEDS = tuple(range(3000, 3020))


def key(value):
    return f"s0_{float(value):.6f}".replace(".", "p")


def label(value):
    return f"{float(value):.6f}".rstrip("0").rstrip(".")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def paths(root):
    root = Path(root)
    return root, root / "campaign.json", root / "jobs"


def write_pbs(path, name, array, ncpus, walltime, command):
    array_line = f"#PBS -J {array}\n" if array else ""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"""#!/bin/bash
#PBS -N {name}
#PBS -q zeus_combined_q
{array_line}#PBS -l select=1:ncpus={ncpus}:mem=64gb
#PBS -l walltime={walltime}

set -euo pipefail
cd /home/tal.noa/ytterbium_lab_simulation_new || exit 1
module load SPACK/apps
module load gcc/14.1.0
module load python/3.14.2
source ~/venvs/atomsmltr/bin/activate
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
    if manifest_path.exists() and not args.force:
        raise FileExistsError(f"Campaign already exists: {manifest_path}")
    manifest = {
        "kind": "mot_2d_s0_campaign", "name": args.name, "stage": "smoke",
        "s0_values": values, "stages": {},
        "fixed_design": {
            "dt_s": DT, "solver": "RK4StHybridCustom",
            "detuning_bounds_gamma": list(BOUNDS_DETUNING),
            "magnet_radius_bounds_m": list(BOUNDS_MAGNET_RADIUS_M),
            "detuning_resolution_gamma": D_RES,
            "magnet_radius_resolution_m": R_RES,
            "target_95_half_width_fraction": TARGET,
            "reporting_zeeman_survivors": 10_000_000,
        },
    }
    save_file_json(manifest_path, manifest)
    write_pbs(jobs / "01_smoke.pbs", "mot2d_smoke", f"0-{len(values)-1}", 1,
              "00:20:00", "python -m studies.mot_2d_s0_campaign smoke "
              f"--campaign {root} --s0-index $PBS_ARRAY_INDEX")
    print(f"Campaign created: {manifest_path}")
    print(f"First job: qsub {jobs / '01_smoke.pbs'}")


def smoke(args):
    root = Path(args.campaign)
    manifest = read(root / "campaign.json")
    value = manifest["s0_values"][args.s0_index]
    output = root / "smoke" / key(value)
    subprocess.run([
        sys.executable, "-m", "studies.optimize_2d_mot_joint", "--fixed-s0", str(value),
        "--n-trials", "1", "--n-ensembles", "1", "--particles-per-ensemble", "2",
        "--npools", "1", "--dt", str(DT), "--stochastic-solver", "hybrid",
        "--study-name", f"{manifest['name']}_{key(value)}_smoke", "--output-dir", str(output),
    ], check=True)
    assert read(output / "summary.json")["n_finished_trials"] == 1
    print(f"SMOKE PASS s0={value}")


def prepare(root, manifest, stage, specs, number, ncpus, walltime):
    save_file_json(root / stage / "tasks.json", specs)
    job = root / "jobs" / f"{number}_{stage}.pbs"
    write_pbs(job, f"mot2d_{stage[:5]}", f"0-{len(specs)-1}", ncpus, walltime,
              f"python -m studies.mot_2d_s0_campaign {stage}-task "
              f"--campaign {root} --task-index $PBS_ARRAY_INDEX")
    manifest["stage"] = stage
    manifest["stages"][stage] = {"tasks": len(specs), "job_file": str(job)}
    save_file_json(root / "campaign.json", manifest)
    print(f"Next job: qsub {job}")


def prepare_screen(root, manifest):
    missing = [v for v in manifest["s0_values"]
               if not (root / "smoke" / key(v) / "summary.json").exists()]
    if missing:
        raise RuntimeError(f"Smoke tests incomplete: {missing}")
    specs = [{"s0": value, "worker": worker}
             for value in manifest["s0_values"] for worker in range(3)]
    prepare(root, manifest, "screen", specs, "02", 200, "10:00:00")


def optuna_task(root, stage, spec, trials, particles, sampler_seed, bounds=None):
    output = root / stage / key(spec["s0"]) / f"worker{spec['worker']}"
    command = [
        sys.executable, "-m", "studies.optimize_2d_mot_joint", "--fixed-s0", str(spec["s0"]),
        "--n-trials", str(trials), "--n-ensembles", "3",
        "--particles-per-ensemble", str(particles), "--npools", "200",
        "--dt", str(DT), "--stochastic-solver", "hybrid",
        "--sampler-seed", str(sampler_seed + spec["worker"]),
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
    for path in (root / stage / key(value)).glob("worker*/trials/trial_*.json"):
        item = read(path)
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
    specs, selected = [], {}
    for value in manifest["s0_values"]:
        rows = trial_rows(root, "screen", value)
        if len(rows) != 3 * SCREEN_TRIALS:
            raise RuntimeError(f"Screening incomplete for s0={value}: {len(rows)}/{3*SCREEN_TRIALS}")
        selected[key(value)] = distinct(rows)
        for worker, candidate in enumerate(selected[key(value)]):
            specs.append({"s0": value, "worker": worker, "center": candidate,
                          "bounds": {
                              "detuning": [max(BOUNDS_DETUNING[0], candidate["detuning_gamma"]-0.08),
                                           min(BOUNDS_DETUNING[1], candidate["detuning_gamma"]+0.08)],
                              "radius": [max(BOUNDS_MAGNET_RADIUS_M[0], candidate["magnet_radius"]-0.5e-3),
                                         min(BOUNDS_MAGNET_RADIUS_M[1], candidate["magnet_radius"]+0.5e-3)],
                          }})
    save_file_json(root / "screening_candidates.json", selected)
    prepare(root, manifest, "refine", specs, "03", 200, "14:00:00")


def refine_task(args):
    root = Path(args.campaign)
    spec = read(root / "refine" / "tasks.json")[args.task_index]
    optuna_task(root, "refine", spec, REFINE_TRIALS, 5000, 701, spec["bounds"])


def prepare_confirmation(root, manifest):
    specs, candidates = [], {}
    for value in manifest["s0_values"]:
        rows = trial_rows(root, "refine", value)
        if len(rows) != 3 * REFINE_TRIALS:
            raise RuntimeError(f"Refinement incomplete for s0={value}: {len(rows)}/{3*REFINE_TRIALS}")
        candidates[key(value)] = distinct(rows)
        for index, candidate in enumerate(candidates[key(value)]):
            specs.append({"s0": value, "candidate_index": index,
                          "parameters": {k: candidate[k] for k in ("s0", "detuning_gamma", "magnet_radius")}})
    save_file_json(root / "refined_candidates.json", candidates)
    prepare(root, manifest, "confirmation", specs, "04", 200, "10:00:00")


def evaluate_task(root, stage, task_index):
    spec = read(root / stage / "tasks.json")[task_index]
    point = spec.get("candidate_index", spec.get("point_index", 0))
    output = root / stage / key(spec["s0"]) / f"point_{point:02d}.json"
    if output.exists():
        print(f"Already complete: {output}")
        return
    ensembles = load_production_ensembles(max_ensembles=10, particles_per_ensemble=10000)
    evaluation = evaluate_configuration(
        **spec["parameters"], ensembles=ensembles, mot_seed_start=25000,
        npools=200, dt_s=DT, stochastic_sim_function=RK4StHybridCustom)
    save_file_json(output, {"kind": f"mot_2d_campaign_{stage}", **spec,
                            "design": {"n_ensembles": 10, "particles_per_ensemble": 10000,
                                       "mot_seed_start": 25000, "npools": 200,
                                       "dt_s": DT, "solver": "RK4StHybridCustom"},
                            "evaluation": evaluation})


def confirmation_task(args):
    evaluate_task(Path(args.campaign), "confirmation", args.task_index)


def paired(candidate, reference):
    differences = []
    for left, right in zip(candidate["evaluation"]["replicates"],
                           reference["evaluation"]["replicates"]):
        if any(left[k] != right[k] for k in ("zeeman_seed", "mot_seed", "n_input", "subset_seed")):
            raise ValueError("Replicates are not paired")
        differences.append(left["conditional_efficiency"] - right["conditional_efficiency"])
    mean, low, high, half = student_mean_interval(differences)
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
        if len(files) != 3:
            raise RuntimeError(f"Confirmation incomplete for s0={value}: {len(files)}/3")
        rows = [read(path) for path in files]
        rows.sort(key=lambda row: (-row["evaluation"]["statistics"]["conditional_95_ci"][0],
                                   -row["evaluation"]["statistics"]["mean_conditional_efficiency"],
                                   row["candidate_index"]))
        winner = rows[0]
        winner["boundary_flags"] = boundary(winner["parameters"])
        winner["comparisons_to_other_candidates"] = [paired(row, winner) for row in rows[1:]]
        winners[key(value)] = winner
        point = 0
        for d_offset in (-0.02, 0.0, 0.02):
            for r_offset in (-0.1e-3, 0.0, 0.1e-3):
                reference = winner["parameters"]
                specs.append({"s0": value, "point_index": point,
                              "offsets": {"detuning_gamma": d_offset, "magnet_radius_m": r_offset},
                              "parameters": {"s0": value,
                                  "detuning_gamma": min(max(reference["detuning_gamma"]+d_offset, BOUNDS_DETUNING[0]), BOUNDS_DETUNING[1]),
                                  "magnet_radius": min(max(reference["magnet_radius"]+r_offset, BOUNDS_MAGNET_RADIUS_M[0]), BOUNDS_MAGNET_RADIUS_M[1])}})
                point += 1
    save_file_json(root / "winners.json", winners)
    prepare(root, manifest, "sensitivity", specs, "05", 200, "10:00:00")


def sensitivity_task(args):
    evaluate_task(Path(args.campaign), "sensitivity", args.task_index)


def prepare_production(root, manifest):
    winners, sensitivity = read(root / "winners.json"), {}
    for value in manifest["s0_values"]:
        rows = [read(p) for p in sorted((root / "sensitivity" / key(value)).glob("point_*.json"))]
        if len(rows) != 9:
            raise RuntimeError(f"Sensitivity incomplete for s0={value}: {len(rows)}/9")
        reference = next(row for row in rows if row["offsets"] == {"detuning_gamma": 0.0, "magnet_radius_m": 0.0})
        sensitivity[key(value)] = {"reference": winners[key(value)]["parameters"], "points": [
            {"parameters": row["parameters"], "offsets": row["offsets"],
             "mean_efficiency": row["evaluation"]["statistics"]["mean_conditional_efficiency"],
             "comparison_to_reference": paired(row, reference),
             "within_loss_margin_at_95_percent": bool(paired(row, reference)["95_ci_fraction"][0] >= -TARGET)}
            for row in rows]}
    save_file_json(root / "sensitivity_summary.json", sensitivity)
    specs = [{"s0": value, "zeeman_seed": seed,
              "parameters": winners[key(value)]["parameters"]}
             for value in manifest["s0_values"] for seed in PRODUCTION_SEEDS]
    prepare(root, manifest, "production", specs, "06", 150, "12:00:00")


def production_task(args):
    root = Path(args.campaign)
    spec = read(root / "production" / "tasks.json")[args.task_index]
    output = root / "production" / key(spec["s0"])
    states = Path("data/particle_states/after_2d_mot") / f"final_ensemble_s0_{label(spec['s0'])}"
    result = output / "replicates" / f"zeeman_seed{spec['zeeman_seed']}.json"
    state = states / f"mot_2d_survivors_zeeman_seed{spec['zeeman_seed']}_mot_seed{spec['zeeman_seed']+15000}.npy"
    if result.exists() and state.exists():
        print(f"Already complete: {result}")
        return
    p = spec["parameters"]
    subprocess.run([sys.executable, "-m", "studies.run_2d_mot_final_production",
                    "--zeeman-seeds", str(spec["zeeman_seed"]), "--s0", str(spec["s0"]),
                    "--detuning-gamma", str(p["detuning_gamma"]),
                    "--magnet-radius-mm", str(1000*p["magnet_radius"]), "--npools", "150",
                    "--output-dir", str(output), "--save-survivor-states", "--states-dir", str(states)],
                   check=True)


def finish(root, manifest):
    winners, sensitivity = read(root / "winners.json"), read(root / "sensitivity_summary.json")
    results = []
    for value in manifest["s0_values"]:
        output = root / "production" / key(value)
        count = len(list((output / "replicates").glob("zeeman_seed*.json")))
        if count != len(PRODUCTION_SEEDS):
            raise RuntimeError(f"Production incomplete for s0={value}: {count}/{len(PRODUCTION_SEEDS)}")
        summary = summarize(output)
        warnings = list(winners[key(value)]["boundary_flags"])
        if not summary["stopping_rule_passes"]:
            warnings.append("target_95_prediction_half_width_not_met")
        results.append({"s0": value, "recommended_parameters": winners[key(value)]["parameters"],
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
            print(f"s0={value}: {done}/{len(PRODUCTION_SEEDS)} production ensembles")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("create")
    command.add_argument("--name", required=True); command.add_argument("--s0", nargs="+", type=float, required=True)
    command.add_argument("--output-dir", required=True); command.add_argument("--force", action="store_true")
    command.set_defaults(func=create)
    command = sub.add_parser("smoke")
    command.add_argument("--campaign", required=True); command.add_argument("--s0-index", type=int, required=True)
    command.set_defaults(func=smoke)
    for name, function in (("screen-task", screen_task), ("refine-task", refine_task),
                           ("confirmation-task", confirmation_task), ("sensitivity-task", sensitivity_task),
                           ("production-task", production_task)):
        command = sub.add_parser(name); command.add_argument("--campaign", required=True)
        command.add_argument("--task-index", type=int, required=True); command.set_defaults(func=function)
    for name, function in (("advance", advance), ("status", status)):
        command = sub.add_parser(name); command.add_argument("--campaign", required=True); command.set_defaults(func=function)
    return parser.parse_args(argv)


if __name__ == "__main__":
    arguments = parse_args()
    arguments.func(arguments)
