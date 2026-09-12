"""Submit the three-shard donut blue-beam ablation study to Zeus PBS."""

import argparse
from pathlib import Path

from config import MOT_3D_DONUT_ABLATION_CONFIG
from studies.submit_3d_mot_overnight_pipeline import INPUT, _header, _submit, _write


ROOT = Path("data/validation/mot_3d/donut_ablation/full_600")


def submit(work_dir):
    settings = MOT_3D_DONUT_ABLATION_CONFIG
    if settings["num_shards"] != 3:
        raise ValueError("The current PBS array helper requires exactly three shards.")
    work_dir = Path(work_dir)
    array_file = _write(
        work_dir / "donut_ablation_array.pbs",
        _header(
            "mot3d_donut_ablation",
            array=True,
            walltime=settings["pbs_walltime"],
            ncpus=settings["pbs_ncpus_per_shard"],
            mem=settings["pbs_memory_per_shard"],
        )
        + f"""python -u -m studies.analyze_3d_mot_donut_ablation \\
    --input {INPUT} --max-atoms {settings['max_atoms']} \\
    --num-shards {settings['num_shards']} --shard-index "$PBS_ARRAY_INDEX" \\
    --npools {settings['pbs_ncpus_per_shard']} \\
    --output-dir "{ROOT}/shard_${{PBS_ARRAY_INDEX}}"
""",
    )
    array_job = _submit(array_file)
    merge_file = _write(
        work_dir / "donut_ablation_merge.pbs",
        _header("mot3d_donut_ablation_merge", walltime="00:30:00", ncpus=1, mem="8gb")
        + f"""python -u -m studies.merge_3d_mot_donut_ablation_shards \\
    --input-root {ROOT} --output-dir {ROOT}/merged \\
    --graph-dir graphs/mot_3d_donut_ablation
""",
    )
    merge_job = _submit(merge_file, array_job)
    print(f"Ablation array: {array_job}")
    print(f"Ablation merge: {merge_job}")
    return merge_job


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", default=str(ROOT / "pbs"))
    return parser.parse_args(argv)


if __name__ == "__main__":
    submit(parse_args().work_dir)
