"""Submit three restart-safe 24-hour Optuna workers for a 3D-MOT family."""

import argparse
import subprocess
from pathlib import Path

from config import MOT_3D_OPTIMIZATION_CONFIG


ROOT = Path("data/optimization/mot_3d/full_optuna_v1")


def _target_counts(total):
    base, remainder = divmod(total, 3)
    return tuple(base + (index < remainder) for index in range(3))


def submit(family, output_root):
    if family not in ("angled_donut", "single_pass"):
        raise ValueError("family must be angled_donut or single_pass.")
    total = MOT_3D_OPTIMIZATION_CONFIG[family]["total_discovery_trials"]
    targets = _target_counts(total)
    output_root = Path(output_root) / family
    pbs_dir = output_root / "pbs"
    pbs_dir.mkdir(parents=True, exist_ok=True)
    sampler_seeds = (271_001, 271_002, 271_003)
    job_ids = []
    for worker_index, (target, sampler_seed) in enumerate(zip(targets, sampler_seeds)):
        pbs = pbs_dir / f"worker_{worker_index}.pbs"
        pbs.write_text(f"""#!/bin/bash
#PBS -N mot3d_{'donut' if family == 'angled_donut' else 'sp'}_opt{worker_index}
#PBS -q zeus_combined_q
#PBS -l select=1:ncpus=200:mem=64gb
#PBS -l walltime=24:00:00

set -euo pipefail
cd ~/ytterbium_lab_simulation_new
mkdir -p data/validation/mot_3d/logs
LOG_STEM="data/validation/mot_3d/logs/${{PBS_JOBNAME}}_${{PBS_JOBID}}"
exec > "${{LOG_STEM}}.out" 2> "${{LOG_STEM}}.err"
source ~/venvs/atomsmltr/bin/activate

python -u -m studies.optimize_3d_mot_full \\
    --family {family} --worker-index {worker_index} \\
    --target-completed-trials {target} --sampler-seed {sampler_seed} \\
    --output-dir {output_root} --npools 200 --timeout-s 82800
""")
        result = subprocess.run(["qsub", str(pbs)], check=True, text=True, capture_output=True)
        job_id = result.stdout.strip()
        job_ids.append(job_id)
        print(f"Submitted {pbs.name}: {job_id}")
    print(f"Family: {family}")
    print(f"Total target completed trials: {total}; per worker: {targets}")
    print("Jobs: " + ", ".join(job_ids))
    return job_ids


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", choices=("angled_donut", "single_pass"), required=True)
    parser.add_argument("--output-root", default=str(ROOT))
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    submit(args.family, args.output_root)
