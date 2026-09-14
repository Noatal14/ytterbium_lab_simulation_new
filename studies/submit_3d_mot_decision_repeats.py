"""Submit repeated-seed 3D-MOT decision representatives to Zeus."""

import argparse
from pathlib import Path

from config import MOT_3D_DECISION_REPEAT_CONFIG as STUDY_CONFIG
from studies.submit_3d_mot_overnight_pipeline import INPUT, _header, _submit, _write


ROOT = Path("data/validation/mot_3d/decision_repeats/current_representatives_600")


def submit(work_dir):
    work_dir = Path(work_dir)
    seeds = " ".join(str(seed) for seed in STUDY_CONFIG["repeat_seeds"])
    array_file = _write(
        work_dir / "decision_repeats_array.pbs",
        _header(
            "mot3d_decision_repeats",
            array=True,
            walltime=STUDY_CONFIG["pbs_walltime"],
            ncpus=STUDY_CONFIG["pbs_ncpus_per_shard"],
            mem=STUDY_CONFIG["pbs_memory_per_shard"],
        )
        + f"""python -u -m studies.run_3d_mot_decision_repeats \\
    --input {INPUT} --max-atoms {STUDY_CONFIG['max_atoms']} \\
    --num-shards {STUDY_CONFIG['num_shards']} --shard-index "$PBS_ARRAY_INDEX" \\
    --npools {STUDY_CONFIG['pbs_ncpus_per_shard']} --repeat-seeds {seeds} \\
    --output-dir "{ROOT}/shard_${{PBS_ARRAY_INDEX}}"
""",
    )
    array_job = _submit(array_file)
    merge_file = _write(
        work_dir / "decision_repeats_merge.pbs",
        _header("mot3d_decision_repeats_merge", walltime="00:15:00", ncpus=1, mem="4gb")
        + f"""python -u -m studies.merge_3d_mot_decision_repeats \\
    --input-root {ROOT} --output-dir {ROOT}/merged \\
    --graph-dir graphs/mot_3d_decision_repeats
""",
    )
    merge_job = _submit(merge_file, array_job)
    print(f"Decision repeats array: {array_job}")
    print(f"Decision repeats merge: {merge_job}")
    return merge_job


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", default=str(ROOT / "pbs"))
    return parser.parse_args(argv)


if __name__ == "__main__":
    submit(parse_args().work_dir)
