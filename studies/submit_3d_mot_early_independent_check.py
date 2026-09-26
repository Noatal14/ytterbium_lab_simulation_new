"""Submit paired early independent checks for donut then single-pass candidates."""

import subprocess
import json
from pathlib import Path


SELECTION_ROOT = Path("data/optimization/mot_3d/weekly_discovery_20260924/early_check_selection")
ROOT = Path("data/validation/mot_3d/early_independent_check_v1")


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _revision():
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()


def _header(name, revision, array=False, ncpus=200, memory="64gb", walltime="24:00:00"):
    array_line = "#PBS -J 0-2\n" if array else ""
    return f"""#!/bin/bash
#PBS -N {name}
#PBS -q zeus_combined_q
{array_line}#PBS -l select=1:ncpus={ncpus}:mem={memory}
#PBS -l walltime={walltime}

set -euo pipefail
cd ~/ytterbium_lab_simulation_new
if [[ "$(git rev-parse HEAD)" != "{revision}" ]]; then
    echo "Repository revision changed after early-check submission." >&2
    exit 42
fi
mkdir -p data/validation/mot_3d/logs
SUFFIX="${{PBS_ARRAY_INDEX:-single}}"
LOG_STEM="data/validation/mot_3d/logs/${{PBS_JOBNAME}}_${{PBS_JOBID}}_${{SUFFIX}}"
exec > "${{LOG_STEM}}.out" 2> "${{LOG_STEM}}.err"
source ~/venvs/atomsmltr/bin/activate

"""


def _submit(path, dependencies=()):
    command = ["qsub"]
    if dependencies:
        command.extend(["-W", "depend=afterok:" + ":".join(dependencies)])
    command.append(str(path))
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    job_id = result.stdout.strip()
    print(f"Submitted {path.name}: {job_id}")
    return job_id


def _family_jobs(family, revision, dependencies=()):
    selection = SELECTION_ROOT / f"{family}_candidates.json"
    family_root = ROOT / family
    pbs_root = ROOT / "pbs"
    short = "don" if family == "angled_donut" else "sp"
    array = _write(
        pbs_root / f"{family}_array.pbs",
        _header(f"m3d_{short}_early", revision, array=True)
        + f"""python -u -m studies.run_3d_mot_early_independent_check \\
    --family {family} --selection {selection} \\
    --worker-index "$PBS_ARRAY_INDEX" --num-workers 3 --npools 200 \\
    --output-dir "{family_root}/worker_${{PBS_ARRAY_INDEX}}"
""",
    )
    array_job = _submit(array, dependencies)
    merge = _write(
        pbs_root / f"{family}_merge.pbs",
        _header(f"m3d_{short}_early_m", revision, ncpus=1, memory="4gb", walltime="00:30:00")
        + f"""python -u -m studies.merge_3d_mot_early_independent_check \\
    --selection {selection} --input-root {family_root} \\
    --output-dir {family_root}/merged
""",
    )
    merge_job = _submit(merge, (array_job,))
    return merge_job


def main():
    manifest = ROOT / "submission_manifest.json"
    if manifest.exists():
        raise FileExistsError(f"Refusing duplicate early-check submission: {manifest}")
    revision = _revision()
    ROOT.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({"status": "submission_in_progress", "revision": revision}, indent=2) + "\n")
    donut_merge = _family_jobs("angled_donut", revision)
    single_merge = _family_jobs("single_pass", revision, (donut_merge,))
    manifest.write_text(
        json.dumps(
            {
                "status": "submitted",
                "revision": revision,
                "donut_merge_job": donut_merge,
                "single_pass_merge_job": single_merge,
            },
            indent=2,
        )
        + "\n"
    )
    print(f"Final early-check job: {single_merge}")


if __name__ == "__main__":
    main()
