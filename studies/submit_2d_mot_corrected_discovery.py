"""Submit corrected-Zeeman production ensembles and fixed-s0 2D discovery."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from studies.generate_corrected_zeeman_ensembles import OUTPUT_DIR as ENSEMBLE_DIR


ROOT = Path("data/optimization/mot_2d/corrected_zeeman_s0_1p3_discovery_v1")
SEEDS = tuple(range(3000, 3020))
DISCOVERY_SEEDS = SEEDS[:4]
SAMPLER_SEEDS = (62001, 62002, 62003)
ANCHORS = (
    (-1.1840645, 0.049217614),
    (-2.0, 0.049217614),
    (-0.6, 0.049217614),
)


def _write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _revision():
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()


def _header(name, revision, array=None, walltime="24:00:00", ncpus=200, memory="64gb"):
    array_line = "" if array is None else f"#PBS -J {array}\n"
    return f"""#!/bin/bash
#PBS -N {name}
#PBS -q zeus_combined_q
{array_line}#PBS -l select=1:ncpus={ncpus}:mem={memory}
#PBS -l walltime={walltime}

set -euo pipefail
cd ~/ytterbium_lab_simulation_new
if [[ "$(git rev-parse HEAD)" != "{revision}" ]]; then
    echo "Repository revision changed after corrected 2D-MOT submission." >&2
    exit 42
fi
mkdir -p data/validation/mot_2d/logs
SUFFIX="${{PBS_ARRAY_INDEX:-single}}"
LOG_STEM="data/validation/mot_2d/logs/${{PBS_JOBNAME}}_${{PBS_JOBID}}_${{SUFFIX}}"
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
    print(f"Submitted {Path(path).name}: {job_id}")
    return job_id


def _worker_command(worker_index):
    seeds = " ".join(map(str, DISCOVERY_SEEDS))
    detuning, radius = ANCHORS[worker_index]
    return f"""python -u -m studies.optimize_2d_mot_joint \\
    --fixed-s0 1.3 --n-trials 20 --n-ensembles 4 \\
    --particles-per-ensemble 1000 --mot-seed-start 18000 \\
    --ensemble-dir "{ENSEMBLE_DIR}" --zeeman-seeds {seeds} \\
    --detuning-bounds -3.0 -0.4 --magnet-radius-bounds-m 0.045 0.051 \\
    --stochastic-solver hybrid --npools 200 \\
    --sampler-seed {SAMPLER_SEEDS[worker_index]} \\
    --enqueue-point {detuning} {radius} \\
    --study-name corrected_zeeman_s0_1p3_worker_{worker_index} \\
    --output-dir "{ROOT}/worker_{worker_index}"
"""


def main():
    manifest = ROOT / "submission_manifest.json"
    if manifest.exists():
        raise FileExistsError(f"Refusing duplicate corrected-2D submission: {manifest}")
    revision = _revision()
    ROOT.mkdir(parents=True, exist_ok=True)
    temporary = manifest.with_name(f".{manifest.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(
            {
                "status": "submitting",
                "kind": "corrected_zeeman_fixed_s0_2d_discovery",
                "revision": revision,
                "fixed_s0": 1.3,
            },
            indent=2,
        )
        + "\n"
    )
    os.replace(temporary, manifest)
    pbs_root = ROOT / "pbs"
    zeeman = _write(
        pbs_root / "00_corrected_zeeman_array.pbs",
        _header("m2d_zcorr", revision, array="0-19", walltime="04:00:00")
        + f"""SEEDS=({' '.join(map(str, SEEDS))})
python -u -m studies.generate_corrected_zeeman_ensembles \\
    --seed "${{SEEDS[$PBS_ARRAY_INDEX]}}" --npools 200 \\
    --output-dir "{ENSEMBLE_DIR}"
""",
    )
    zeeman_job = _submit(zeeman)

    smoke = _write(
        pbs_root / "01_smoke.pbs",
        _header("m2d_corr_sm", revision, walltime="01:00:00", ncpus=12, memory="8gb")
        + f"""python -u -m studies.optimize_2d_mot_joint \\
    --fixed-s0 1.3 --n-trials 1 --n-ensembles 1 \\
    --particles-per-ensemble 200 --mot-seed-start 18000 \\
    --ensemble-dir "{ENSEMBLE_DIR}" --zeeman-seeds {DISCOVERY_SEEDS[0]} \\
    --detuning-bounds -3.0 -0.4 --magnet-radius-bounds-m 0.045 0.051 \\
    --stochastic-solver hybrid --npools 12 --sampler-seed 61999 \\
    --enqueue-point {ANCHORS[0][0]} {ANCHORS[0][1]} \\
    --study-name corrected_zeeman_s0_1p3_smoke \\
    --output-dir "{ROOT}/smoke"
""",
    )
    smoke_job = _submit(smoke, (zeeman_job,))

    final_worker_jobs = []
    worker_jobs = []
    for worker_index in range(3):
        first = _write(
            pbs_root / f"worker_{worker_index}_round_1.pbs",
            _header(f"m2d_c{worker_index}_r1", revision)
            + _worker_command(worker_index),
        )
        first_job = _submit(first, (smoke_job,))
        second = _write(
            pbs_root / f"worker_{worker_index}_round_2.pbs",
            _header(f"m2d_c{worker_index}_r2", revision)
            + _worker_command(worker_index),
        )
        second_job = _submit(second, (first_job,), dependency_type="afterany")
        worker_jobs.append([first_job, second_job])
        final_worker_jobs.append(second_job)

    merge = _write(
        pbs_root / "02_merge.pbs",
        _header("m2d_corr_m", revision, walltime="00:20:00", ncpus=1, memory="4gb")
        + f"""python -u -m studies.merge_2d_mot_corrected_discovery \\
    --input-root "{ROOT}" --output-dir "{ROOT}/merged"
""",
    )
    merge_job = _submit(merge, tuple(final_worker_jobs))
    manifest.write_text(
        json.dumps(
            {
                "status": "submitted",
                "kind": "corrected_zeeman_fixed_s0_2d_discovery",
                "revision": revision,
                "fixed_s0": 1.3,
                "production_zeeman_seeds": list(SEEDS),
                "discovery_zeeman_seeds": list(DISCOVERY_SEEDS),
                "particles_per_discovery_ensemble": 1000,
                "total_discovery_trials": 120,
                "zeeman_job": zeeman_job,
                "smoke_job": smoke_job,
                "worker_jobs": worker_jobs,
                "merge_job": merge_job,
            },
            indent=2,
        )
        + "\n"
    )
    print(f"Final corrected-2D discovery job: {merge_job}")


if __name__ == "__main__":
    main()
