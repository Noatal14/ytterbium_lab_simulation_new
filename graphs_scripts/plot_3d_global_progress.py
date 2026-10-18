"""Global-search trial outcomes and running best per independent worker.

The x axis is local trial order, not wall-clock or a fictitious shared sequence.
All outcomes are search-sample usable-at-end fractions, not held-out validation.
"""
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = ROOT/"data/optimization/mot_3d/mot_3d_s0_1p3_search10us_20261012_v1"


def main():
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.3), sharey=True, layout="constrained")
    colors = ("#0072B2", "#D55E00", "#009E73")
    provenance = {"definition": __doc__, "families": {}, "source_sha256": {}}
    for ax, family, title in zip(axes, ("angled_donut", "single_pass"), ("Blue shell", "Single pass")):
        total = 0
        summary = []
        for worker, color in enumerate(colors):
            paths = sorted((CAMPAIGN/"discovery"/family/f"worker_{worker}/trials").glob("trial_*.json"))
            rows = []
            for path in paths:
                row = json.loads(path.read_text())
                if row["family"] != family or row["worker_index"] != worker:
                    raise ValueError("Trial identity mismatch")
                if row["input_particle_count"] != 600:
                    raise ValueError("Mixed particle counts")
                provenance["source_sha256"][str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
                rows.append(row)
            rows.sort(key=lambda row: row["trial_number"])
            numbers = [row["trial_number"] for row in rows]
            if numbers != list(range(len(rows))):
                raise ValueError(f"Non-contiguous trials: {family}, worker {worker}")
            x = np.arange(1, len(rows)+1)
            values = 100*np.array([row["usable_at_end_fraction"] for row in rows])
            running = np.maximum.accumulate(values)
            ax.scatter(x, values, color=color, s=13, alpha=.28, edgecolors="none", zorder=2)
            ax.step(x, running, where="post", color=color, linewidth=2, label=f"Worker {worker} · best {running[-1]:.1f}%", zorder=3)
            summary.append({"worker": worker, "trials": len(rows), "best_capture_percent": float(running[-1])})
            total += len(rows)
        provenance["families"][family] = summary
        ax.set(title=f"{title} · {total} tested configurations", xlabel="Configurations evaluated by each worker",
               ylim=(0, 105), xlim=(1, max(r["trials"] for r in summary)))
        ax.grid(alpha=.2)
        handles, labels = ax.get_legend_handles_labels()
        handles.append(Line2D([], [], marker="o", linestyle="none", color="#666666", alpha=.4, markersize=4))
        ax.legend(handles, labels+["Individual trial result"], fontsize=8, loc="lower right")
    axes[0].set_ylabel("3D capture at simulation end among 2D survivors (%)")
    fig.suptitle("3D-MOT global-search progress", fontsize=17)
    fig.supxlabel("Faint points: trial results. Step curves: best result found so far by each worker.\n"
                  "600 atoms per trial · search-sample results, not independent validation · local trial order, not elapsed time.", fontsize=9)
    output = ROOT/"graphs/report_optimization"
    output.mkdir(parents=True, exist_ok=True)
    for extension in ("png", "pdf"):
        fig.savefig(output/f"06_3d_global_search_progress.{extension}", dpi=220, bbox_inches="tight")
    plt.close(fig)
    (output/"global_search_progress_values.json").write_text(json.dumps(provenance, indent=2)+"\n")


if __name__ == "__main__":
    main()
