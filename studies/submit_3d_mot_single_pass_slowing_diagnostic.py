"""Submit the focused yz single-pass slowing-region diagnostic."""

import subprocess
from pathlib import Path


ROOT = Path("data/validation/mot_3d/single_pass_yz_screen/slowing_diagnostic_120")


def main():
    pbs = ROOT / "pbs" / "single_pass_slowing_diagnostic.pbs"
    pbs.parent.mkdir(parents=True, exist_ok=True)
    pbs.write_text(f"""#!/bin/bash
#PBS -N mot3d_sp_slow
#PBS -q zeus_combined_q
#PBS -l select=1:ncpus=200:mem=64gb
#PBS -l walltime=02:00:00

set -euo pipefail
cd ~/ytterbium_lab_simulation_new
mkdir -p data/validation/mot_3d/logs
LOG_STEM="data/validation/mot_3d/logs/${{PBS_JOBNAME}}_${{PBS_JOBID}}"
exec > "${{LOG_STEM}}.out" 2> "${{LOG_STEM}}.err"
source ~/venvs/atomsmltr/bin/activate

python -u -m studies.diagnose_3d_mot_single_pass_slowing \\
    --max-atoms 120 --npools 120 --t-max 0.1 \\
    --z-offset-m-values -0.050 -0.045 \\
    --blue-s0 0.25 --blue-detuning-gamma -2.75 --blue-waist-m 0.0075 \\
    --output-dir {ROOT} \\
    --graph-dir graphs/mot_3d_configuration_decision
""")
    result = subprocess.run(["qsub", str(pbs)], check=True, text=True, capture_output=True)
    job_id = result.stdout.strip()
    print(f"Submitted {pbs.name}: {job_id}")
    print(f"Single-pass slowing diagnostic: {job_id}")


if __name__ == "__main__":
    main()
