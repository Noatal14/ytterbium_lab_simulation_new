"""Submit the paired single-pass stability and geometry-factorial study."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from studies.run_3d_mot_single_pass_stability import ROOT


def _write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _revision():
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()


def _header(name, revision, array=None, ncpus=200, memory="64gb", walltime="04:00:00"):
    array_line = "" if array is None else f"#PBS -J {array}\n"
    return f"""#!/bin/bash
#PBS -N {name}
#PBS -q zeus_combined_q
{array_line}#PBS -l select=1:ncpus={ncpus}:mem={memory}
#PBS -l walltime={walltime}

set -euo pipefail
cd ~/ytterbium_lab_simulation_new
if [[ "$(git rev-parse HEAD)" != "{revision}" ]]; then
    echo "Repository revision changed after single-pass stability submission." >&2
    exit 42
fi
mkdir -p data/validation/mot_3d/logs
SUFFIX="${{PBS_ARRAY_INDEX:-single}}"
LOG_STEM="data/validation/mot_3d/logs/${{PBS_JOBNAME}}_${{PBS_JOBID}}_${{SUFFIX}}"
exec > "${{LOG_STEM}}.out" 2> "${{LOG_STEM}}.err"
source ~/venvs/atomsmltr/bin/activate

"""


def _submit(path, dependency=None):
    command = ["qsub"]
    if dependency:
        command.extend(["-W", f"depend=afterok:{dependency}"])
    command.append(str(path))
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    job_id = result.stdout.strip()
    print(f"Submitted {Path(path).name}: {job_id}")
    return job_id


def main():
    manifest = ROOT / "submission_manifest.json"
    if manifest.exists():
        raise FileExistsError(f"Refusing duplicate stability submission: {manifest}")
    revision = _revision()
    pbs_root = ROOT / "pbs"
    array = _write(
        pbs_root / "01_stability_array.pbs",
        _header("m3d_sp_stab", revision, array="0-2")
        + f"""python -u -m studies.run_3d_mot_single_pass_stability \\
    --shard-index "$PBS_ARRAY_INDEX" --num-shards 3 --max-atoms 600 \\
    --npools 200 --t-max 0.1 --output-dir "{ROOT}/shard_${{PBS_ARRAY_INDEX}}"
""",
    )
    array_job = _submit(array)
    merge = _write(
        pbs_root / "02_merge.pbs",
        _header(
            "m3d_sp_stab_m",
            revision,
            ncpus=1,
            memory="4gb",
            walltime="00:20:00",
        )
        + f"""python -u -m studies.merge_3d_mot_single_pass_stability \\
    --input-root "{ROOT}" --output-dir "{ROOT}/merged" \\
    --graph-path "graphs/mot_3d_configuration_decision/single_pass_stability_v1.png"
""",
    )
    merge_job = _submit(merge, array_job)
    ROOT.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps(
            {
                "kind": "single_pass_stability_submission",
                "revision": revision,
                "array_job": array_job,
                "merge_job": merge_job,
                "design": "600 paired atoms; 4 angle/aperture variants; dense blue-s0 scan",
            },
            indent=2,
        )
        + "\n"
    )
    print(f"Final single-pass stability job: {merge_job}")


if __name__ == "__main__":
    main()
