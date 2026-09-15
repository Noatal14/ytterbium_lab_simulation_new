"""Submit the final inexpensive checks before full 3D-MOT optimization."""

import argparse
from pathlib import Path

from config import MOT_3D_DECISION_REPEAT_CONFIG as REPEAT_CONFIG
from studies import submit_3d_mot_five_beam_decision as boundary_submitter
from studies.submit_3d_mot_overnight_pipeline import INPUT, _header, _submit, _write


BOUNDARY_SUMMARY = (
    boundary_submitter.ROOT / "merged" / "five_beam_decision_summary.json"
)
REPEAT_ROOT = Path(
    "data/validation/mot_3d/decision_repeats/finalists_from_boundary_600"
)


def submit(work_dir):
    work_dir = Path(work_dir)
    boundary_merge_job = boundary_submitter.submit(
        boundary_submitter.ROOT / "pbs"
    )
    seeds = " ".join(str(seed) for seed in REPEAT_CONFIG["repeat_seeds"])
    repeat_array_file = _write(
        work_dir / "finalist_repeats_array.pbs",
        _header(
            "mot3d_finalist_repeats",
            array=True,
            walltime=REPEAT_CONFIG["pbs_walltime"],
            ncpus=REPEAT_CONFIG["pbs_ncpus_per_shard"],
            mem=REPEAT_CONFIG["pbs_memory_per_shard"],
        )
        + f"""python -u -m studies.run_3d_mot_decision_repeats \\
    --input {INPUT} --max-atoms {REPEAT_CONFIG['max_atoms']} \\
    --num-shards {REPEAT_CONFIG['num_shards']} --shard-index "$PBS_ARRAY_INDEX" \\
    --npools {REPEAT_CONFIG['pbs_ncpus_per_shard']} --repeat-seeds {seeds} \\
    --five-beam-summary {BOUNDARY_SUMMARY} \\
    --configurations full_donut five_beam_gravity \\
    --output-dir "{REPEAT_ROOT}/shard_${{PBS_ARRAY_INDEX}}"
""",
    )
    repeat_array_job = _submit(repeat_array_file, boundary_merge_job)
    repeat_merge_file = _write(
        work_dir / "finalist_repeats_merge.pbs",
        _header("mot3d_finalist_repeats_merge", walltime="00:15:00", ncpus=1, mem="4gb")
        + f"""python -u -m studies.merge_3d_mot_decision_repeats \\
    --input-root {REPEAT_ROOT} --output-dir {REPEAT_ROOT}/merged \\
    --graph-dir graphs/mot_3d_decision_repeats/finalists_from_boundary
""",
    )
    repeat_merge_job = _submit(repeat_merge_file, repeat_array_job)
    print(f"Boundary-grid merge: {boundary_merge_job}")
    print(f"Finalist repeats array: {repeat_array_job}")
    print(f"Finalist repeats merge: {repeat_merge_job}")
    return repeat_merge_job


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", default=str(REPEAT_ROOT / "pbs"))
    return parser.parse_args(argv)


if __name__ == "__main__":
    submit(parse_args().work_dir)
