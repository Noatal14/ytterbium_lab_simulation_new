"""
Visualize the available 3D-MOT configurations.

This script is a geometry/debugging tool only. It does not propagate atoms or
calculate optical forces. The plots are built directly from the 3D-MOT
configuration in ``config.py`` and the same direction/center helper functions
used by ``lab_setup.laser_setup_3d``.

Run from the repository root, for example:

    python plot_3d_mot_configurations.py
    python plot_3d_mot_configurations.py --config angled_concentric
    python plot_3d_mot_configurations.py --save --no-show

Coordinates are shown in millimeters relative to the configured 3D-MOT center.
The beam surfaces are schematic: their transverse size comes from the configured
waist/ring parameters, while the displayed longitudinal beam length is chosen
only for visualization.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D

from config import MOT_3D_CONFIGURATIONS
from lab_setup.laser_setup_3d import _beam_profile_center, _get_beam_directions


BLUE_COLOR = "tab:blue"
GREEN_COLOR = "tab:green"
AXIS_COLOR = "0.35"
MM_PER_M = 1e3


def parse_args():
    parser = argparse.ArgumentParser(
        description="Plot the configured 3D-MOT laser geometries."
    )
    parser.add_argument(
        "--config",
        default="all",
        choices=["all", *sorted(MOT_3D_CONFIGURATIONS)],
        help="Configuration to plot. Default: all.",
    )
    parser.add_argument(
        "--beam-length-mm",
        type=float,
        default=60.0,
        help=(
            "Displayed distance from the notional laser source to the beam "
            "center, in mm. Visualization only. Default: 60 mm."
        ),
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save each figure as a PNG.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("graphs/3d_mot_configurations"),
        help="Directory used with --save.",
    )
    parser.add_argument(
        "--no-show",
        action="store_true",
        help="Do not open interactive plot windows.",
    )
    return parser.parse_args()


def _orthonormal_basis(direction):
    """Return two unit vectors perpendicular to ``direction``."""
    direction = np.asarray(direction, dtype=float)
    direction /= np.linalg.norm(direction)

    reference = np.array([0.0, 0.0, 1.0])
    if abs(np.dot(direction, reference)) > 0.9:
        reference = np.array([0.0, 1.0, 0.0])

    u = np.cross(direction, reference)
    u /= np.linalg.norm(u)
    v = np.cross(direction, u)
    v /= np.linalg.norm(v)
    return u, v


def _cylinder_surface(start, end, radius, n_long=14, n_phi=36):
    """Create a cylindrical surface around the segment from start to end."""
    start = np.asarray(start, dtype=float)
    end = np.asarray(end, dtype=float)
    axis = end - start
    axis_norm = np.linalg.norm(axis)
    if axis_norm == 0.0:
        raise ValueError("Cannot draw a zero-length beam.")

    direction = axis / axis_norm
    u, v = _orthonormal_basis(direction)

    t = np.linspace(0.0, 1.0, n_long)
    phi = np.linspace(0.0, 2.0 * np.pi, n_phi)
    tt, pp = np.meshgrid(t, phi, indexing="ij")

    centers = start[None, None, :] + tt[..., None] * axis[None, None, :]
    radial = radius * (
        np.cos(pp)[..., None] * u[None, None, :]
        + np.sin(pp)[..., None] * v[None, None, :]
    )
    points = centers + radial
    return points[..., 0], points[..., 1], points[..., 2]


def _circle_points(center, direction, radius, n_phi=120):
    """Return a circle in the plane normal to ``direction``."""
    center = np.asarray(center, dtype=float)
    direction = np.asarray(direction, dtype=float)
    direction /= np.linalg.norm(direction)
    u, v = _orthonormal_basis(direction)

    phi = np.linspace(0.0, 2.0 * np.pi, n_phi)
    return (
        center[None, :]
        + radius * np.cos(phi)[:, None] * u[None, :]
        + radius * np.sin(phi)[:, None] * v[None, :]
    )


def _direction_component_enabled(profile, axis_tag, wavelength_key):
    """Return whether one wavelength is enabled on one propagation direction."""
    wavelength_cfg = profile.get(wavelength_key, {})
    axis_components = profile.get("beam_components", {}).get(axis_tag, {})
    return axis_components.get(
        f"{wavelength_key}_enabled",
        wavelength_cfg.get("enabled", True),
    )


def _component_center(profile, wavelength_key):
    """Return the absolute configured center of one wavelength component."""
    base_center = np.asarray(profile["center_position_m"], dtype=float)
    return np.asarray(
        _beam_profile_center(profile, wavelength_key, base_center),
        dtype=float,
    )


def _draw_gaussian_beam(ax, source, center, direction, radius_m, color):
    """Draw a schematic Gaussian beam as a translucent cylinder."""
    x, y, z = _cylinder_surface(source, center, radius_m)
    ax.plot_surface(
        x * MM_PER_M,
        y * MM_PER_M,
        z * MM_PER_M,
        color=color,
        alpha=0.11,
        linewidth=0,
        shade=False,
    )

    segment = np.vstack([source, center]) * MM_PER_M
    ax.plot(
        segment[:, 0],
        segment[:, 1],
        segment[:, 2],
        color=color,
        linewidth=1.8,
        alpha=0.85,
    )

    arrow_start = source + 0.68 * (center - source)
    arrow_length = 0.22 * np.linalg.norm(center - source)
    ax.quiver(
        *(arrow_start * MM_PER_M),
        *(direction * arrow_length * MM_PER_M),
        color=color,
        arrow_length_ratio=0.28,
        linewidth=1.2,
    )


def _draw_annular_beam(
    ax,
    source,
    center,
    direction,
    ring_radius_m,
    ring_width_m,
    color,
):
    """Draw an annular beam as two coaxial shells plus the ring cross-section."""
    inner_radius = max(ring_radius_m - ring_width_m, ring_radius_m * 0.15)
    outer_radius = ring_radius_m + ring_width_m

    for radius in (inner_radius, outer_radius):
        x, y, z = _cylinder_surface(source, center, radius)
        ax.plot_surface(
            x * MM_PER_M,
            y * MM_PER_M,
            z * MM_PER_M,
            color=color,
            alpha=0.09,
            linewidth=0,
            shade=False,
        )

    for radius, width in (
        (inner_radius, 1.0),
        (ring_radius_m, 2.4),
        (outer_radius, 1.0),
    ):
        circle = _circle_points(center, direction, radius) * MM_PER_M
        ax.plot(
            circle[:, 0],
            circle[:, 1],
            circle[:, 2],
            color=color,
            linewidth=width,
            alpha=0.9,
        )

    segment = np.vstack([source, center]) * MM_PER_M
    ax.plot(
        segment[:, 0],
        segment[:, 1],
        segment[:, 2],
        color=color,
        linewidth=1.4,
        alpha=0.75,
    )

    arrow_start = source + 0.68 * (center - source)
    arrow_length = 0.22 * np.linalg.norm(center - source)
    ax.quiver(
        *(arrow_start * MM_PER_M),
        *(direction * arrow_length * MM_PER_M),
        color=color,
        arrow_length_ratio=0.28,
        linewidth=1.2,
    )


def _draw_coordinate_reference(ax, origin, scale_m):
    """Draw x/y/z, atomic propagation, and gravity references."""
    origin = np.asarray(origin, dtype=float)

    for label, direction in (
        ("+x", np.array([1.0, 0.0, 0.0])),
        ("+y", np.array([0.0, 1.0, 0.0])),
        ("+z / atoms", np.array([0.0, 0.0, 1.0])),
    ):
        ax.quiver(
            *(origin * MM_PER_M),
            *(direction * scale_m * MM_PER_M),
            color=AXIS_COLOR,
            linewidth=1.4,
            arrow_length_ratio=0.16,
        )
        label_pos = origin + 1.12 * scale_m * direction
        ax.text(*(label_pos * MM_PER_M), label, color=AXIS_COLOR, fontsize=9)

    gravity = np.array([-1.0, 0.0, 0.0])
    ax.quiver(
        *(origin * MM_PER_M),
        *(gravity * 0.8 * scale_m * MM_PER_M),
        color="black",
        linewidth=2.0,
        arrow_length_ratio=0.18,
    )
    gravity_label = origin + gravity * 0.92 * scale_m
    ax.text(*(gravity_label * MM_PER_M), "gravity", color="black", fontsize=9)


def _set_equal_3d_limits(ax, points_mm, padding=1.12):
    """Give x/y/z approximately equal physical scaling."""
    points_mm = np.asarray(points_mm, dtype=float)
    mins = points_mm.min(axis=0)
    maxs = points_mm.max(axis=0)
    center = 0.5 * (mins + maxs)
    half_span = 0.5 * np.max(maxs - mins) * padding
    if half_span == 0.0:
        half_span = 1.0

    ax.set_xlim(center[0] - half_span, center[0] + half_span)
    ax.set_ylim(center[1] - half_span, center[1] + half_span)
    ax.set_zlim(center[2] - half_span, center[2] + half_span)
    ax.set_box_aspect((1, 1, 1))


def _print_profile_summary(name, profile, directions):
    print()
    print("=" * 72)
    print(f"3D MOT CONFIGURATION: {name}")
    print("=" * 72)

    if "xz_angle_from_z_deg" in profile:
        print(f"xz angle from z: {profile['xz_angle_from_z_deg']:.3f} deg")

    for tag, direction in directions:
        direction = np.asarray(direction, dtype=float)
        print(
            f"{tag:>6s}: "
            f"({direction[0]: .6f}, {direction[1]: .6f}, {direction[2]: .6f})"
        )

    blue_center = _component_center(profile, "399")
    green_center = _component_center(profile, "556")
    print("399 center [m]:", np.array2string(blue_center, precision=6))
    print("556 center [m]:", np.array2string(green_center, precision=6))

    if name == "angled_sequential":
        if blue_center[2] < green_center[2]:
            print("Ordering check: OK — blue is upstream of green along +z.")
        else:
            print("Ordering check: WARNING — blue is not upstream of green.")

    if name == "five_beam_gravity":
        tags = {tag for tag, _ in directions}
        if "-X" not in tags and "+X" in tags:
            print("Five-beam check: OK — -X is blocked and +X remains.")
        else:
            print("Five-beam check: WARNING — unexpected vertical beam set.")


def plot_configuration(name, profile, beam_length_m):
    directions = _get_beam_directions(profile)
    _print_profile_summary(name, profile, directions)

    absolute_center = np.asarray(profile["center_position_m"], dtype=float)

    fig = plt.figure(figsize=(10, 9))
    ax = fig.add_subplot(111, projection="3d")

    points_for_limits = [np.zeros(3)]
    relative_origin = np.zeros(3)

    reference_scale = min(0.025, 0.45 * beam_length_m)
    _draw_coordinate_reference(ax, relative_origin, reference_scale)

    ax.scatter(0.0, 0.0, 0.0, marker="*", s=140, color="black", zorder=10)

    blue_cfg = profile.get("399", {})
    green_cfg = profile.get("556", {})

    for axis_tag, direction in directions:
        direction = np.asarray(direction, dtype=float)
        direction /= np.linalg.norm(direction)

        for wavelength_key, cfg, color in (
            ("399", blue_cfg, BLUE_COLOR),
            ("556", green_cfg, GREEN_COLOR),
        ):
            if not _direction_component_enabled(profile, axis_tag, wavelength_key):
                continue

            component_center_abs = _component_center(profile, wavelength_key)
            component_center = component_center_abs - absolute_center

            # A propagation vector points from the source toward the beam center.
            source = component_center - direction * beam_length_m
            profile_kind = cfg.get("profile", "gaussian")

            if profile_kind == "annular":
                ring_radius = float(cfg["ring_radius_m"])
                ring_width = float(cfg["ring_width_m"])
                _draw_annular_beam(
                    ax,
                    source,
                    component_center,
                    direction,
                    ring_radius,
                    ring_width,
                    color,
                )
                display_radius = ring_radius + ring_width
            else:
                waist = float(cfg["waist_m"])
                _draw_gaussian_beam(
                    ax,
                    source,
                    component_center,
                    direction,
                    waist,
                    color,
                )
                display_radius = waist

            points_for_limits.extend(
                [
                    source * MM_PER_M,
                    component_center * MM_PER_M,
                    (component_center + display_radius) * MM_PER_M,
                    (component_center - display_radius) * MM_PER_M,
                ]
            )

            label_pos = source * MM_PER_M
            ax.text(
                label_pos[0],
                label_pos[1],
                label_pos[2],
                f"{wavelength_key} {axis_tag}",
                color=color,
                fontsize=7,
            )

    if name == "angled_sequential":
        blue_center = (_component_center(profile, "399") - absolute_center) * MM_PER_M
        green_center = (_component_center(profile, "556") - absolute_center) * MM_PER_M
        ax.scatter(*blue_center, s=55, color=BLUE_COLOR, marker="o")
        ax.scatter(*green_center, s=55, color=GREEN_COLOR, marker="o")
        ax.text(*blue_center, "  blue center", color=BLUE_COLOR, fontsize=8)
        ax.text(*green_center, "  green center", color=GREEN_COLOR, fontsize=8)

    if name == "five_beam_gravity":
        # The missing source is physically above (+x). A beam emitted from there
        # toward the MOT would propagate along -x.
        missing_source = np.array([beam_length_m, 0.0, 0.0])
        ax.scatter(*(missing_source * MM_PER_M), marker="x", s=90, color="black")
        ax.text(
            *(missing_source * MM_PER_M),
            "  blocked upper beam\n  (would propagate -x)",
            color="black",
            fontsize=8,
        )
        points_for_limits.append(missing_source * MM_PER_M)

    legend_handles = [
        Line2D([0], [0], color=BLUE_COLOR, lw=4, label="399 nm"),
        Line2D([0], [0], color=GREEN_COLOR, lw=4, label="556 nm"),
        Line2D(
            [0],
            [0],
            marker="*",
            color="black",
            linestyle="None",
            markersize=10,
            label="3D-MOT center",
        ),
    ]
    ax.legend(handles=legend_handles, loc="upper left")

    ax.set_title(
        f"3D-MOT configuration: {name}\n"
        "(geometry visualization; beam length is schematic)"
    )
    ax.set_xlabel("x relative to MOT center [mm]\n(gravity is -x)")
    ax.set_ylabel("y relative to MOT center [mm]")
    ax.set_zlabel("z relative to MOT center [mm]\n(atoms propagate +z)")

    _set_equal_3d_limits(ax, points_for_limits)
    ax.view_init(elev=24, azim=-55)
    fig.tight_layout()
    return fig


def main():
    args = parse_args()

    if args.beam_length_mm <= 0.0:
        raise ValueError("--beam-length-mm must be positive.")

    beam_length_m = args.beam_length_mm / MM_PER_M

    if args.config == "all":
        config_names = list(MOT_3D_CONFIGURATIONS)
    else:
        config_names = [args.config]

    if args.save:
        args.output_dir.mkdir(parents=True, exist_ok=True)

    figures = []
    for name in config_names:
        fig = plot_configuration(
            name,
            MOT_3D_CONFIGURATIONS[name],
            beam_length_m,
        )
        figures.append(fig)

        if args.save:
            output_path = args.output_dir / f"3d_mot_{name}.png"
            fig.savefig(output_path, dpi=220, bbox_inches="tight")
            print(f"Saved: {output_path}")

    if not args.no_show:
        plt.show()
    else:
        for fig in figures:
            plt.close(fig)


if __name__ == "__main__":
    main()