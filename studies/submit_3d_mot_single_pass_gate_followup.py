"""Submit the focused single-pass finite-gate follow-up to Zeus."""

import argparse
from pathlib import Path

from config import MOT_3D_SINGLE_PASS_GATE_FOLLOWUP_CONFIG
from studies.submit_3d_mot_overnight_pipeline import INPUT, _header, _submit, _write


ROOT = Path("data/validation/mot_3d/single_pass_gate_followup/extended_600")


def submit(work_dir):
    settings = MOT_3D_SINGLE_PASS_GATE_FOLLOWUP_CONFIG
    work_dir = Path(work_dir)
    array_file = _write(
        work_dir / "single_pass_gate_followup_array.pbs",
        _header(
            "mot3d_single_gate_followup",
            array=True,
            walltime=settings["pbs_walltime"],
            ncpus=settings["pbs_ncpus_per_shard"],
            mem=settings["pbs_memory_per_shard"],
        )
        + f"""python -u -m studies.scan_3d_mot_single_pass_gate_followup \\
    --input {INPUT} --max-atoms {settings['max_atoms']} \\
    --num-shards {settings['num_shards']} --shard-index "$PBS_ARRAY_INDEX" \\
    --npools {settings['pbs_ncpus_per_shard']} \\
    --output-dir "{ROOT}/shard_${{PBS_ARRAY_INDEX}}"
""",
    )
    array_job = _submit(array_file)
    merge_file = _write(
        work_dir / "single_pass_gate_followup_merge.pbs",
        _header("mot3d_single_gate_followup_merge", walltime="00:15:00", ncpus=1, mem="4gb")
        + f"""python -u -m studies.merge_3d_mot_single_pass_gate_followup \\
    --input-root {ROOT} --output-dir {ROOT}/merged \\
    --graph-dir graphs/mot_3d_single_pass_gate_followup
""",
    )
    merge_job = _submit(merge_file, array_job)
    print(f"Single-pass follow-up array: {array_job}")
    print(f"Single-pass follow-up merge: {merge_job}")
    return merge_job


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", default=str(ROOT / "pbs"))
    return parser.parse_args(argv)


if __name__ == "__main__":
    submit(parse_args().work_dir)
