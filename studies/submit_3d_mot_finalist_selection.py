"""Submit full-existing-data finalist selection for both 3D-MOT families."""

import json
import subprocess
from pathlib import Path


CLOSURE_ROOT = Path("data/optimization/mot_3d/closure_refinement_v1")
ROOT = Path("data/optimization/mot_3d/finalist_selection_v1")


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _revision():
    return subprocess.run(["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()


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
    echo "Repository revision changed after finalist submission." >&2
    exit 42
fi
mkdir -p data/validation/mot_3d/logs
SUFFIX="${{PBS_ARRAY_INDEX:-single}}"
LOG_STEM="data/validation/mot_3d/logs/${{PBS_JOBNAME}}_${{PBS_JOBID}}_${{SUFFIX}}"
exec > "${{LOG_STEM}}.out" 2> "${{LOG_STEM}}.err"
source ~/venvs/atomsmltr/bin/activate

"""


def _submit(path, dependencies=(), dependency_type="afterok"):
    command = ["qsub"]
    if dependencies:
        command.extend(["-W", f"depend={dependency_type}:" + ":".join(dependencies)])
    command.append(str(path))
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    job_id = result.stdout.strip()
    print(f"Submitted {path.name}: {job_id}")
    return job_id


def _family_jobs(family, revision, dependencies=()):
    short = "don" if family == "angled_donut" else "sp"
    family_root = ROOT / family
    selection = ROOT / "selection" / f"{family}_finalists.json"
    pbs_root = ROOT / "pbs"
    command = f"""python -u -m studies.run_3d_mot_finalist_selection \\
    --family {family} --selection {selection} \\
    --finalist-index "$PBS_ARRAY_INDEX" --npools 200 \\
    --output-dir "{family_root}/finalist_${{PBS_ARRAY_INDEX}}"
"""
    first = _write(pbs_root / f"{family}_round_1_array.pbs", _header(f"m3d_{short}_fin1", revision, array=True) + command)
    first_job = _submit(first, dependencies)
    second = _write(pbs_root / f"{family}_round_2_array.pbs", _header(f"m3d_{short}_fin2", revision, array=True) + command)
    second_job = _submit(second, (first_job,), dependency_type="afterany")
    merge = _write(
        pbs_root / f"{family}_merge.pbs",
        _header(f"m3d_{short}_fin_m", revision, ncpus=1, memory="8gb", walltime="00:30:00")
        + f"""python -u -m studies.merge_3d_mot_finalist_selection \\
    --selection {selection} --input-root {family_root} \\
    --output-dir {family_root}/merged
""",
    )
    return _submit(merge, (second_job,))


def main():
    manifest = ROOT / "submission_manifest.json"
    if manifest.exists():
        raise FileExistsError(f"Refusing duplicate finalist submission: {manifest}")
    revision = _revision()
    selection_root = ROOT / "selection"
    for family in ("angled_donut", "single_pass"):
        subprocess.run(
            [
                "python", "-m", "studies.select_3d_mot_finalists",
                "--family", family,
                "--closure-summary", str(CLOSURE_ROOT / family / "merged" / "refinement_summary.json"),
                "--output", str(selection_root / f"{family}_finalists.json"),
            ],
            check=True,
        )
    ROOT.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({"status": "submission_in_progress", "revision": revision}, indent=2) + "\n")
    donut_merge = _family_jobs("angled_donut", revision)
    single_merge = _family_jobs("single_pass", revision, (donut_merge,))
    manifest.write_text(
        json.dumps(
            {
                "status": "submitted",
                "revision": revision,
                "design": "3 finalists/family, all 15840 existing survivors, 3 matched recoil seeds",
                "donut_merge_job": donut_merge,
                "single_pass_merge_job": single_merge,
            },
            indent=2,
        ) + "\n"
    )
    print(f"Final finalist-selection job: {single_merge}")


if __name__ == "__main__":
    main()
