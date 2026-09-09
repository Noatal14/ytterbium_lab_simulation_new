"""Submit the fast three-shard 3D-MOT screening run to PBS."""

import argparse
from pathlib import Path

import numpy as np

from config import MOT_3D_CONFIGURATIONS, MOT_3D_SCREENING_CONFIG
from studies.submit_3d_mot_overnight_pipeline import INPUT, ROOT, _header, _submit, _write


def submit_screening(work_dir, profiles, max_atoms):
    unknown = sorted(set(profiles) - set(MOT_3D_CONFIGURATIONS))
    if unknown:
        raise ValueError(f"Unknown profiles: {unknown}")
    work_dir = Path(work_dir)
    output_root = ROOT / "screening" / "fast_geometry_screen"
    profile_args = " ".join(profiles)
    pools = min(50, int(np.ceil(max_atoms / 3)))
    array_file = _write(
        work_dir / "screening_array.pbs",
        _header("mot3d_screen", array=True, walltime="01:00:00", ncpus=pools, mem="32gb")
        + f"""python -u -m studies.screen_3d_mot_configurations \\
    --input {INPUT} --profiles {profile_args} --max-atoms {max_atoms} \\
    --num-shards 3 --shard-index "$PBS_ARRAY_INDEX" --npools {pools} \\
    --output-dir "{output_root}/shard_${{PBS_ARRAY_INDEX}}"
""",
    )
    array_job = _submit(array_file)
    merge_file = _write(
        work_dir / "screening_merge.pbs",
        _header("mot3d_screen_merge", walltime="00:15:00", ncpus=1, mem="4gb")
        + f"""python -u -m studies.merge_3d_mot_screening_shards \\
    --input-root {output_root} --output-dir {output_root}/merged
""",
    )
    merge_job = _submit(merge_file, array_job)
    print(f"Screening array: {array_job}")
    print(f"Screening merge: {merge_job}")
    print(f"Final report: {output_root}/merged/merged_screening_scan.json")
    return merge_job


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profiles", nargs="+", default=list(MOT_3D_CONFIGURATIONS))
    parser.add_argument("--max-atoms", type=int, default=MOT_3D_SCREENING_CONFIG["max_atoms"])
    parser.add_argument("--work-dir", default=str(ROOT / "screening" / "pbs"))
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    submit_screening(args.work_dir, args.profiles, args.max_atoms)
