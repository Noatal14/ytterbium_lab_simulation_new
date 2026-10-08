"""Submit the guarded paired old-versus-corrected Zeeman impact workflow."""

import json
import os
import subprocess
from pathlib import Path

from studies.zeeman.magnet_impact import ROOT, SEEDS


PBS_ROOT = ROOT / "pbs"


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _revision():
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()


def _header(name, revision, array=None, ncpus=200, memory="64gb", walltime="24:00:00"):
    array_line = "" if array is None else f"#PBS -J {array}\n"
    return f"""#!/bin/bash
#PBS -N {name}
#PBS -q zeus_combined_q
{array_line}#PBS -l select=1:ncpus={ncpus}:mem={memory}
#PBS -l walltime={walltime}

set -euo pipefail
cd ~/ytterbium_lab_simulation_new
if [[ "$(git rev-parse HEAD)" != "{revision}" ]]; then
    echo "Repository revision changed after corrected-Zeeman submission." >&2
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


def main():
    manifest = ROOT / "submission_manifest.json"
    if manifest.exists():
        raise FileExistsError(f"Refusing duplicate submission: {manifest}")
    revision = _revision()
    ROOT.mkdir(parents=True, exist_ok=True)
    temporary_manifest = manifest.with_name(f".{manifest.name}.{os.getpid()}.tmp")
    temporary_manifest.write_text(
        json.dumps(
            {
                "kind": "corrected_zeeman_paired_impact_submission",
                "status": "submitting",
                "revision": revision,
                "seeds": list(SEEDS),
            },
            indent=2,
        )
        + "\n"
    )
    os.replace(temporary_manifest, manifest)
    seed_words = " ".join(str(seed) for seed in SEEDS)
    upstream = _write(
        PBS_ROOT / "01_corrected_upstream_array.pbs",
        _header("m3d_zcorr_up", revision, array="0-3")
        + f"""SEEDS=({seed_words})
python -u -m studies.zeeman.magnet_impact upstream \\
    --seed "${{SEEDS[$PBS_ARRAY_INDEX]}}" --npools 200
""",
    )
    upstream_job = _submit(upstream)

    mot3d = _write(
        PBS_ROOT / "02_paired_finalists_array.pbs",
        _header("m3d_zcorr_3d", revision, array="0-11", walltime="08:00:00")
        + """POPULATIONS=(old corrected)
FAMILIES=(angled_donut single_pass)
RECOIL_SEEDS=(44001 44002 44003)
INDEX="$PBS_ARRAY_INDEX"
SEED_INDEX=$((INDEX % 3))
INDEX=$((INDEX / 3))
FAMILY_INDEX=$((INDEX % 2))
POPULATION_INDEX=$((INDEX / 2))
python -u -m studies.zeeman.magnet_impact mot3d \\
    --population "${POPULATIONS[$POPULATION_INDEX]}" \\
    --family "${FAMILIES[$FAMILY_INDEX]}" \\
    --recoil-seed "${RECOIL_SEEDS[$SEED_INDEX]}" --npools 200
""",
    )
    mot3d_job = _submit(mot3d, (upstream_job,))

    merge = _write(
        PBS_ROOT / "03_merge.pbs",
        _header("m3d_zcorr_m", revision, ncpus=1, memory="8gb", walltime="00:30:00")
        + "python -u -m studies.zeeman.magnet_impact merge\n",
    )
    merge_job = _submit(merge, (mot3d_job,))
    manifest.write_text(
        json.dumps(
            {
                "kind": "corrected_zeeman_paired_impact_submission",
                "status": "submitted",
                "revision": revision,
                "seeds": list(SEEDS),
                "upstream_job": upstream_job,
                "mot3d_job": mot3d_job,
                "merge_job": merge_job,
            },
            indent=2,
        )
        + "\n"
    )
    print(f"Final corrected-Zeeman impact job: {merge_job}")


if __name__ == "__main__":
    main()
