"""Submit the three-node 600-atom donut velocity diagnostic to Zeus."""

import argparse
from pathlib import Path

from studies.compare_3d_mot_retention import DEFAULT_INPUT
from studies.submit_3d_mot_five_beam_velocity import _header, _submit, _write


ROOT = Path("data/validation/mot_3d/donut_velocity/unified_style_600_100ms")


def submit(work_dir):
    work_dir = Path(work_dir)
    array_file = _write(
        work_dir / "donut_velocity_array.pbs",
        _header("mot3d_donut_velocity", True, "02:00:00", 200, "64gb")
        + f"""python -u -m studies.analyze_3d_mot_donut_velocity \\
    --input {DEFAULT_INPUT} --max-atoms 600 --num-shards 3 \\
    --shard-index "$PBS_ARRAY_INDEX" --npools 200 \\
    --output-dir "{ROOT}/shard_${{PBS_ARRAY_INDEX}}"
""",
    )
    array_job = _submit(array_file)
    merge_file = _write(
        work_dir / "donut_velocity_merge.pbs",
        _header("mot3d_donut_velocity_merge", False, "00:15:00", 1, "4gb")
        + f"""python -u -m studies.merge_3d_mot_donut_velocity \\
    --input-root {ROOT} --output-dir {ROOT}/merged
""",
    )
    merge_job = _submit(merge_file, array_job)
    print(f"Donut velocity array: {array_job}")
    print(f"Donut velocity merge: {merge_job}")
    return array_job, merge_job


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", default=str(ROOT / "pbs"))
    return parser.parse_args(argv)


if __name__ == "__main__":
    submit(parse_args().work_dir)
