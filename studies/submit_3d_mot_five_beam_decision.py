"""Submit the compact corrected-five-beam decision screen to Zeus."""

import argparse
from pathlib import Path

from config import MOT_3D_FIVE_BEAM_REFINED_SCREEN_CONFIG as STUDY_CONFIG
from studies.submit_3d_mot_overnight_pipeline import INPUT, _header, _submit, _write


ROOT = Path("data/validation/mot_3d/five_beam_decision/refined_600")


def submit(work_dir):
    work_dir = Path(work_dir)
    array_file = _write(
        work_dir / "five_beam_decision_array.pbs",
        _header(
            "mot3d_five_decision",
            array=True,
            walltime=STUDY_CONFIG["pbs_walltime"],
            ncpus=STUDY_CONFIG["pbs_ncpus_per_shard"],
            mem=STUDY_CONFIG["pbs_memory_per_shard"],
        )
        + f"""python -u -m studies.scan_3d_mot_five_beam_decision \\
    --input {INPUT} --max-atoms {STUDY_CONFIG['max_atoms']} \\
    --num-shards {STUDY_CONFIG['num_shards']} --shard-index "$PBS_ARRAY_INDEX" \\
    --npools {STUDY_CONFIG['pbs_ncpus_per_shard']} --refined \\
    --output-dir "{ROOT}/shard_${{PBS_ARRAY_INDEX}}"
""",
    )
    array_job = _submit(array_file)
    merge_file = _write(
        work_dir / "five_beam_decision_merge.pbs",
        _header("mot3d_five_decision_merge", walltime="00:15:00", ncpus=1, mem="4gb")
        + f"""python -u -m studies.merge_3d_mot_five_beam_decision \\
    --input-root {ROOT} --output-dir {ROOT}/merged \\
    --graph-dir graphs/mot_3d_five_beam_decision
""",
    )
    merge_job = _submit(merge_file, array_job)
    print(f"Five-beam decision array: {array_job}")
    print(f"Five-beam decision merge: {merge_job}")
    return merge_job


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", default=str(ROOT / "pbs"))
    return parser.parse_args(argv)


if __name__ == "__main__":
    submit(parse_args().work_dir)
