"""Submit the buildable angled-sequential geometry and parameter scan DAG."""

import argparse
from pathlib import Path

from studies.submit_3d_mot_overnight_pipeline import INPUT, ROOT, _header, _submit, _write


SEQUENTIAL = ROOT / "angled_sequential"


def submit_pipeline(work_dir):
    work_dir = Path(work_dir)
    suffix = "planar_circular_900"

    geometry_root = SEQUENTIAL / f"geometry_scan_{suffix}"
    geometry_array = _write(
        work_dir / "sequential_geometry_array.pbs",
        _header("mot3d_seq_geometry", array=True, walltime="04:00:00")
        + f"""python -u -m studies.scan_3d_mot_sequential_geometry \\
    --input {INPUT} \\
    --max-atoms 900 --num-shards 3 --shard-index "$PBS_ARRAY_INDEX" \\
    --npools 200 --waists-mm 3 5 10 --exclusions-mm 5 10 \\
    --crossings-mm 10 20 \\
    --output-dir "{geometry_root}/shard_${{PBS_ARRAY_INDEX}}"
""",
    )
    geometry_job = _submit(geometry_array)
    geometry_finish = _write(
        work_dir / "sequential_geometry_finish.pbs",
        _header("mot3d_seq_geofin", ncpus=1, mem="4gb", walltime="00:30:00")
        + f"""python -m studies.merge_3d_mot_blue_scan_shards \\
    --input-root {geometry_root} --output-dir {geometry_root}/merged
python -m studies.select_3d_mot_scan_points \\
    --input {geometry_root}/merged/merged_sequential_geometry_scan.json \\
    --output {geometry_root}/merged/selected_best.json
""",
    )
    geometry_finish_job = _submit(geometry_finish, geometry_job)

    blue_root = SEQUENTIAL / f"blue_scan_{suffix}"
    blue_array = _write(
        work_dir / "sequential_blue_array.pbs",
        _header("mot3d_seq_blue", array=True, walltime="06:00:00")
        + f"""python -u -m studies.scan_3d_mot_blue_slower \\
    --input {INPUT} --profiles angled_sequential \\
    --geometry-point-file {geometry_root}/merged/selected_best.json \\
    --max-atoms 900 --num-shards 3 --shard-index "$PBS_ARRAY_INDEX" \\
    --npools 200 --s0-values 0.3 0.5 0.8 1.0 1.2 1.5 \\
    --detuning-gamma-values -8 -7 -6 -5 -4 -3 -2 -1 \\
    --output-dir "{blue_root}/shard_${{PBS_ARRAY_INDEX}}"
""",
    )
    blue_job = _submit(blue_array, geometry_finish_job)
    blue_finish = _write(
        work_dir / "sequential_blue_finish.pbs",
        _header("mot3d_seq_bfin", ncpus=1, mem="4gb", walltime="00:30:00")
        + f"""python -m studies.merge_3d_mot_blue_scan_shards \\
    --input-root {blue_root} --output-dir {blue_root}/merged
python -m studies.select_3d_mot_scan_points \\
    --input {blue_root}/merged/merged_blue_slower_scan.json \\
    --output {blue_root}/merged/selected_top5.json --top-n 5 --unique-blue-pairs
""",
    )
    blue_finish_job = _submit(blue_finish, blue_job)

    gradient_root = SEQUENTIAL / f"gradient_scan_{suffix}"
    gradient_array = _write(
        work_dir / "sequential_gradient_array.pbs",
        _header("mot3d_seq_gradient", array=True, walltime="05:00:00")
        + f"""python -u -m studies.scan_3d_mot_gradient \\
    --input {INPUT} --profile angled_sequential \\
    --parameter-points-file {blue_root}/merged/selected_top5.json \\
    --gradient-G-cm-values 2.5 5 7.5 10 12.5 15 \\
    --max-atoms 900 --num-shards 3 --shard-index "$PBS_ARRAY_INDEX" \\
    --npools 200 --output-dir "{gradient_root}/shard_${{PBS_ARRAY_INDEX}}"
""",
    )
    gradient_job = _submit(gradient_array, blue_finish_job)
    gradient_finish = _write(
        work_dir / "sequential_gradient_finish.pbs",
        _header("mot3d_seq_gfin", ncpus=1, mem="4gb", walltime="00:30:00")
        + f"""python -m studies.merge_3d_mot_blue_scan_shards \\
    --input-root {gradient_root} --output-dir {gradient_root}/merged
python -m studies.select_3d_mot_scan_points \\
    --input {gradient_root}/merged/merged_blue_slower_scan.json \\
    --output {gradient_root}/merged/selected_best.json
""",
    )
    gradient_finish_job = _submit(gradient_finish, gradient_job)

    green_root = SEQUENTIAL / f"green_scan_{suffix}"
    green_array = _write(
        work_dir / "sequential_green_array.pbs",
        _header("mot3d_seq_green", array=True, walltime="05:00:00")
        + f"""python -u -m studies.scan_3d_mot_green_trap \\
    --input {INPUT} --profile angled_sequential \\
    --operating-point-file {gradient_root}/merged/selected_best.json \\
    --green-s0-values 1 3 5 10 20 30 \\
    --green-detuning-gamma-values -25 -20 -15 -10 -5 -2 \\
    --max-atoms 900 --num-shards 3 --shard-index "$PBS_ARRAY_INDEX" \\
    --npools 200 --output-dir "{green_root}/shard_${{PBS_ARRAY_INDEX}}"
""",
    )
    green_job = _submit(green_array, gradient_finish_job)
    green_finish = _write(
        work_dir / "sequential_green_finish.pbs",
        _header("mot3d_seq_finish", ncpus=1, mem="4gb", walltime="00:30:00")
        + f"""python -m studies.merge_3d_mot_blue_scan_shards \\
    --input-root {green_root} --output-dir {green_root}/merged
python -m studies.select_3d_mot_scan_points \\
    --input {green_root}/merged/merged_green_trap_scan.json \\
    --output {green_root}/merged/selected_best.json
python -m studies.summarize_3d_mot_optimization \\
    --selection angled_sequential {green_root}/merged/selected_best.json \\
    --output {SEQUENTIAL}/final_operating_point_{suffix}.json
""",
    )
    final_job = _submit(green_finish, green_job)
    print(f"Final sequential optimization job: {final_job}")
    print(f"Final report: {SEQUENTIAL}/final_operating_point_{suffix}.json")
    return final_job


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--work-dir", default=str(ROOT / "sequential_planar_circular_pipeline_pbs")
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    submit_pipeline(parse_args().work_dir)
