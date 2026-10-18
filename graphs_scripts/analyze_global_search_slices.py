"""Find exact near-constant nuisance-parameter groups in global-search data.

Distance uses each parameter's frozen search bounds, not observed sample range.
Every nuisance parameter must have total group spread <= tolerance. Maximal
cliques enumerate all such groups; no transitive chaining or bin-edge artifacts.
This analyzes geometric coverage, without selecting by capture performance.
"""
import itertools
import json
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree, ConvexHull, QhullError

ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = ROOT/"data/optimization/mot_3d/mot_3d_s0_1p3_search10us_20261012_v1"


def maximal_cliques(adjacency):
    def visit(r, p, x):
        if not p and not x:
            yield sorted(r)
            return
        pivot = max(p | x, key=lambda v: len(p & adjacency[v]))
        for v in sorted(p - adjacency[pivot]):
            yield from visit(r | {v}, p & adjacency[v], x & adjacency[v])
            p.remove(v)
            x.add(v)
    yield from visit(set(), set(adjacency), set())


def analyze(family):
    paths = sorted((CAMPAIGN/"discovery"/family).glob("worker_*/trials/trial_*.json"))
    raw = [(p, json.loads(p.read_text())) for p in paths]
    unique = {}
    for path, row in raw:
        signature = tuple(sorted(row["parameters"].items()))
        unique.setdefault(signature, (path, row))
    rows = list(unique.values())
    keys = list(rows[0][1]["parameters"])
    bounds = rows[0][1]["scientific_design"]["bounds"]
    frozen = dict(bounds["common"], **bounds[family])
    limits = np.array([frozen[k+"_bounds"] for k in keys])
    parameters = np.array([[r["parameters"][k] for k in keys] for _, r in rows])
    normalized = (parameters-limits[:, 0])/(limits[:, 1]-limits[:, 0])
    results = []
    for tolerance in (.05, .10, .15, .20):
        best_any = None
        best_spread = None
        best_informative = None
        for pair in itertools.combinations(range(len(keys)), 2):
            nuisance = [i for i in range(len(keys)) if i not in pair]
            edges = cKDTree(normalized[:, nuisance]).query_pairs(tolerance, p=np.inf)
            adjacency = {i: set() for i in range(len(rows))}
            for a, b in edges:
                adjacency[a].add(b)
                adjacency[b].add(a)
            for group in maximal_cliques(adjacency):
                span = np.ptp(normalized[group][:, pair], axis=0)
                area = 0.
                if len(group) >= 3 and np.all(span > 0):
                    try:
                        area = float(ConvexHull(normalized[group][:, pair]).volume)
                    except QhullError:
                        pass
                record = {"axes": [keys[i] for i in pair], "count": len(group),
                          "axis_span_fraction": span.tolist(), "normalized_hull_area": area,
                          "group_indices": group}
                score = (len(group), min(span), area)
                if best_any is None or score > best_any[0]:
                    best_any = (score, record)
                if min(span) >= .25 and area >= .02:
                    if best_spread is None or score > best_spread[0]:
                        best_spread = (score, record)
                    capture = [rows[i][1]["usable_at_end_fraction"] for i in group]
                    if max(capture)-min(capture) >= .05:
                        if best_informative is None or score > best_informative[0]:
                            best_informative = (score, record)
        for label, best in (("largest_group", best_any), ("largest_with_2d_coverage", best_spread),
                            ("largest_with_2d_coverage_and_5pp_capture_range", best_informative)):
            if best:
                record = dict(best[1])
                group = record.pop("group_indices")
                nuisance = [i for i, k in enumerate(keys) if k not in record["axes"]]
                assert np.all(np.ptp(normalized[group][:, nuisance], axis=0) <= tolerance+1e-12)
                record["parameter_ranges"] = {k: [float(parameters[group, i].min()), float(parameters[group, i].max())]
                                               for i, k in enumerate(keys)}
                record["capture_percent_range"] = [float(min(rows[i][1]["usable_at_end_fraction"] for i in group)*100),
                                                   float(max(rows[i][1]["usable_at_end_fraction"] for i in group)*100)]
                record["source_trials"] = [str(rows[i][0].relative_to(ROOT)) for i in group]
            results.append({"tolerance_fraction": tolerance, "criterion": label, "result": record if best else None})
        print(family, tolerance, "largest", best_any[0], "coverage", best_spread[0] if best_spread else None, flush=True)
    return {"registered_trials": len(raw), "distinct_configurations": len(rows),
            "frozen_bounds": {k: limits[i].tolist() for i, k in enumerate(keys)}, "results": results}


if __name__ == "__main__":
    output = {"method": __doc__, "families": {f: analyze(f) for f in ("angled_donut", "single_pass")}}
    destination = ROOT/"graphs/report_optimization/global_search_slice_analysis.json"
    destination.write_text(json.dumps(output, indent=2)+"\n")
    print(destination)
