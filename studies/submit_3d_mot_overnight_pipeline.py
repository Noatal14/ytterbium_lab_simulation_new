"""Submit the donut-green and complete five-beam optimization DAG to PBS."""

import argparse
import subprocess
from pathlib import Path

from studies.merge_3d_mot_blue_scan_shards import run_merge
from studies.select_3d_mot_scan_points import run_selection


INPUT = "data/particle_states/after_2d_mot/final_ensemble_s0_1.47"
ROOT = Path("data/validation/mot_3d/optimization")
DONUT = ROOT / "angled_donut"
FIVE = ROOT / "five_beam_gravity"


def _header(name, array=False, walltime="03:00:00", ncpus=200, mem="64gb"):
    array_line = "#PBS -J 0-2\n" if array else ""
    return f"""#!/bin/bash
#PBS -q zeus_combined_q
#PBS -l select=1:ncpus={ncpus}:mem={mem}
#PBS -l walltime={walltime}
{array_line}#PBS -N {name}
#PBS -j oe

cd ~/ytterbium_lab_simulation_new
source ~/venvs/atomsmltr/bin/activate

"""


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def _submit(path, dependency=None):
    command = ["qsub"]
    if dependency:
        command.extend(["-W", f"depend=afterok:{dependency}"])
    command.append(str(path))
    result = subprocess.run(command, check=True, text=True, capture_output=True)
    job_id = result.stdout.strip()
    print(f"Submitted {path.name}: {job_id}")
    return job_id


def submit_pipeline(work_dir):
    work_dir = Path(work_dir)
    donut_gradient_root = DONUT / "gradient_scan_600"
    donut_gradient_merged = donut_gradient_root / "merged"
    run_merge(donut_gradient_root, donut_gradient_merged)
    donut_gradient_selection = donut_gradient_merged / "selected_best.json"
    run_selection(
        donut_gradient_merged / "merged_blue_slower_scan.json",
        donut_gradient_selection,
        top_n=1,
        unique_blue_pairs=False,
    )

    donut_green_root = DONUT / "green_scan_900"
    donut_green_array = _write(
        work_dir / "donut_green_array.pbs",
        _header("mot3d_donut_green", array=True)
        + f"""python -m studies.scan_3d_mot_green_trap \\
    --input {INPUT} \\
    --profile angled_donut \\
    --operating-point-file {donut_gradient_selection} \\
    --max-atoms 900 \\
    --num-shards 3 \\
    --shard-index "$PBS_ARRAY_INDEX" \\
    --npools 200 \\
    --green-s0-values 1 3 5 10 20 \\
    --green-detuning-gamma-values -20 -15 -10 -5 -2 \\
    --output-dir "{donut_green_root}/shard_${{PBS_ARRAY_INDEX}}"
""",
    )
    donut_green_job = _submit(donut_green_array)
    donut_green_finish = _write(
        work_dir / "donut_green_finish.pbs",
        _header("mot3d_donut_finish", walltime="00:30:00", ncpus=1, mem="4gb")
        + f"""python -m studies.merge_3d_mot_blue_scan_shards \\
    --input-root {donut_green_root} \\
    --output-dir {donut_green_root}/merged
python -m studies.select_3d_mot_scan_points \\
    --input {donut_green_root}/merged/merged_green_trap_scan.json \\
    --output {donut_green_root}/merged/selected_best.json
""",
    )
    donut_finish_job = _submit(donut_green_finish, donut_green_job)

    five_blue_root = FIVE / "blue_scan_900"
    five_blue_array = _write(
        work_dir / "five_blue_array.pbs",
        _header("mot3d_five_blue", array=True)
        + f"""python -m studies.scan_3d_mot_blue_slower \\
    --input {INPUT} \\
    --profiles five_beam_gravity \\
    --max-atoms 900 \\
    --num-shards 3 \\
    --shard-index "$PBS_ARRAY_INDEX" \\
    --npools 200 \\
    --s0-values 0.3 0.5 0.8 1.0 1.2 1.5 \\
    --detuning-gamma-values -8 -7 -6 -5 -4 -3 \\
    --output-dir "{five_blue_root}/shard_${{PBS_ARRAY_INDEX}}"
""",
    )
    # Keep the workflow within the agreed three-node/600-core envelope.
    five_blue_job = _submit(five_blue_array, donut_finish_job)
    five_blue_finish = _write(
        work_dir / "five_blue_finish.pbs",
        _header("mot3d_five_blue_finish", walltime="00:30:00", ncpus=1, mem="4gb")
        + f"""python -m studies.merge_3d_mot_blue_scan_shards \\
    --input-root {five_blue_root} \\
    --output-dir {five_blue_root}/merged
python -m studies.select_3d_mot_scan_points \\
    --input {five_blue_root}/merged/merged_blue_slower_scan.json \\
    --output {five_blue_root}/merged/selected_top5.json \\
    --top-n 5 --unique-blue-pairs
""",
    )
    five_blue_finish_job = _submit(five_blue_finish, five_blue_job)

    five_gradient_root = FIVE / "gradient_scan_900"
    five_gradient_array = _write(
        work_dir / "five_gradient_array.pbs",
        _header("mot3d_five_gradient", array=True)
        + f"""python -m studies.scan_3d_mot_gradient \\
    --input {INPUT} \\
    --profile five_beam_gravity \\
    --parameter-points-file {five_blue_root}/merged/selected_top5.json \\
    --gradient-G-cm-values 5 7.5 10 12.5 15 \\
    --max-atoms 900 \\
    --num-shards 3 \\
    --shard-index "$PBS_ARRAY_INDEX" \\
    --npools 200 \\
    --output-dir "{five_gradient_root}/shard_${{PBS_ARRAY_INDEX}}"
""",
    )
    five_gradient_job = _submit(five_gradient_array, five_blue_finish_job)
    five_gradient_finish = _write(
        work_dir / "five_gradient_finish.pbs",
        _header("mot3d_five_grad_finish", walltime="00:30:00", ncpus=1, mem="4gb")
        + f"""python -m studies.merge_3d_mot_blue_scan_shards \\
    --input-root {five_gradient_root} \\
    --output-dir {five_gradient_root}/merged
python -m studies.select_3d_mot_scan_points \\
    --input {five_gradient_root}/merged/merged_blue_slower_scan.json \\
    --output {five_gradient_root}/merged/selected_best.json
""",
    )
    five_gradient_finish_job = _submit(five_gradient_finish, five_gradient_job)

    five_green_root = FIVE / "green_scan_900"
    five_green_array = _write(
        work_dir / "five_green_array.pbs",
        _header("mot3d_five_green", array=True)
        + f"""python -m studies.scan_3d_mot_green_trap \\
    --input {INPUT} \\
    --profile five_beam_gravity \\
    --operating-point-file {five_gradient_root}/merged/selected_best.json \\
    --max-atoms 900 \\
    --num-shards 3 \\
    --shard-index "$PBS_ARRAY_INDEX" \\
    --npools 200 \\
    --green-s0-values 1 3 5 10 20 \\
    --green-detuning-gamma-values -20 -15 -10 -5 -2 \\
    --output-dir "{five_green_root}/shard_${{PBS_ARRAY_INDEX}}"
""",
    )
    five_green_job = _submit(five_green_array, five_gradient_finish_job)
    five_green_finish = _write(
        work_dir / "five_green_finish.pbs",
        _header("mot3d_five_finish", walltime="00:30:00", ncpus=1, mem="4gb")
        + f"""python -m studies.merge_3d_mot_blue_scan_shards \\
    --input-root {five_green_root} \\
    --output-dir {five_green_root}/merged
python -m studies.select_3d_mot_scan_points \\
    --input {five_green_root}/merged/merged_green_trap_scan.json \\
    --output {five_green_root}/merged/selected_best.json
""",
    )
    five_finish_job = _submit(five_green_finish, five_green_job)

    final_output = ROOT / "final_operating_points.json"
    final_job_file = _write(
        work_dir / "final_summary.pbs",
        _header("mot3d_opt_summary", walltime="00:15:00", ncpus=1, mem="4gb")
        + f"""python -m studies.summarize_3d_mot_optimization \\
    --selection angled_donut {donut_green_root}/merged/selected_best.json \\
    --selection five_beam_gravity {five_green_root}/merged/selected_best.json \\
    --output {final_output}
""",
    )
    final_job = _submit(final_job_file, f"{donut_finish_job}:{five_finish_job}")
    print(f"Pipeline final summary job: {final_job}")
    print(f"Final report will be written to: {final_output}")
    return final_job


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--work-dir",
        default=str(ROOT / "overnight_pipeline_pbs"),
        help="Directory for generated PBS files.",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    submit_pipeline(args.work_dir)
