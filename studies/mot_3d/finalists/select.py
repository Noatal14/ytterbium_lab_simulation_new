"""Select the three closure leaders per family for full-existing-data evaluation."""

import argparse
import json
from pathlib import Path

from studies.mot_3d.discovery.optimize import build_profile_from_parameters


def select(family, closure_summary, count=3):
    summary = json.loads(Path(closure_summary).read_text())
    if summary["family"] != family:
        raise ValueError("Closure summary and requested family disagree.")
    ranked = summary["ranked_candidates"]
    if len(ranked) < count:
        raise ValueError(f"Need {count} closure candidates; found {len(ranked)}.")
    candidates = []
    for finalist_rank, source in enumerate(ranked[:count], start=1):
        profile, parameters, derived = build_profile_from_parameters(
            family, source["parameters"]
        )
        candidates.append(
            {
                "candidate_id": f"{family}_finalist_{finalist_rank:02d}",
                "finalist_rank_from_closure": finalist_rank,
                "source_candidate_id": source["candidate_id"],
                "source_closure_role": source.get("closure_role"),
                "source_closure_fraction": source["mean_usable_fraction"],
                "source_closure_ci": source.get(
                    "simultaneous_95_ci", source["bootstrap_95_ci"]
                ),
                "parameters": parameters,
                "derived_parameters": derived,
                "resolved_profile": profile,
            }
        )
    return {
        "kind": "mot_3d_finalist_selection",
        "family": family,
        "candidate_count": len(candidates),
        "selection_rule": "top three closure candidates ranked by the lower endpoint of the simultaneous 95% confidence interval",
        "candidates": candidates,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", choices=("angled_donut", "single_pass"), required=True)
    parser.add_argument("--closure-summary", required=True)
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    payload = select(args.family, args.closure_summary, args.count)
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"Saved {len(payload['candidates'])} finalists: {destination}")


if __name__ == "__main__":
    main()
