"""Submit the 9-point yz single-pass crossing-position comparison."""

import argparse
import subprocess
from pathlib import Path

from studies.compare_3d_mot_retention import DEFAULT_INPUT


ROOT = Path("data/validation/mot_3d/single_pass_yz_screen/position_screen_600")


def _write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _header(name, array, walltime, ncpus, mem):
    array_line = "#PBS -J 0-2\n" if array else ""
    return f"""#!/bin/bash
#PBS -N {name}
#PBS -q zeus_combined_q
{array_line}#PBS -l select=1:ncpus={ncpus}:mem={mem}
#PBS -l walltime={walltime}

set -euo pipefail
cd ~/ytterbium_lab_simulation_new
mkdir -p data/validation/mot_3d/logs
LOG_SUFFIX="${{PBS_ARRAY_INDEX:-single}}"
LOG_STEM="data/validation/mot_3d/logs/${{PBS_JOBNAME}}_${{PBS_JOBID}}_${{LOG_SUFFIX}}"
exec > "${{LOG_STEM}}.out" 2> "${{LOG_STEM}}.err"
source ~/venvs/atomsmltr/bin/activate

"""


def _submit(path, dependency=None):
    command = ["qsub"]
    if dependency:
        command.extend(["-W", f"depend=afterok:{dependency}"])
    command.append(str(path))
    result = subprocess.run(command, check=True, text=True, capture_output=True)
    job_id = result.stdout.strip()
    print(f"Submitted {Path(path).name}: {job_id}")
    return job_id


def submit(work_dir, blue_s0, reference_detuning):
    work_dir = Path(work_dir)
    detunings = (
        reference_detuning - 0.25,
        reference_detuning,
        reference_detuning + 0.25,
    )
    detuning_args = " ".join(f"{value:g}" for value in detunings)
    array_file = _write(
        work_dir / "single_pass_position_array.pbs",
        _header("mot3d_sp_pos", True, "01:30:00", 200, "64gb")
        + f"""python -u -m studies.scan_3d_mot_single_pass_position_screen \\
    --input {DEFAULT_INPUT} --max-atoms 600 --num-shards 3 \\
    --shard-index "$PBS_ARRAY_INDEX" --npools 200 --t-max 0.1 \\
    --z-offset-m-values -0.050 -0.045 -0.040 \\
    --detuning-gamma-values {detuning_args} \\
    --blue-s0 {blue_s0:g} --blue-waist-m 0.0075 \\
    --output-dir "{ROOT}/shard_${{PBS_ARRAY_INDEX}}"
""",
    )
    array_job = _submit(array_file)
    merge_file = _write(
        work_dir / "single_pass_position_merge.pbs",
        _header("mot3d_sp_pos_merge", False, "00:15:00", 1, "4gb")
        + f"""python -u -m studies.merge_3d_mot_single_pass_position_screen \\
    --input-root {ROOT} --output-dir {ROOT}/merged \\
    --graph-dir graphs/mot_3d_configuration_decision
""",
    )
    merge_job = _submit(merge_file, array_job)
    print(f"Position-screen array: {array_job}")
    print(f"Position-screen merge: {merge_job}")
    return array_job, merge_job


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", default=str(ROOT / "pbs"))
    parser.add_argument("--blue-s0", type=float, required=True)
    parser.add_argument("--reference-detuning", type=float, required=True)
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    submit(args.work_dir, args.blue_s0, args.reference_detuning)
