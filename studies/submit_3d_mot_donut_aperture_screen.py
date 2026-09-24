"""Submit the three-point, 600-particle physical narrow-donut sanity screen."""

import subprocess
from pathlib import Path

from studies.compare_3d_mot_retention import DEFAULT_INPUT


ROOT = Path("data/validation/mot_3d/donut_aperture_split_screen_v1_600")


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


def main():
    pbs_dir = ROOT / "pbs"
    array_file = _write(
        pbs_dir / "donut_aperture_screen_array.pbs",
        _header("mot3d_donut_ap", True, "01:00:00", 200, "64gb")
        + f"""python -u -m studies.scan_3d_mot_donut_aperture_screen \\
    --input {DEFAULT_INPUT} --max-atoms 600 --num-shards 3 \\
    --shard-index "$PBS_ARRAY_INDEX" --npools 200 --t-max 0.1 \\
    --split-radius-m-values 0.004 0.005 0.006 \\
    --aperture-radius-m 0.0075 \\
    --output-dir "{ROOT}/shard_${{PBS_ARRAY_INDEX}}"
""",
    )
    array_job = _submit(array_file)
    merge_file = _write(
        pbs_dir / "donut_aperture_screen_merge.pbs",
        _header("mot3d_donut_ap_merge", False, "00:15:00", 1, "4gb")
        + f"""python -u -m studies.merge_3d_mot_donut_aperture_screen \\
    --input-root {ROOT} --output-dir {ROOT}/merged \\
    --graph-dir graphs/mot_3d_configuration_decision
""",
    )
    merge_job = _submit(merge_file, array_job)
    print(f"Donut-aperture screen array: {array_job}")
    print(f"Donut-aperture screen merge: {merge_job}")


if __name__ == "__main__":
    main()
