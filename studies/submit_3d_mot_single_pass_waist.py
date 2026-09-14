"""Submit the focused three-shard single-pass waist screen to Zeus PBS."""

import argparse
from pathlib import Path

from config import MOT_3D_SINGLE_PASS_WAIST_SCREEN_CONFIG
from studies.submit_3d_mot_overnight_pipeline import INPUT, _header, _submit, _write


ROOT = Path("data/validation/mot_3d/single_pass_waist_screen/focused_600")


def submit(work_dir):
    settings = MOT_3D_SINGLE_PASS_WAIST_SCREEN_CONFIG
    work_dir = Path(work_dir)
    array_file = _write(
        work_dir / "single_pass_waist_array.pbs",
        _header(
            "mot3d_single_pass_waist",
            array=True,
            walltime=settings["pbs_walltime"],
            ncpus=settings["pbs_ncpus_per_shard"],
            mem=settings["pbs_memory_per_shard"],
        )
        + f"""python -u -m studies.scan_3d_mot_single_pass_waist \\
    --input {INPUT} --max-atoms {settings['max_atoms']} \\
    --num-shards {settings['num_shards']} --shard-index "$PBS_ARRAY_INDEX" \\
    --npools {settings['pbs_ncpus_per_shard']} \\
    --output-dir "{ROOT}/shard_${{PBS_ARRAY_INDEX}}"
""",
    )
    array_job = _submit(array_file)
    merge_file = _write(
        work_dir / "single_pass_waist_merge.pbs",
        _header("mot3d_single_pass_waist_merge", walltime="00:15:00", ncpus=1, mem="4gb")
        + f"""python -u -m studies.merge_3d_mot_single_pass_waist \\
    --input-root {ROOT} --output-dir {ROOT}/merged \\
    --graph-dir graphs/mot_3d_single_pass_waist_screen
""",
    )
    merge_job = _submit(merge_file, array_job)
    print(f"Single-pass waist array: {array_job}")
    print(f"Single-pass waist merge: {merge_job}")
    return merge_job


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", default=str(ROOT / "pbs"))
    return parser.parse_args(argv)


if __name__ == "__main__":
    submit(parse_args().work_dir)
