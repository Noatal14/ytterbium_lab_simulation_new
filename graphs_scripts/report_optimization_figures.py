"""Reproducible report figures from frozen campaign artifacts (no simulations).

Run from any directory: MPLBACKEND=Agg python3 graphs_scripts/report_optimization_figures.py
Data paths may be overridden with --data-root. The optimization-map background
is a smoothed thin-plate spline, clipped to the measured value range. It is
illustrative, especially outside the sampled convex hull, not a prediction.
Finalist seed scatter is descriptive, not a CI.
"""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.transforms import Bbox
import numpy as np
from scipy.interpolate import RBFInterpolator

REPO = Path(__file__).resolve().parents[1]
C2 = "optimization/mot_2d/corrected_zeeman_s0_1p3_20261006"
C3 = "optimization/mot_3d/mot_3d_s0_1p3_search10us_20261012_v1"
FAMILIES = ("angled_donut", "single_pass")
NAMES = {"angled_donut": "Angled donut", "single_pass": "Single pass"}
LABELS = {"green_s0": "Green saturation parameter", "green_detuning_gamma": "Green detuning",
          "green_waist_m": "Green beam waist", "blue_s0": "Blue saturation parameter",
          "blue_waist_m": "Blue beam waist", "magnetic_gradient_G_cm": "Magnetic gradient",
          "blue_detuning_gamma": "Blue detuning", "core_shell_split_radius_m": "Core / shell radius",
          "blue_detuning_anchor_gamma": "Blue detuning anchor", "blue_crossing_angle_deg": "Crossing angle",
          "blue_crossing_z_offset_m": "Crossing z-offset"}


class Figures:
    def __init__(self, data, output):
        self.data, self.output, self.sources = data, output, {}
        output.mkdir(parents=True, exist_ok=True)

    def track(self, path):
        self.sources[str(path.relative_to(self.data))] = hashlib.sha256(path.read_bytes()).hexdigest()
        return path

    def read(self, path):
        return json.loads(self.track(path).read_text())

    def save(self, fig, name):
        fig.savefig(self.output / (name + ".png"), dpi=220, bbox_inches="tight")
        fig.savefig(self.output / (name + ".pdf"), bbox_inches="tight")
        plt.close(fig)

    def save_panel(self, fig, axes, name, caption):
        """Export a standalone vector panel, including its labels/colorbar."""
        fig.canvas.draw()
        # Freeze layout while temporarily hiding unrelated panels and headings.
        engine = fig.get_layout_engine()
        fig.set_layout_engine(None)
        visibility = [(artist, artist.get_visible()) for artist in [*fig.axes, *fig.texts]]
        for artist, _ in visibility:
            artist.set_visible(artist in axes)
        renderer = fig.canvas.get_renderer()
        bounds = Bbox.union([axis.get_tightbbox(renderer) for axis in axes]).transformed(fig.dpi_scale_trans.inverted())
        width, height = fig.get_size_inches()
        text = fig.text(bounds.x0/width, (bounds.y0-.15)/height, caption, va="top", fontsize=9)
        fig.canvas.draw()
        text_bounds = text.get_window_extent(fig.canvas.get_renderer()).transformed(fig.dpi_scale_trans.inverted())
        bounds = Bbox.union([bounds, text_bounds]).padded(.12)
        for extension in ("png", "pdf"):
            fig.savefig(self.output/f"{name}.{extension}", dpi=220, bbox_inches=bounds)
        text.remove()
        for artist, visible in visibility:
            artist.set_visible(visible)
        fig.set_layout_engine(engine)

    def map_2d(self):
        winner = self.read(self.data / C2 / "sensitivity_summary.json")["s0_1p300000"]["reference"]
        production = self.read(self.data / C2 / "production/s0_1p300000/summary.json")["replicate_statistics"]
        rate = 100*production["mean_conditional_efficiency"]
        low, high = 100*np.asarray(production["conditional_95_ci"])
        selected_label = f"Selected configuration: {rate:.3f}%\nProduction 95% CI: [{low:.3f}, {high:.3f}]%"
        fig = plt.figure(figsize=(16, 8.6))
        ax = fig.add_axes([.06, .25, .41, .60])
        for stage, title, sample in (("screen", "Global search", "10,000"),):
            rows = [self.read(p) for p in sorted((self.data / C2 / stage).glob("**/trial_*.json"))]
            if not rows:
                raise ValueError(f"No {stage} trials")
            grouped = {}
            for row in rows:
                p = row["parameters"]
                key = (p["detuning_gamma"], p["magnet_radius"])
                grouped.setdefault(key, []).append(row["statistics"]["mean_conditional_efficiency"])
            # Repeated deterministic trial records are not independent evidence.
            for values in grouped.values():
                if not np.allclose(values, values[0], rtol=0, atol=1e-12):
                    raise ValueError("Repeated coordinates have different results; explicit pooling is required")
            x = [k[0] for k in grouped]
            y = [1000*k[1] for k in grouped]
            z = [100*v[0] for v in grouped.values()]
            # Smooth visual guide only: normalize coordinate scales and clip to
            # the observed range so extrapolation cannot invent higher yields.
            x, y, z = np.asarray(x), np.asarray(y), np.asarray(z)
            xn, yn = (x-x.min())/np.ptp(x), (y-y.min())/np.ptp(y)
            gx, gy = np.meshgrid(np.linspace(-.04, 1.04, 350), np.linspace(-.04, 1.04, 350))
            interpolator = RBFInterpolator(np.column_stack((xn, yn)), z,
                                          kernel="thin_plate_spline", smoothing=.01)
            filled = interpolator(np.column_stack((gx.ravel(), gy.ravel()))).reshape(gx.shape)
            filled = np.clip(filled, z.min(), z.max())
            background = ax.contourf(x.min()+gx*np.ptp(x), y.min()+gy*np.ptp(y), filled,
                                     levels=np.linspace(z.min(), z.max(), 80), cmap="viridis")
            colorbar_ax = fig.add_axes([.49, .25, .014, .60])
            colorbar = fig.colorbar(background, cax=colorbar_ax,
                                   label="2D-MOT capture among Zeeman survivors (%)")
            from matplotlib.ticker import MaxNLocator, FormatStrFormatter
            colorbar.locator = MaxNLocator(nbins=7)
            colorbar.formatter = FormatStrFormatter("%.1f")
            colorbar.update_ticks()
            ax.scatter(x, y, color="#ee3035", s=48, edgecolors="white", linewidths=.9, zorder=3)
            map_points = (x, y, z)
            ax.scatter([winner["detuning_gamma"]], [1000*winner["magnet_radius"]], marker="*", s=190,
                       c="#d95f02", edgecolors="black", linewidths=.6, label=selected_label, zorder=4)
            ax.set(xlabel=r"Detuning $\Delta/\Gamma$", ylabel="Magnet radius (mm)",
                   title="")
            ax.set_xlim(x.min()-.04*np.ptp(x), x.max()+.04*np.ptp(x))
            ax.set_ylim(y.min()-.04*np.ptp(y), y.max()+.04*np.ptp(y))
            ax.legend(loc="lower left", fontsize=9, framealpha=.92)
            ax.tick_params(labelsize=12)
            ax.xaxis.label.set_size(14)
            ax.yaxis.label.set_size(14)
        refined = [self.read(p) for p in sorted((self.data / C2 / "refine").glob("**/trial_*.json"))]
        unique = {}
        for row in refined:
            params = row["parameters"]
            key = (params["detuning_gamma"], params["magnet_radius"])
            if key in unique and row["statistics"] != unique[key]["statistics"]:
                raise ValueError("Repeated refined configurations have inconsistent statistics")
            unique[key] = row
        if not unique:
            raise ValueError("No refined configurations")
        bars = fig.add_axes([.62, .25, .36, .60])
        labels = []
        for i, (key, row) in enumerate(sorted(unique.items())):
            stats = row["statistics"]
            mean = 100*stats["mean_conditional_efficiency"]
            lo, hi = 100*np.asarray(stats["conditional_95_ci"])
            chosen = key == (winner["detuning_gamma"], winner["magnet_radius"])
            bars.bar(i, mean, yerr=[[mean-lo], [hi-mean]], capsize=3, width=.7,
                     color="#d95f02" if chosen else "#0072B2")
            labels.append(f"{key[0]:.4f}\n{1000*key[1]:.3f}" + (" ★" if chosen else ""))
        bars.set(xticks=range(len(labels)), xticklabels=labels, ylim=(0, 3.4),
                 ylabel="2D-MOT capture (%)", xlabel=r"Configuration: $\Delta/\Gamma$ / radius (mm)")
        bars.tick_params(axis="x", labelrotation=65, labelsize=9)
        bars.grid(axis="y", alpha=.2)
        bars.set_axisbelow(True)
        fig.suptitle(r"2D-MOT optimization · $s_0=1.3$", fontsize=19, y=.97)
        fig.text(.265, .89, f"Global search · {len(grouped)} configurations\n{sample} trajectories per point",
                 ha="center", fontsize=11, color="#444444")
        fig.text(.80, .89, f"Refined search · {len(unique)} configurations\n50,000 trajectories per configuration",
                 ha="center", fontsize=11, color="#444444")
        fig.text(.06, .065,
                 "Capture among Zeeman survivors. Background: illustrative interpolation; point labels: measured percentages. Error bars: 95% CI.\n"
                 "★ Selected by the highest lower 95% confidence bound in independent confirmation, not the highest search mean.",
                 fontsize=9, linespacing=1.5, color="#444444")
        self.label_map(ax, *map_points)
        self.save_panel(fig, [ax, colorbar_ax], "01a_2d_global_search_map",
                        r"$s_0=1.3$ · capture among Zeeman survivors · background: illustrative interpolation")
        self.save_panel(fig, [bars], "01b_2d_refined_search",
                        "Capture among Zeeman survivors · error bars: 95% CI\n"
                        "★ Selected by the highest lower 95% confidence bound in independent confirmation.")
        self.save(fig, "01_2d_optimization_map")

    @staticmethod
    def label_map(ax, x, y, values):
        """Place compact measured-value labels with collision-aware offsets."""
        ax.figure.canvas.draw()
        renderer = ax.figure.canvas.get_renderer()
        occupied = []
        offsets = [(dx, dy) for radius in (6, 16, 28, 42, 58)
                   for dx, dy in ((radius, radius), (-radius, radius), (radius, -radius),
                                  (-radius, -radius), (0, radius), (radius, 0), (-radius, 0), (0, -radius))]
        for px, py, value in zip(x, y, values):
            label = ax.annotate(f"{value:.2f}", (px, py), xytext=(6, 6), textcoords="offset points",
                                fontsize=9, ha="center", va="center", zorder=5,
                                bbox=dict(boxstyle="round,pad=.16", fc="white", ec="#555555", alpha=.85, lw=.4),
                                arrowprops=dict(arrowstyle="-", lw=.4, color="#555555"))
            label.set_in_layout(False)
            for offset in offsets:
                label.set_position(offset)
                label.update_positions(renderer)
                label.update_bbox_position_size(renderer)
                box = label.get_bbox_patch().get_window_extent(renderer).expanded(1.08, 1.15)
                if ax.bbox.contains(box.x0, box.y0) and ax.bbox.contains(box.x1, box.y1) and not any(box.overlaps(other) for other in occupied):
                    break
            occupied.append(box)

    def sensitivity(self):
        exported = {}
        fig, axes = plt.subplots(2, 1, figsize=(13, 10), layout="constrained")
        for ax, family in zip(axes, FAMILIES):
            summary = self.read(self.data / C3 / "closure" / family / "merged/refinement_summary.json")
            rows = summary["ranked_candidates"]
            exported[family] = [{k: row[k] for k in ("candidate_id", "closure_role", "parameters",
                                "mean_usable_fraction", "bootstrap_95_ci")} for row in rows]
            baseline = next(r for r in rows if r["closure_role"] == "focused_refinement_leader")
            params = list(dict.fromkeys(r["closure_role"].rsplit("_", 1)[0] for r in rows
                                       if r is not baseline))
            params.sort(key=lambda k: list(LABELS).index(k))
            for i, param in enumerate(params):
                for direction, offset, color in (("down", -.19, "#0072B2"), ("up", .19, "#D55E00")):
                    match = [r for r in rows if r["closure_role"] == param + "_" + direction]
                    if not match:
                        continue
                    row = match[0]
                    mean = 100*row["mean_usable_fraction"]
                    lo, hi = 100*np.asarray(row["bootstrap_95_ci"])
                    ax.bar(i+offset, mean, width=.36,
                           yerr=[[max(0, mean-lo)], [max(0, hi-mean)]],
                           color=color, capsize=3, error_kw={"linewidth": .9},
                           label=direction.capitalize() if i == 0 else None)
            ax.axhline(100*baseline["mean_usable_fraction"], color="#333333", linestyle="--", linewidth=1,
                       label="Nominal configuration")
            ticks = []
            for param in params:
                factor = 1000 if param.endswith("_m") else 1
                unit = " mm" if factor == 1000 else (" G/cm" if param == "magnetic_gradient_G_cm" else
                        "°" if param.endswith("_deg") else " Γ" if "gamma" in param else "")
                values = []
                for role in (param+"_down", "focused_refinement_leader", param+"_up"):
                    matches = [r for r in rows if r["closure_role"] == role]
                    values.append(f"{factor*matches[0]['parameters'][param]:.4g}" if matches else "—")
                ticks.append(LABELS[param]+"\n"+" / ".join(values)+unit)
            ax.set(xticks=range(len(params)), xticklabels=ticks,
                   ylabel="3D capture among 2D survivors (%)",
                   title="Blue shell" if family == "angled_donut" else "Single pass",
                   ylim=(0, 108 if family == "angled_donut" else 35))
            ax.tick_params(axis="x", labelrotation=25, labelsize=8)
            ax.legend(fontsize=8, loc="upper right", ncol=3)
            ax.grid(axis="y", alpha=.2)
            ax.set_axisbelow(True)
        fig.suptitle("3D-MOT local sensitivity", fontsize=17)
        fig.supxlabel("Label values: down / nominal / up; missing directions were not tested.\n"
                      "Error bars: marginal 95% hierarchical-bootstrap intervals. Vertical axes start at zero; scales differ between panels.\n"
                      "3,000 input atoms × 3 recoil seeds per point.", fontsize=9)
        self.save(fig, "02_3d_sensitivity")
        (self.output / "sensitivity_values.json").write_text(json.dumps(exported, indent=2)+"\n")

    def finalists(self):
        fig, axes = plt.subplots(1, 2, figsize=(11, 5.3), layout="constrained")
        snapshot = {}
        for ax, family in zip(axes, FAMILIES):
            selection = self.read(self.data / C3 / "selection/finalists" / (family+".json"))
            labels = []
            for i, candidate in enumerate(selection["candidates"]):
                cid = candidate["candidate_id"]
                rows = [self.read(p) for p in sorted((self.data / C3 / "finalist_selection" / family).glob(f"finalist_*/{cid}_seed_*.json"))]
                if len({r['recoil_seed'] for r in rows}) != len(rows):
                    raise ValueError("Duplicate finalist seed")
                values = [100*r["usable_at_end_count"]/r["input_particle_count"] for r in rows]
                snapshot[cid] = {"completed_seeds": len(rows), "seed_capture_percent": values,
                                 "parameters": candidate["parameters"]}
                labels.append(f"Finalist {i+1}\n{len(rows)}/3 seeds")
                if values:
                    ax.scatter(i+np.linspace(-.09, .09, len(values)), values, s=46, color="#0072B2", zorder=3)
                    ax.scatter(i, np.mean(values), marker="_", s=450, linewidths=2.5, color="#D55E00", zorder=4)
                else:
                    ax.text(i, .08, "Pending", transform=ax.get_xaxis_transform(), ha="center", color="#666666")
            ax.set(xticks=range(3), xticklabels=labels, xlim=(-.5, 2.5),
                   ylabel="3D capture among 2D survivors (%)", title=NAMES[family])
            ax.ticklabel_format(axis="y", useOffset=False)
            ax.grid(axis="y", alpha=.2)
        fig.suptitle("3D-MOT finalists · provisional snapshot", fontsize=17)
        fig.supxlabel("Dots: completed recoil seeds; orange line: available-seed mean (not a confidence interval).\n"
                      "16,883 input atoms per seed · time step 10 µs. Incomplete candidates are not ranked.\n"
                      "These are local input-ensemble capture fractions, not fractions of all atoms leaving the oven.", fontsize=9)
        (self.output / "finalist_snapshot.json").write_text(json.dumps(snapshot, indent=2)+"\n")
        self.save(fig, "03_3d_finalists")

    def velocities(self):
        root = self.data / "particle_states/after_2d_mot/final_ensemble_s0_1.3"
        paths = sorted(root.glob("mot_2d_survivors_zeeman_seed30[123]*_mot_seed43*.npy"))
        if len(paths) != 20:
            raise ValueError(f"Expected 20 production ensembles, found {len(paths)}")
        arrays = []
        for path in paths:
            metadata = self.read(path.with_suffix(".json"))
            if metadata["state_layout"] != ["x_m", "y_m", "z_m", "vx_m_s", "vy_m_s", "vz_m_s"]:
                raise ValueError("Unsupported state layout")
            self.track(path)
            if self.sources[str(path.relative_to(self.data))] != metadata["output_sha256"]:
                raise ValueError("Survivor array hash mismatch")
            arrays.append(np.load(path, allow_pickle=False))
        states = np.concatenate(arrays)
        if states.ndim != 2 or states.shape[1] != 6 or not np.isfinite(states).all():
            raise ValueError("Invalid state array")
        vx, vy, vz = states[:, 3:].T
        vt = np.hypot(vx, vy)
        fig, axes = plt.subplots(1, 3, figsize=(13, 4.5), layout="constrained")
        axes[0].hist(vz, bins=55, density=True, color="#0072B2", alpha=.85)
        axes[0].set(xlabel=r"Longitudinal velocity $v_z$ (m/s)", ylabel="Probability density (s/m)", title="Longitudinal distribution")
        for v, label, color in ((vx, r"$v_x$", "#0072B2"), (vy, r"$v_y$", "#D55E00")):
            axes[1].hist(v, bins=55, histtype="step", density=True, linewidth=1.6, label=label, color=color)
        axes[1].set(xlabel="Transverse velocity (m/s)", ylabel="Probability density (s/m)", title="Transverse components")
        axes[1].legend()
        h = axes[2].hist2d(vz, vt, bins=45, cmap="viridis", cmin=1)
        velocity_colorbar = fig.colorbar(h[3], ax=axes[2], label="Atoms per bin", shrink=.85)
        axes[2].set(xlabel=r"$v_z$ (m/s)", ylabel=r"$\sqrt{v_x^2+v_y^2}$ (m/s)", title="Longitudinal / transverse correlation")
        fig.suptitle("Velocity distribution after the optimized 2D MOT", fontsize=17)
        fig.supxlabel(f"{len(states):,} surviving atoms\n"
                      r"$s_0=1.3$, $\Delta/\Gamma=-0.919661$, magnet radius 46.7641 mm.", fontsize=9)
        stats = {k: {"mean_m_s": float(np.mean(v)), "std_m_s": float(np.std(v)),
                     "p10_median_p90_m_s": np.quantile(v, [.1, .5, .9]).tolist()}
                 for k, v in (("vx", vx), ("vy", vy), ("vz", vz), ("v_transverse", vt))}
        stats["atom_count"] = len(states)
        (self.output / "velocity_statistics.json").write_text(json.dumps(stats, indent=2)+"\n")
        caption = (f"{len(states):,} surviving atoms\n" +
                   r"$s_0=1.3$, $\Delta/\Gamma=-0.919661$, magnet radius 46.7641 mm.")
        for i, suffix in enumerate(("longitudinal", "transverse", "correlation")):
            panel_axes = [axes[i]] + ([velocity_colorbar.ax] if i == 2 else [])
            self.save_panel(fig, panel_axes, f"04{chr(97+i)}_2d_velocity_{suffix}", caption)
        self.save(fig, "04_2d_output_velocities")

    def run(self):
        self.map_2d()
        self.sensitivity()
        self.finalists()
        self.velocities()
        (self.output / "provenance.json").write_text(json.dumps({
            "generated_utc": datetime.now(timezone.utc).isoformat(),
            "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "source_sha256": self.sources,
            "notes": "Finalist snapshot is incomplete; sensitivity uses marginal bootstrap intervals."}, indent=2)+"\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=REPO / "data")
    parser.add_argument("--output-dir", type=Path, default=REPO / "graphs/report_optimization")
    args = parser.parse_args()
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "pdf.fonttype": 42, "savefig.facecolor": "white"})
    Figures(args.data_root.resolve(), args.output_dir.resolve()).run()


if __name__ == "__main__":
    main()
