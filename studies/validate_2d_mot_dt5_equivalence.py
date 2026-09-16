"""Test whether 5 us is equivalent to the locked 0.625 us 2D-MOT result.

Only the candidate 5 us simulations are run.  The reference side is read from
the retained final-production result, so the expensive 0.625 us production is
never repeated.  The same Zeeman ensembles and MOT seed assigned to every
reference replicate are reused for the candidate run.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
from scipy.stats import t as student_t

from studies.optimize_2d_mot_joint import evaluate_configuration
from utils.RK4StHybridCustom import RK4StHybridCustom
from utils.file_helpers import save_file_json
from utils.mot_2d_study import load_production_ensembles


REFERENCE_SUMMARY = Path(
    "data/optimization/mot_2d/final_production_v22/summary.json"
)
DEFAULT_OUTPUT_DIR = Path(
    "data/validation/mot_2d/dt5_equivalence_to_final_production"
)
CANDIDATE_DT_S = 5e-6
EQUIVALENCE_MARGIN_FRACTION = 0.0005  # 0.05 percentage points
N_TASKS = 4
NPOOLS = 150


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def reference_payload(path):
    payload = read_json(path)
    required = {"parameters", "design", "replicates", "zeeman_seeds"}
    missing = required - payload.keys()
    if missing:
        raise ValueError(f"Reference summary is missing fields: {sorted(missing)}")
    if len(payload["replicates"]) != 20:
        raise ValueError("Expected exactly 20 final-production reference replicates.")
    return payload


def task_seed_groups(reference):
    seeds = sorted(int(seed) for seed in reference["zeeman_seeds"])
    groups = [list(map(int, group)) for group in np.array_split(seeds, N_TASKS)]
    if any(not group for group in groups):
        raise ValueError("The reference does not contain enough seeds for four tasks.")
    return groups


def prepare(args):
    reference = reference_payload(args.reference_summary)
    output_dir = Path(args.output_dir)
    jobs_dir = output_dir / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    task_groups = task_seed_groups(reference)
    save_file_json(
        output_dir / "design.json",
        {
            "kind": "mot_2d_dt5_equivalence_design",
            "reference_summary": str(args.reference_summary),
            "candidate_dt_s": CANDIDATE_DT_S,
            "equivalence_margin_fraction": EQUIVALENCE_MARGIN_FRACTION,
            "equivalence_margin_percentage_points": (
                100 * EQUIVALENCE_MARGIN_FRACTION
            ),
            "n_tasks": N_TASKS,
            "npools_per_task": NPOOLS,
            "task_zeeman_seeds": task_groups,
            "parameters": reference["parameters"],
        },
    )
    pbs_path = jobs_dir / "01_run_dt5.pbs"
    pbs_path.write_text(
        f"""#!/bin/bash
#PBS -N mot2d_dt5eq
#PBS -q zeus_combined_q
#PBS -J 0-{N_TASKS - 1}
#PBS -l select=1:ncpus={NPOOLS}:mem=64gb
#PBS -l walltime=04:00:00

set -euo pipefail
cd /home/tal.noa/ytterbium_lab_simulation_new || exit 1
module load SPACK/apps
module load gcc/14.1.0
module load python/3.14.2
source ~/venvs/atomsmltr/bin/activate

RUN_TMP="/tmp/${{USER}}_mot2d_dt5eq_${{PBS_JOBID}}_${{PBS_ARRAY_INDEX}}"
mkdir -p "${{RUN_TMP}}"
export TMPDIR="${{RUN_TMP}}" TMP="${{RUN_TMP}}" TEMP="${{RUN_TMP}}"
trap 'rm -rf -- "${{RUN_TMP}}"' EXIT

exec > "mot2d_dt5eq_${{PBS_ARRAY_INDEX}}_${{PBS_JOBID}}.out" \\
     2> "mot2d_dt5eq_${{PBS_ARRAY_INDEX}}_${{PBS_JOBID}}.err"

python -u -m studies.validate_2d_mot_dt5_equivalence run-task \\
    --task-index "${{PBS_ARRAY_INDEX}}" \\
    --reference-summary {args.reference_summary} \\
    --output-dir {output_dir} \\
    --npools {NPOOLS}
""",
        encoding="utf-8",
    )
    print(f"Design saved to: {output_dir / 'design.json'}")
    print(f"PBS file saved to: {pbs_path}")
    print(f"Submit with: qsub {pbs_path}")


def smoke(args):
    """Exercise the real 5 us simulation and output path with two atoms."""
    reference = reference_payload(args.reference_summary)
    first_row = min(reference["replicates"], key=lambda row: row["zeeman_seed"])
    zeeman_seed = int(first_row["zeeman_seed"])
    mot_seed = int(first_row["mot_seed"])
    ensembles = load_production_ensembles(
        max_ensembles=1,
        particles_per_ensemble=2,
        zeeman_seeds=[zeeman_seed],
    )
    parameters = {key: float(value) for key, value in reference["parameters"].items()}
    evaluation = evaluate_configuration(
        **parameters,
        ensembles=ensembles,
        mot_seed_start=mot_seed,
        mot_seeds=[mot_seed],
        npools=1,
        dt_s=CANDIDATE_DT_S,
        stochastic_sim_function=RK4StHybridCustom,
    )
    payload = {
        "kind": "mot_2d_dt5_equivalence_smoke",
        "parameters": parameters,
        "design": {
            "dt_s": CANDIDATE_DT_S,
            "stochastic_solver": RK4StHybridCustom.__name__,
            "n_input": 2,
            "zeeman_seed": zeeman_seed,
            "mot_seed": mot_seed,
        },
        "evaluation": evaluation,
    }
    output_path = Path(args.output_dir) / "smoke.json"
    save_file_json(output_path, payload)
    print(f"SMOKE PASS: real 5 us simulation completed; output={output_path}")


def run_task(args):
    reference = reference_payload(args.reference_summary)
    groups = task_seed_groups(reference)
    if args.task_index < 0 or args.task_index >= len(groups):
        raise ValueError(f"task-index must be between 0 and {len(groups) - 1}.")

    reference_rows = {
        int(row["zeeman_seed"]): row for row in reference["replicates"]
    }
    output_dir = Path(args.output_dir) / "replicates"
    output_dir.mkdir(parents=True, exist_ok=True)
    assigned_seeds = groups[args.task_index]
    missing_seeds = [
        seed
        for seed in assigned_seeds
        if not (output_dir / f"zeeman_seed{seed}.json").exists()
    ]
    if not missing_seeds:
        print(f"Task {args.task_index}: all assigned seeds already completed.")
        return

    ensembles = load_production_ensembles(
        particles_per_ensemble=None,
        zeeman_seeds=missing_seeds,
    )
    ensemble_by_seed = {int(row["zeeman_seed"]): row for row in ensembles}
    ordered_ensembles = [ensemble_by_seed[seed] for seed in missing_seeds]
    mot_seeds = [int(reference_rows[seed]["mot_seed"]) for seed in missing_seeds]
    parameters = {key: float(value) for key, value in reference["parameters"].items()}
    evaluation = evaluate_configuration(
        **parameters,
        ensembles=ordered_ensembles,
        mot_seed_start=mot_seeds[0],
        mot_seeds=mot_seeds,
        npools=args.npools,
        dt_s=CANDIDATE_DT_S,
        stochastic_sim_function=RK4StHybridCustom,
    )
    for row in evaluation["replicates"]:
        seed = int(row["zeeman_seed"])
        reference_row = reference_rows[seed]
        if int(row["mot_seed"]) != int(reference_row["mot_seed"]):
            raise RuntimeError("Candidate and reference MOT seeds do not match.")
        payload = {
            "kind": "mot_2d_dt5_equivalence_replicate",
            "parameters": parameters,
            "design": {
                "dt_s": CANDIDATE_DT_S,
                "stochastic_solver": RK4StHybridCustom.__name__,
                "uses_all_available_particles": True,
                "npools": int(args.npools),
                "reference_summary": str(args.reference_summary),
                "reference_dt_s": float(reference["design"]["dt_s"]),
            },
            "replicate": row,
            "reference_replicate": reference_row,
        }
        save_file_json(output_dir / f"zeeman_seed{seed}.json", payload)
        print(
            "MOT_2D_DT5_EQUIVALENCE_RESULT "
            f"zeeman_seed={seed} mot_seed={row['mot_seed']} "
            f"captured={row['captured']} n_input={row['n_input']} "
            f"candidate_percent={100 * row['conditional_efficiency']:.6f} "
            f"reference_percent={100 * reference_row['conditional_efficiency']:.6f}",
            flush=True,
        )


def paired_summary(candidate_rows, reference_rows, margin_fraction):
    differences = np.asarray(
        [
            candidate_rows[seed]["conditional_efficiency"]
            - reference_rows[seed]["conditional_efficiency"]
            for seed in sorted(reference_rows)
        ],
        dtype=float,
    )
    mean_difference = float(np.mean(differences))
    standard_deviation = float(np.std(differences, ddof=1))
    standard_error = standard_deviation / math.sqrt(len(differences))
    critical = float(student_t.ppf(0.975, len(differences) - 1))
    half_width = float(critical * standard_error)
    low = mean_difference - half_width
    high = mean_difference + half_width
    return {
        "paired_differences_fraction": differences.tolist(),
        "mean_paired_difference_fraction": mean_difference,
        "paired_difference_standard_deviation_fraction": standard_deviation,
        "paired_difference_standard_error_fraction": standard_error,
        "critical_value": critical,
        "paired_95_ci_fraction": [low, high],
        "paired_95_ci_half_width_fraction": half_width,
        "equivalence_margin_fraction": margin_fraction,
        "equivalence_margin_percentage_points": 100 * margin_fraction,
        "equivalence_passes": bool(
            low >= -margin_fraction and high <= margin_fraction
        ),
    }


def summarize(args):
    reference = reference_payload(args.reference_summary)
    reference_rows = {
        int(row["zeeman_seed"]): row for row in reference["replicates"]
    }
    candidate_paths = sorted(
        (Path(args.output_dir) / "replicates").glob("zeeman_seed*.json")
    )
    candidate_payloads = [read_json(path) for path in candidate_paths]
    candidate_rows = {
        int(payload["replicate"]["zeeman_seed"]): payload["replicate"]
        for payload in candidate_payloads
    }
    missing = sorted(set(reference_rows) - set(candidate_rows))
    extra = sorted(set(candidate_rows) - set(reference_rows))
    if missing or extra:
        raise RuntimeError(
            f"Candidate result set is incomplete: missing={missing}, extra={extra}"
        )
    for payload in candidate_payloads:
        if payload["parameters"] != reference["parameters"]:
            raise ValueError("Candidate files contain parameters unlike the reference.")
        if not math.isclose(payload["design"]["dt_s"], CANDIDATE_DT_S):
            raise ValueError("Candidate files contain an unexpected timestep.")

    paired = paired_summary(
        candidate_rows,
        reference_rows,
        args.margin_percentage_points / 100.0,
    )
    candidate_input = sum(int(row["n_input"]) for row in candidate_rows.values())
    candidate_captured = sum(
        int(row["captured"]) for row in candidate_rows.values()
    )
    reference_input = sum(int(row["n_input"]) for row in reference_rows.values())
    reference_captured = sum(
        int(row["captured"]) for row in reference_rows.values()
    )
    summary = {
        "kind": "mot_2d_dt5_equivalence_summary",
        "parameters": reference["parameters"],
        "candidate_dt_s": CANDIDATE_DT_S,
        "reference_dt_s": float(reference["design"]["dt_s"]),
        "n_paired_ensembles": len(reference_rows),
        "candidate_total_input": candidate_input,
        "candidate_total_captured": candidate_captured,
        "candidate_pooled_efficiency": candidate_captured / candidate_input,
        "reference_total_input": reference_input,
        "reference_total_captured": reference_captured,
        "reference_pooled_efficiency": reference_captured / reference_input,
        "paired_comparison": paired,
        "decision": (
            "PASS_USE_5_US"
            if paired["equivalence_passes"]
            else "FAIL_KEEP_0P625_US"
        ),
        "decision_rule": (
            "Use 5 us only if the complete paired 95% confidence interval for "
            "candidate minus reference capture lies inside the predeclared "
            f"+/-{args.margin_percentage_points:g} percentage-point margin."
        ),
    }
    output_path = Path(args.output_dir) / "summary.json"
    save_file_json(output_path, summary)

    low, high = paired["paired_95_ci_fraction"]
    print("\n2D-MOT TIMESTEP EQUIVALENCE")
    print("=" * 76)
    print(
        f"candidate dt:  {CANDIDATE_DT_S * 1e6:g} us | "
        f"capture={100 * summary['candidate_pooled_efficiency']:.6f}%"
    )
    print(
        f"reference dt:  {summary['reference_dt_s'] * 1e6:g} us | "
        f"capture={100 * summary['reference_pooled_efficiency']:.6f}%"
    )
    print(
        "paired difference (candidate - reference): "
        f"{100 * paired['mean_paired_difference_fraction']:+.6f} pp"
    )
    print(f"paired 95% CI: [{100 * low:+.6f}, {100 * high:+.6f}] pp")
    print(
        f"required interval: [-{args.margin_percentage_points:g}, "
        f"+{args.margin_percentage_points:g}] pp"
    )
    print(f"DECISION: {summary['decision']}")
    print(f"Summary saved to: {output_path}")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    command = subparsers.add_parser("prepare")
    command.add_argument("--reference-summary", default=str(REFERENCE_SUMMARY))
    command.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    command.set_defaults(func=prepare)

    command = subparsers.add_parser("smoke")
    command.add_argument("--reference-summary", default=str(REFERENCE_SUMMARY))
    command.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    command.set_defaults(func=smoke)

    command = subparsers.add_parser("run-task")
    command.add_argument("--task-index", type=int, required=True)
    command.add_argument("--reference-summary", default=str(REFERENCE_SUMMARY))
    command.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    command.add_argument("--npools", type=int, default=NPOOLS)
    command.set_defaults(func=run_task)

    command = subparsers.add_parser("summarize")
    command.add_argument("--reference-summary", default=str(REFERENCE_SUMMARY))
    command.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    command.add_argument(
        "--margin-percentage-points",
        type=float,
        default=100 * EQUIVALENCE_MARGIN_FRACTION,
    )
    command.set_defaults(func=summarize)
    return parser.parse_args(argv)


if __name__ == "__main__":
    arguments = parse_args()
    arguments.func(arguments)
