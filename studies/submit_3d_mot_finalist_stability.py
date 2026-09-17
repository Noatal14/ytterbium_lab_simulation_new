"""Submit the direct 400-ms finalist comparison to Zeus."""

import argparse
import subprocess
from pathlib import Path

from config import MOT_3D_FINALIST_STABILITY_CONFIG as STUDY_CONFIG
from studies.compare_3d_mot_retention import DEFAULT_INPUT


ROOT = Path("data/validation/mot_3d/finalist_stability/full_ensemble_400ms")


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


def _write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _submit(path, dependency=None):
    command = ["qsub"]
    if dependency:
        command.extend(["-W", f"depend=afterok:{dependency}"])
    command.append(str(path))
    result = subprocess.run(command, check=True, text=True, capture_output=True)
    job_id = result.stdout.strip()
    print(f"Submitted {Path(path).name}: {job_id}")
    return job_id


def submit(work_dir):
    settings = STUDY_CONFIG
    work_dir = Path(work_dir)
    array_file = _write(
        work_dir / "finalist_stability_array.pbs",
        _header(
            "mot3d_finalists_400ms",
            array=True,
            walltime=settings["pbs_walltime"],
            ncpus=settings["pbs_ncpus_per_shard"],
            mem=settings["pbs_memory_per_shard"],
        )
        + f"""python -u -m studies.compare_3d_mot_finalist_stability \\
    --input {DEFAULT_INPUT} \\
    --num-shards {settings['num_shards']} \\
    --shard-index "$PBS_ARRAY_INDEX" \\
    --npools {settings['pbs_ncpus_per_shard']} \\
    --t-max {settings['t_max_s']} \\
    --output-dir "{ROOT}/shard_${{PBS_ARRAY_INDEX}}"
""",
    )
    array_job = _submit(array_file)
    merge_file = _write(
        work_dir / "finalist_stability_merge.pbs",
        _header(
            "mot3d_finalists_merge",
            array=False,
            walltime="00:30:00",
            ncpus=1,
            mem="8gb",
        )
        + f"""python -u -m studies.merge_3d_mot_finalist_stability \\
    --input-root {ROOT} \\
    --output-dir {ROOT}/merged
""",
    )
    merge_job = _submit(merge_file, array_job)
    print(f"Finalist array: {array_job}")
    print(f"Finalist merge: {merge_job}")
    return array_job, merge_job


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", default=str(ROOT / "pbs"))
    return parser.parse_args(argv)


if __name__ == "__main__":
    submit(parse_args().work_dir)
