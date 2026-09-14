"""Plot the study-only finite blue-gate geometries in the lab x-z plane."""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import Circle, Rectangle

from config import MOT_3D_SINGLE_PASS_GATE_FOLLOWUP_CONFIG


OUTPUT = Path("graphs/mot_3d_single_pass_gate_followup/gate_geometries.png")
BLUE = "#1769aa"
GREEN = "#2ca02c"
ATOM = "#222222"


def _beam_pair(axis, crossing_z_mm, z_min_mm, z_max_mm, color=BLUE, alpha=1.0):
    """Draw the two angled -z-propagating xz beams over a lab-z interval."""
    slope = np.tan(np.deg2rad(30.0))
    for sign in (-1.0, 1.0):
        z = np.array([z_min_mm, z_max_mm])
        x = sign * slope * (z - crossing_z_mm)
        axis.plot(z, x, color=color, linewidth=3.0, alpha=alpha)
        start_z = z_max_mm - 0.20 * (z_max_mm - z_min_mm)
        end_z = z_max_mm - 0.43 * (z_max_mm - z_min_mm)
        start_x = sign * slope * (start_z - crossing_z_mm)
        end_x = sign * slope * (end_z - crossing_z_mm)
        axis.annotate(
            "",
            xy=(end_z, end_x),
            xytext=(start_z, start_x),
            arrowprops=dict(arrowstyle="-|>", color=color, lw=2.4),
        )


def _opposite_arrows(axis, crossing_z_mm, z_min_mm, z_max_mm, color=BLUE):
    """Add +z propagation arrows on the same two xz axes."""
    slope = np.tan(np.deg2rad(30.0))
    for sign in (-1.0, 1.0):
        start_z = z_min_mm + 0.20 * (z_max_mm - z_min_mm)
        end_z = z_min_mm + 0.43 * (z_max_mm - z_min_mm)
        axis.annotate(
            "",
            xy=(end_z, sign * slope * (end_z - crossing_z_mm)),
            xytext=(start_z, sign * slope * (start_z - crossing_z_mm)),
            arrowprops=dict(arrowstyle="-|>", color=color, lw=2.4),
        )


def _green_xz_axes(axis):
    """Show the two bidirectional green xz axes inside the protected core."""
    slope = np.tan(np.deg2rad(30.0))
    for sign in (-1.0, 1.0):
        z = np.array([-9.0, 9.0])
        x = sign * slope * z
        axis.plot(z, x, color=GREEN, linewidth=1.8, alpha=0.8, zorder=4)
        for start_z, end_z in ((-6.5, -3.5), (6.5, 3.5)):
            axis.annotate(
                "",
                xy=(end_z, sign * slope * end_z),
                xytext=(start_z, sign * slope * start_z),
                arrowprops=dict(arrowstyle="-|>", color=GREEN, lw=1.5),
            )


def _common(axis, title):
    axis.axhline(0.0, color=ATOM, linewidth=1.2, alpha=0.65)
    axis.annotate(
        "incoming atoms (+z)",
        xy=(-7, -17),
        xytext=(-44, -17),
        arrowprops=dict(arrowstyle="-|>", color=ATOM, lw=2.0),
        ha="left",
        va="center",
        color=ATOM,
    )
    axis.scatter([0], [0], marker="*", s=150, color="black", zorder=8)
    axis.add_patch(Circle((0, 0), 10, fill=False, color=GREEN, linewidth=2.4))
    _green_xz_axes(axis)
    axis.text(1.5, 8.2, "556-nm core\n(6 green beams)", color=GREEN, fontsize=9)
    axis.set(xlim=(-47, 58), ylim=(-31, 31), xlabel="z relative to MOT center [mm]", ylabel="x [mm]", title=title)
    axis.set_aspect("equal", adjustable="box")
    axis.grid(alpha=0.18)


def plot_geometries(output_path=OUTPUT):
    settings = MOT_3D_SINGLE_PASS_GATE_FOLLOWUP_CONFIG
    fig, axes = plt.subplots(1, 3, figsize=(18, 6.2), sharex=True, sharey=True)

    _common(axes[0], "A. Full donut control")
    _beam_pair(axes[0], 0.0, -45.0, 18.0)
    _opposite_arrows(axes[0], 0.0, -45.0, 18.0)
    axes[0].text(-43, 18, "continuous blue access\n(schematic xz pair)", color=BLUE)
    axes[0].text(-43, 13, "blue and green ±y pairs\nare out of this plane", color=BLUE, fontsize=9)

    _common(axes[1], "B. One -z single-pass gate")
    cutoff = settings["entrance_cutoff_offset_m"] * 1e3
    crossings = np.array([settings["entrance_crossing_offset_m"] * 1e3])
    axes[1].axvline(cutoff, linestyle="--", color="0.35", linewidth=1.5)
    axes[1].text(cutoff + 0.8, 18, "hard cutoff\nblue = 0 to the right", fontsize=9)
    for crossing in crossings:
        axes[1].scatter([crossing], [0], color=BLUE, s=32, zorder=6)
        axes[1].text(crossing, -4.0, f"{abs(crossing):g}", ha="center", color=BLUE, fontsize=8)
    _beam_pair(axes[1], -20.0, -45.0, cutoff)
    axes[1].text(-43, 22, "entrance slowing gate\ncrossing: -20 mm", color=BLUE)

    _common(axes[2], "C. Entrance slower + downstream backstop")
    entrance_crossing = settings["entrance_crossing_offset_m"] * 1e3
    entrance_cutoff = settings["entrance_cutoff_offset_m"] * 1e3
    _beam_pair(axes[2], entrance_crossing, -45.0, entrance_cutoff)
    z_min, z_max = np.asarray(settings["backstop_window_m"]) * 1e3
    axes[2].add_patch(
        Rectangle((z_min, -26.5), z_max - z_min, 53, color="#b8dcfa", alpha=0.5, zorder=-2)
    )
    backstop_crossings = np.asarray(settings["backstop_crossing_offsets_m"]) * 1e3
    representative = float(backstop_crossings[len(backstop_crossings) // 2])
    _beam_pair(axes[2], representative, z_min, z_max, alpha=0.95)
    for crossing in backstop_crossings:
        axes[2].scatter([crossing], [0], color=BLUE, s=32, zorder=6)
        axes[2].text(crossing, -4.0, f"{crossing:g}", ha="center", color=BLUE, fontsize=8)
    axes[2].text(-43, 22, "entrance gate\n(kz < 0)", color=BLUE)
    axes[2].text(
        np.mean([z_min, z_max]),
        22,
        f"downstream backstop\n{z_min:g}…{z_max:g} mm; kz < 0",
        ha="center",
        color=BLUE,
    )
    crossing_text = ", ".join(f"{value:g}" for value in backstop_crossings)
    intensity_text = ", ".join(
        f"{value:g}" for value in settings["backstop_s0_values"]
    )
    axes[2].text(
        np.mean([z_min, z_max]),
        -24,
        f"crossings: {crossing_text} mm\ns0: {intensity_text}",
        ha="center",
        fontsize=8.5,
    )

    legend = [
        Line2D([0], [0], color=BLUE, lw=3, label="399-nm blue beam; arrow = propagation"),
        Line2D([0], [0], color=GREEN, lw=2.4, label="protected 556-nm MOT core"),
        Line2D([0], [0], marker="*", color="black", lw=0, markersize=11, label="MOT center"),
    ]
    fig.legend(handles=legend, loc="lower center", ncol=3, frameon=False)
    fig.suptitle("3D-MOT entrance-slower and downstream-backstop study (schematic)", fontsize=16)
    fig.text(
        0.5,
        0.055,
        "All blue beams are transversely center-blocked; the green MOT also contains a ±y pair not visible in this plane.",
        ha="center",
        fontsize=10,
    )
    fig.tight_layout(rect=(0, 0.12, 1, 0.94))
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=220, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {output_path}")
    return output_path


if __name__ == "__main__":
    plot_geometries()
