"""Submit the guarded, restart-safe week-long discovery dependency chain."""

import argparse
import json
import subprocess
from pathlib import Path

from config import MOT_3D_OPTIMIZATION_CONFIG


DEFAULT_ROOT = Path("data/optimization/mot_3d/weekly_discovery_20260924")
DONUT_SCREEN = Path(
    "data/validation/mot_3d/donut_core_shell_split_screen_v2_600/merged/"
    "donut_aperture_screen_summary.json"
)


def _revision():
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()


def _write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _header(name, walltime, ncpus, mem, revision):
    return f"""#!/bin/bash
#PBS -N {name}
#PBS -q zeus_combined_q
#PBS -l select=1:ncpus={ncpus}:mem={mem}
#PBS -l walltime={walltime}

set -euo pipefail
cd ~/ytterbium_lab_simulation_new
ACTUAL_REVISION="$(git rev-parse HEAD)"
if [[ "$ACTUAL_REVISION" != "{revision}" ]]; then
    echo "Revision changed: expected {revision}, found $ACTUAL_REVISION" >&2
    exit 42
fi
mkdir -p data/validation/mot_3d/logs
LOG_STEM="data/validation/mot_3d/logs/${{PBS_JOBNAME}}_${{PBS_JOBID}}"
exec > "${{LOG_STEM}}.out" 2> "${{LOG_STEM}}.err"
source ~/venvs/atomsmltr/bin/activate

"""


def _submit(path, dependencies=()):
    command = ["qsub"]
    dependencies = tuple(dependencies)
    if dependencies:
        command.extend(["-W", "depend=afterok:" + ":".join(dependencies)])
    command.append(str(path))
    result = subprocess.run(command, check=True, text=True, capture_output=True)
    job_id = result.stdout.strip()
    print(f"Submitted {Path(path).name}: {job_id}")
    return job_id


def _targets(total):
    base, remainder = divmod(total, 3)
    return tuple(base + (index < remainder) for index in range(3))


def _worker_pbs(path, family, worker, target, sampler_seed, root, revision, round_index):
    short = "don" if family == "angled_donut" else "sp"
    return _write(
        path,
        _header(
            f"m3d_{short}{worker}_r{round_index}", "24:00:00", 200, "64gb", revision
        )
        + f"""python -u -m studies.optimize_3d_mot_full \\
    --family {family} --worker-index {worker} \\
    --target-completed-trials {target} --sampler-seed {sampler_seed} \\
    --output-dir {root / family} --npools 200 --timeout-s 82800
""",
    )


def _submit_family(family, rounds, dependencies, root, pbs_dir, revision):
    total = MOT_3D_OPTIMIZATION_CONFIG[family]["total_discovery_trials"]
    targets = _targets(total)
    sampler_seeds = (271_001, 271_002, 271_003)
    final_jobs = []
    all_jobs = []
    for worker, (target, sampler_seed) in enumerate(zip(targets, sampler_seeds)):
        previous = tuple(dependencies)
        for round_index in range(1, rounds + 1):
            pbs = _worker_pbs(
                pbs_dir / family / f"worker_{worker}_round_{round_index}.pbs",
                family,
                worker,
                target,
                sampler_seed,
                root,
                revision,
                round_index,
            )
            job_id = _submit(pbs, previous)
            all_jobs.append(job_id)
            previous = (job_id,)
        final_jobs.append(previous[0])
    return all_jobs, final_jobs


def _merge_pbs(path, family, root, revision):
    short = "don" if family == "angled_donut" else "sp"
    expected = MOT_3D_OPTIMIZATION_CONFIG[family]["total_discovery_trials"]
    return _write(
        path,
        _header(f"m3d_{short}_merge", "00:30:00", 1, "4gb", revision)
        + f"""python -u -m studies.merge_3d_mot_full_optimization \\
    --input-root {root / family} --output-dir {root / family / 'merged'} \\
    --expected-trial-count {expected}
""",
    )


def submit(args):
    root = Path(args.output_root)
    pbs_dir = root / "pbs"
    revision = _revision()
    manifest_path = root / "submission_manifest.json"
    if manifest_path.exists():
        raise FileExistsError(
            f"A weekly discovery submission already exists at {manifest_path}. "
            "Refusing to submit a duplicate chain against the same studies."
        )
    root.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "kind": "guarded_weekly_mot_3d_discovery_submission",
                "status": "submission_in_progress",
                "software_revision": revision,
                "output_root": str(root),
            },
            indent=2,
        )
        + "\n"
    )

    preflight = _write(
        pbs_dir / "00_preflight.pbs",
        _header("m3d_preflight", "00:10:00", 1, "2gb", revision)
        + f"""python -u -m studies.validate_3d_mot_discovery_preflight \\
    --summary {args.donut_screen} --minimum-fraction {args.minimum_donut_fraction:g}
""",
    )
    preflight_job = _submit(preflight)

    smoke_jobs = []
    for index, family in enumerate(("angled_donut", "single_pass")):
        short = "don" if family == "angled_donut" else "sp"
        pbs = _write(
            pbs_dir / f"01_smoke_{family}.pbs",
            _header(f"m3d_{short}_smoke", "01:00:00", 12, "8gb", revision)
            + f"""python -u -m studies.optimize_3d_mot_full \\
    --family {family} --worker-index 0 \\
    --target-completed-trials 1 --sampler-seed {281001 + index} \\
    --output-dir {root / 'smoke' / family} \\
    --ensemble-count 1 --particles-per-ensemble 12 --npools 12 \\
    --timeout-s 3000
""",
        )
        smoke_jobs.append(_submit(pbs, (preflight_job,)))

    donut_jobs, donut_final = _submit_family(
        "angled_donut",
        args.donut_rounds,
        smoke_jobs,
        root,
        pbs_dir,
        revision,
    )
    donut_merge_job = _submit(
        _merge_pbs(
            pbs_dir / "03_merge_angled_donut.pbs",
            "angled_donut",
            root,
            revision,
        ),
        donut_final,
    )

    single_jobs, single_final = _submit_family(
        "single_pass",
        args.single_pass_rounds,
        (donut_merge_job,),
        root,
        pbs_dir,
        revision,
    )
    single_merge_job = _submit(
        _merge_pbs(
            pbs_dir / "05_merge_single_pass.pbs",
            "single_pass",
            root,
            revision,
        ),
        single_final,
    )

    manifest = {
        "kind": "guarded_weekly_mot_3d_discovery_submission",
        "software_revision": revision,
        "output_root": str(root),
        "donut_screen": str(args.donut_screen),
        "minimum_donut_fraction": args.minimum_donut_fraction,
        "donut_rounds": args.donut_rounds,
        "single_pass_rounds": args.single_pass_rounds,
        "jobs": {
            "preflight": preflight_job,
            "smoke": smoke_jobs,
            "donut_workers": donut_jobs,
            "donut_merge": donut_merge_job,
            "single_pass_workers": single_jobs,
            "single_pass_merge": single_merge_job,
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Saved submission manifest: {manifest_path}")
    print(f"Final dependency-chain job: {single_merge_job}")
    return manifest


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", default=str(DEFAULT_ROOT))
    parser.add_argument("--donut-screen", default=str(DONUT_SCREEN))
    parser.add_argument("--minimum-donut-fraction", type=float, default=0.20)
    parser.add_argument("--donut-rounds", type=int, default=2)
    parser.add_argument("--single-pass-rounds", type=int, default=3)
    return parser.parse_args(argv)


if __name__ == "__main__":
    submit(parse_args())
