"""Select reproducible candidate points from a merged 3D-MOT scan report."""

import argparse
import json
from pathlib import Path


def merged_rank_key(record):
    speed = record.get("weighted_mean_of_shard_medians_minimum_speed_inside_m_s")
    return (
        record["capture_eligible_ever_count"],
        record["peak_capture_eligible_count"],
        record["minimum_residence_met_count"],
        record["slow_inside_count"],
        -float(speed) if speed is not None else float("-inf"),
        record["entered_capture_region_count"],
    )


def select_points(report, top_n=1, unique_blue_pairs=False):
    records = list(report["records"])
    if unique_blue_pairs:
        best_by_pair = {}
        for record in records:
            key = (record["s0"], record["detuning_gamma"])
            if key not in best_by_pair or merged_rank_key(record) > merged_rank_key(
                best_by_pair[key]
            ):
                best_by_pair[key] = record
        records = list(best_by_pair.values())
    ranked = sorted(records, key=merged_rank_key, reverse=True)
    if top_n <= 0 or top_n > len(ranked):
        raise ValueError("top_n must select at least one available record.")
    return ranked[:top_n]


def run_selection(input_path, output_path, top_n=1, unique_blue_pairs=False):
    input_path = Path(input_path)
    report = json.loads(input_path.read_text())
    selected = select_points(report, top_n, unique_blue_pairs)
    output = {
        "source_report": str(input_path),
        "ranking_priority": [
            "capture_eligible_ever_count (higher)",
            "peak_capture_eligible_count (higher)",
            "minimum_residence_met_count (higher)",
            "slow_inside_count (higher)",
            "weighted mean of shard median minimum speed (lower)",
            "entered_capture_region_count (higher)",
        ],
        "selected_points": selected,
        "best_point": selected[0],
    }
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2) + "\n")
    print(f"Saved selected points: {output_path}")
    for index, point in enumerate(selected, start=1):
        print(
            f"{index}: s0={point['s0']:g}, detuning={point['detuning_gamma']:g} Gamma, "
            f"gradient={point.get('gradient_G_cm', 'n/a')}, "
            f"eligible={point['capture_eligible_ever_count']}"
        )
    return output


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--top-n", type=int, default=1)
    parser.add_argument("--unique-blue-pairs", action="store_true")
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    run_selection(args.input, args.output, args.top_n, args.unique_blue_pairs)
