"""Submit force-corrected five-beam blue, gradient, and green scans to PBS."""

import argparse
from pathlib import Path

from studies.submit_3d_mot_overnight_pipeline import (
    DONUT,
    FIVE,
    INPUT,
    ROOT,
    _header,
    _submit,
    _write,
)


def submit_pipeline(work_dir):
    work_dir = Path(work_dir)
    suffix = "force_corrected_900"

    blue_root = FIVE / f"blue_scan_{suffix}"
    blue_array = _write(
        work_dir / "five_corrected_blue_array.pbs",
        _header("mot3d_five2_blue", array=True, walltime="05:00:00")
        + f"""python -u -m studies.scan_3d_mot_blue_slower \\
    --input {INPUT} \\
    --profiles five_beam_gravity \\
    --max-atoms 900 \\
    --num-shards 3 \\
    --shard-index "$PBS_ARRAY_INDEX" \\
    --npools 200 \\
    --s0-values 0.3 0.5 0.8 1.0 1.2 1.5 \\
    --detuning-gamma-values -8 -7 -6 -5 -4 -3 -2 -1 \\
    --output-dir "{blue_root}/shard_${{PBS_ARRAY_INDEX}}"
""",
    )
    blue_job = _submit(blue_array)
    blue_finish = _write(
        work_dir / "five_corrected_blue_finish.pbs",
        _header("mot3d_five2_bfin", walltime="00:30:00", ncpus=1, mem="4gb")
        + f"""python -m studies.merge_3d_mot_blue_scan_shards \\
    --input-root {blue_root} --output-dir {blue_root}/merged
python -m studies.select_3d_mot_scan_points \\
    --input {blue_root}/merged/merged_blue_slower_scan.json \\
    --output {blue_root}/merged/selected_top5.json \\
    --top-n 5 --unique-blue-pairs
""",
    )
    blue_finish_job = _submit(blue_finish, blue_job)

    gradient_root = FIVE / f"gradient_scan_{suffix}"
    gradient_array = _write(
        work_dir / "five_corrected_gradient_array.pbs",
        _header("mot3d_five2_grad", array=True, walltime="04:00:00")
        + f"""python -u -m studies.scan_3d_mot_gradient \\
    --input {INPUT} \\
    --profile five_beam_gravity \\
    --parameter-points-file {blue_root}/merged/selected_top5.json \\
    --gradient-G-cm-values 2.5 5 7.5 10 12.5 15 \\
    --max-atoms 900 \\
    --num-shards 3 \\
    --shard-index "$PBS_ARRAY_INDEX" \\
    --npools 200 \\
    --output-dir "{gradient_root}/shard_${{PBS_ARRAY_INDEX}}"
""",
    )
    gradient_job = _submit(gradient_array, blue_finish_job)
    gradient_finish = _write(
        work_dir / "five_corrected_gradient_finish.pbs",
        _header("mot3d_five2_gfin", walltime="00:30:00", ncpus=1, mem="4gb")
        + f"""python -m studies.merge_3d_mot_blue_scan_shards \\
    --input-root {gradient_root} --output-dir {gradient_root}/merged
python -m studies.select_3d_mot_scan_points \\
    --input {gradient_root}/merged/merged_blue_slower_scan.json \\
    --output {gradient_root}/merged/selected_best.json
""",
    )
    gradient_finish_job = _submit(gradient_finish, gradient_job)

    green_root = FIVE / f"green_scan_{suffix}"
    green_array = _write(
        work_dir / "five_corrected_green_array.pbs",
        _header("mot3d_five2_green", array=True, walltime="04:00:00")
        + f"""python -u -m studies.scan_3d_mot_green_trap \\
    --input {INPUT} \\
    --profile five_beam_gravity \\
    --operating-point-file {gradient_root}/merged/selected_best.json \\
    --max-atoms 900 \\
    --num-shards 3 \\
    --shard-index "$PBS_ARRAY_INDEX" \\
    --npools 200 \\
    --green-s0-values 1 3 5 10 20 \\
    --green-detuning-gamma-values -20 -15 -10 -5 -2 \\
    --output-dir "{green_root}/shard_${{PBS_ARRAY_INDEX}}"
""",
    )
    green_job = _submit(green_array, gradient_finish_job)
    green_finish = _write(
        work_dir / "five_corrected_green_finish.pbs",
        _header("mot3d_five2_fin", walltime="00:30:00", ncpus=1, mem="4gb")
        + f"""python -m studies.merge_3d_mot_blue_scan_shards \\
    --input-root {green_root} --output-dir {green_root}/merged
python -m studies.select_3d_mot_scan_points \\
    --input {green_root}/merged/merged_green_trap_scan.json \\
    --output {green_root}/merged/selected_best.json
""",
    )
    green_finish_job = _submit(green_finish, green_job)

    donut_selection = DONUT / "green_scan_900/merged/selected_best.json"
    final_job_file = _write(
        work_dir / "five_corrected_final_summary.pbs",
        _header("mot3d_five2_sum", walltime="00:15:00", ncpus=1, mem="4gb")
        + f"""python -m studies.summarize_3d_mot_optimization \\
    --selection angled_donut {donut_selection} \\
    --selection five_beam_gravity {green_root}/merged/selected_best.json \\
    --output {ROOT}/final_operating_points.json
""",
    )
    final_job = _submit(final_job_file, green_finish_job)
    print(f"Force-corrected five-beam final summary job: {final_job}")
    print(f"Final report: {ROOT}/final_operating_points.json")
    return final_job


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--work-dir", default=str(ROOT / "five_beam_force_corrected_pipeline_pbs")
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    submit_pipeline(args.work_dir)
