"""Submit one end-to-end 12-particle Optuna smoke trial per 3D-MOT family."""

import subprocess
from pathlib import Path


ROOT = Path("data/optimization/mot_3d/full_optuna_v1_smoke")


def main():
    pbs_dir = ROOT / "pbs"
    pbs_dir.mkdir(parents=True, exist_ok=True)
    jobs = []
    for index, family in enumerate(("angled_donut", "single_pass")):
        pbs = pbs_dir / f"{family}.pbs"
        pbs.write_text(f"""#!/bin/bash
#PBS -N mot3d_{'donut' if family == 'angled_donut' else 'sp'}_smoke
#PBS -q zeus_combined_q
#PBS -l select=1:ncpus=12:mem=8gb
#PBS -l walltime=01:00:00

set -euo pipefail
cd ~/ytterbium_lab_simulation_new
mkdir -p data/validation/mot_3d/logs
LOG_STEM="data/validation/mot_3d/logs/${{PBS_JOBNAME}}_${{PBS_JOBID}}"
exec > "${{LOG_STEM}}.out" 2> "${{LOG_STEM}}.err"
source ~/venvs/atomsmltr/bin/activate

python -u -m studies.optimize_3d_mot_full \\
    --family {family} --worker-index 0 \\
    --target-completed-trials 1 --sampler-seed {281001 + index} \\
    --output-dir {ROOT / family} \\
    --ensemble-count 1 --particles-per-ensemble 12 --npools 12 \\
    --timeout-s 3000
""")
        result = subprocess.run(["qsub", str(pbs)], check=True, text=True, capture_output=True)
        job_id = result.stdout.strip()
        jobs.append(job_id)
        print(f"Submitted {pbs.name}: {job_id}")
    print("Full-optimization smoke jobs: " + ", ".join(jobs))


if __name__ == "__main__":
    main()
