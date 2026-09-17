"""
Visualize the available 3D-MOT configurations.

This script is a geometry/debugging tool only. It does not propagate atoms or
calculate optical forces. The plots are built directly from the 3D-MOT
configuration in ``config.py`` and the same direction/center helper functions
used by ``lab_setup.laser_setup_3d``.

Run from the repository root, for example:

    python -m graphs_scripts.plot_3d_mot_configurations
    python -m graphs_scripts.plot_3d_mot_configurations --config angled_donut

Coordinates are shown in millimeters relative to the configured 3D-MOT center.
The beam surfaces are schematic: their transverse size comes from the configured
waist and cutoff parameters, while the displayed longitudinal beam length is chosen
only for visualization.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import Arc

from config import MOT_3D_CONFIGURATIONS
from lab_setup.laser_setup_3d import (
    _beam_profile_center,
    _get_beam_directions,
    _validate_profile,
    setup_3dmot_lasers,
)


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
        "--output-dir",
        type=Path,
        default=Path("graphs/mot_3d_configuration_decision"),
        help="Directory for the generated PNG files.",
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


def _filled_cylinder(ax, start, end, radius, color, alpha):
    """Draw one smooth beam envelope without the visually dense wire mesh."""
    x, y, z = _cylinder_surface(start, end, radius, n_long=2, n_phi=56)
    ax.plot_surface(
        x * MM_PER_M,
        y * MM_PER_M,
        z * MM_PER_M,
        color=color,
        alpha=alpha,
        linewidth=0.0,
        antialiased=True,
        shade=False,
    )
    for point in (start, end):
        circle = _circle_points(point, end - start, radius) * MM_PER_M
        ax.plot(*circle.T, color=color, linewidth=0.8, alpha=min(1.0, alpha + 0.35))


def _display_radius(cfg):
    profile_kind = cfg.get("profile", "gaussian")
    if profile_kind == "donut":
        return max(1.5 * float(cfg["waist_m"]), float(cfg["inner_cutoff_radius_m"]))
    if profile_kind == "outer_clipped_gaussian":
        return float(cfg["outer_cutoff_radius_m"])
    if profile_kind == "elliptical":
        return max(float(cfg["waist_short_m"]), float(cfg["waist_long_m"]))
    return float(cfg["waist_m"])


def _beam_display_specs(profile, beam_length_m):
    """Return one authoritative set of schematic beams for all view panels."""
    absolute_center = np.asarray(profile["center_position_m"], dtype=float)
    specs = []
    for axis_tag, raw_direction in _get_beam_directions(profile):
        direction = np.asarray(raw_direction, dtype=float)
        direction /= np.linalg.norm(direction)
        for wavelength_key, color in (("399", BLUE_COLOR), ("556", GREEN_COLOR)):
            if not _direction_component_enabled(profile, axis_tag, wavelength_key):
                continue
            cfg = profile[wavelength_key]
            center = _component_center(profile, wavelength_key) - absolute_center
            source = center - direction * beam_length_m
            specs.append(
                {
                    "axis_tag": axis_tag,
                    "wavelength": wavelength_key,
                    "color": color,
                    "direction": direction,
                    "source": source,
                    "center": center,
                    "radius_m": _display_radius(cfg),
                    "inner_radius_m": (
                        float(cfg["inner_cutoff_radius_m"])
                        if cfg.get("profile") == "donut"
                        else None
                    ),
                }
            )

    return specs


def _draw_simplified_3d_beam(ax, spec):
    """Draw a filled envelope, centerline, and unmistakable propagation arrow."""
    alpha = 0.12 if spec["wavelength"] == "399" else 0.24
    _filled_cylinder(
        ax,
        spec["source"],
        spec["center"],
        spec["radius_m"],
        spec["color"],
        alpha,
    )
    if spec["inner_radius_m"] is not None:
        for point in (spec["source"], spec["center"]):
            circle = _circle_points(
                point, spec["direction"], spec["inner_radius_m"]
            ) * MM_PER_M
            ax.plot(*circle.T, color=spec["color"], linewidth=1.5, linestyle="--")
    segment = np.vstack([spec["source"], spec["center"]]) * MM_PER_M
    ax.plot(*segment.T, color=spec["color"], linewidth=2.0, alpha=0.92)
    start = spec["source"] + 0.57 * (spec["center"] - spec["source"])
    length = 0.25 * np.linalg.norm(spec["center"] - spec["source"])
    ax.quiver(
        *(start * MM_PER_M),
        *(spec["direction"] * length * MM_PER_M),
        color=spec["color"],
        linewidth=2.6,
        arrow_length_ratio=0.42,
    )


def _draw_projection(ax, specs, vertical_axis, title, profile, beam_length_m):
    """Draw an orthographic z-versus-x/y schematic with readable arrows."""
    vertical_index = {"x": 0, "y": 1}[vertical_axis]
    projected = []
    labels_by_segment = {}
    drawn_segments = set()

    for spec in specs:
        source = np.array(
            [spec["source"][2], spec["source"][vertical_index]], dtype=float
        )
        center = np.array(
            [spec["center"][2], spec["center"][vertical_index]], dtype=float
        )
        # An axis perpendicular to this view collapses to a point. Omitting it
        # is clearer than drawing a blob and a label at the MOT center; it is
        # visible in the complementary projection.
        if np.linalg.norm(center - source) < 1e-10:
            continue
        geometry_key = tuple(np.round(np.concatenate([source, center]), 10))
        labels_by_segment.setdefault(geometry_key, set()).add(spec["axis_tag"])
        projected.append((spec, source, center, geometry_key))

    # Draw broad 399 envelopes first and green cores above them.
    ordered = sorted(projected, key=lambda item: item[0]["wavelength"] == "556")
    for spec, source, center, geometry_key in ordered:
        draw_key = (spec["wavelength"], geometry_key)
        if draw_key in drawn_segments:
            continue
        drawn_segments.add(draw_key)
        z = np.array([source[0], center[0]]) * MM_PER_M
        vertical = np.array([source[1], center[1]]) * MM_PER_M
        width = 15 if spec["wavelength"] == "399" else 8
        ax.plot(
            z,
            vertical,
            color=spec["color"],
            linewidth=width,
            alpha=0.14 if spec["wavelength"] == "399" else 0.24,
            solid_capstyle="round",
        )
        ax.plot(z, vertical, color=spec["color"], linewidth=1.8, alpha=0.9)
        start = source + 0.55 * (center - source)
        delta = 0.25 * (center - source)
        ax.annotate(
            "",
            xy=((start[0] + delta[0]) * MM_PER_M,
                (start[1] + delta[1]) * MM_PER_M),
            xytext=(start[0] * MM_PER_M, start[1] * MM_PER_M),
            arrowprops={
                "arrowstyle": "-|>",
                "color": spec["color"],
                "lw": 2.6,
                "mutation_scale": 16,
            },
        )

    # Hidden-coordinate symmetry can make distinct axes coincide in a 2D
    # view. Label the shared projection once instead of stacking text.
    for geometry_key, axis_tags in labels_by_segment.items():
        source_z, source_vertical, _, _ = geometry_key
        label = " / ".join(sorted(axis_tags))
        ax.text(
            source_z * MM_PER_M,
            source_vertical * MM_PER_M,
            f" {label}",
            fontsize=8,
            color="0.2",
            ha="left",
            va="bottom",
        )

    ax.scatter(0, 0, marker="*", s=90, color="black", zorder=10)
    ax.annotate(
        "atoms +z",
        xy=(-0.70 * beam_length_m * MM_PER_M, -0.78 * beam_length_m * MM_PER_M),
        xytext=(-1.08 * beam_length_m * MM_PER_M, -0.78 * beam_length_m * MM_PER_M),
        arrowprops={"arrowstyle": "-|>", "lw": 2.8, "color": "#b24c00"},
        color="#b24c00",
        fontsize=9,
        va="center",
    )
    if vertical_axis == "x":
        ax.annotate(
            "gravity",
            xy=(0, -0.58 * beam_length_m * MM_PER_M),
            xytext=(0, -0.20 * beam_length_m * MM_PER_M),
            arrowprops={"arrowstyle": "-|>", "lw": 2.4, "color": "black"},
            ha="center",
            fontsize=9,
        )
        if profile.get("beam_layout") == "rotated_yz_minus_upper_x":
            ax.scatter(0, beam_length_m * MM_PER_M, marker="x", s=90, color="black")
            ax.text(2, beam_length_m * MM_PER_M, "blocked upper beam", fontsize=8)

    limit = 1.38 * beam_length_m * MM_PER_M
    ax.set_xlim(-limit, limit)
    ax.set_ylim(-limit, limit)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("z relative to MOT center [mm]")
    ax.set_ylabel(f"{vertical_axis} relative to MOT center [mm]")
    ax.set_title(title)
    ax.grid(alpha=0.16)


def _draw_angle_marker(ax, radius_mm, theta1_deg, theta2_deg, label):
    """Draw a compact angle arc around the MOT center in a 2D projection."""
    arc = Arc(
        (0.0, 0.0),
        2.0 * radius_mm,
        2.0 * radius_mm,
        theta1=theta1_deg,
        theta2=theta2_deg,
        color="#6a3d9a",
        linewidth=2.2,
        zorder=12,
    )
    ax.add_patch(arc)
    middle = np.deg2rad(0.5 * (theta1_deg + theta2_deg))
    label_radius = 1.18 * radius_mm
    ax.text(
        label_radius * np.cos(middle),
        label_radius * np.sin(middle),
        label,
        color="#6a3d9a",
        fontsize=10,
        fontweight="bold",
        ha="center",
        va="center",
        zorder=13,
        bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.78, "pad": 1.0},
    )


def _annotate_configuration_angles(name, xz_ax, yz_ax):
    """Mark the experimentally relevant inter-beam angles."""
    if name == "angled_donut":
        # The two crossed x-z axes are 30 degrees from z, giving alternating
        # 60-degree and 120-degree sectors around the MOT center.
        _draw_angle_marker(xz_ax, 17.0, -30.0, 30.0, r"$60^\circ$")
        _draw_angle_marker(xz_ax, 22.0, 30.0, 150.0, r"$120^\circ$")
    elif name == "five_beam_gravity":
        # The two diagonal axes in the y-z plane are orthogonal.
        _draw_angle_marker(yz_ax, 19.0, 45.0, 135.0, r"$90^\circ$")


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
    """Draw one opaque wire boundary at the configured 1/e^2 waist."""
    x, y, z = _cylinder_surface(source, center, radius_m)
    ax.plot_wireframe(
        x * MM_PER_M, y * MM_PER_M, z * MM_PER_M,
        color=color, linewidth=0.55, rstride=3, cstride=6,
    )

    segment = np.vstack([source, center]) * MM_PER_M
    ax.plot(
        segment[:, 0],
        segment[:, 1],
        segment[:, 2],
        color=color,
        linewidth=1.8,
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


def _draw_outer_clipped_gaussian_beam(
    ax, source, center, direction, waist_m, outer_cutoff_radius_m, color
):
    """Draw the opaque wire boundary of the transmitted green core."""
    x, y, z = _cylinder_surface(source, center, outer_cutoff_radius_m)
    ax.plot_wireframe(
        x * MM_PER_M, y * MM_PER_M, z * MM_PER_M,
        color=color, linewidth=0.55, rstride=3, cstride=6,
    )

    segment = np.vstack([source, center]) * MM_PER_M
    ax.plot(*segment.T, color=color, linewidth=1.8, alpha=0.85)


def _draw_elliptical_beam(ax, source, center, direction, short_m, long_m, color):
    """Draw the crossed slower with its long axis along lab y."""
    direction = np.asarray(direction, dtype=float)
    direction /= np.linalg.norm(direction)
    long_axis = np.array([0.0, 1.0, 0.0])
    short_axis = np.cross(long_axis, direction)
    short_axis /= np.linalg.norm(short_axis)

    t = np.linspace(0.0, 1.0, 14)
    phi = np.linspace(0.0, 2.0 * np.pi, 36)
    tt, pp = np.meshgrid(t, phi, indexing="ij")
    centers = source[None, None, :] + tt[..., None] * (
        center - source
    )[None, None, :]
    points = centers + (
        short_m * np.cos(pp)[..., None] * short_axis[None, None, :]
        + long_m * np.sin(pp)[..., None] * long_axis[None, None, :]
    )
    ax.plot_wireframe(
        points[..., 0] * MM_PER_M,
        points[..., 1] * MM_PER_M,
        points[..., 2] * MM_PER_M,
        color=color,
        linewidth=0.55,
        rstride=3,
        cstride=6,
    )
    segment = np.vstack([source, center]) * MM_PER_M
    ax.plot(*segment.T, color=color, linewidth=1.8, alpha=0.85)

    arrow_start = source + 0.68 * (center - source)
    arrow_length = 0.22 * np.linalg.norm(center - source)
    ax.quiver(
        *(arrow_start * MM_PER_M),
        *(direction * arrow_length * MM_PER_M),
        color=color,
        arrow_length_ratio=0.28,
        linewidth=1.2,
    )


def _draw_donut_beam(
    ax,
    source,
    center,
    direction,
    waist_m,
    inner_cutoff_radius_m,
    color,
):
    """Draw a Gaussian beam whose central disk is removed by a hard mask."""
    outer_radius = max(1.5 * waist_m, inner_cutoff_radius_m)
    for radius in (outer_radius, inner_cutoff_radius_m):
        x, y, z = _cylinder_surface(source, center, radius)
        ax.plot_wireframe(
            x * MM_PER_M,
            y * MM_PER_M,
            z * MM_PER_M,
            color=color,
            linewidth=0.5,
            rstride=3,
            cstride=6,
        )

    for radius, width, linestyle in (
        (inner_cutoff_radius_m, 2.4, "--"),
        (outer_radius, 0.8, ":"),
    ):
        circle = _circle_points(center, direction, radius) * MM_PER_M
        ax.plot(
            circle[:, 0],
            circle[:, 1],
            circle[:, 2],
            color=color,
            linewidth=width,
            linestyle=linestyle,
        )

    segment = np.vstack([source, center]) * MM_PER_M
    ax.plot(
        segment[:, 0],
        segment[:, 1],
        segment[:, 2],
        color=color,
        linewidth=1.0,
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


def _normalized_radial_intensity(cfg, radius_m, waist_m=None):
    """Return the configured transverse intensity normalized to its peak."""
    if cfg.get("profile", "gaussian") == "donut":
        intensity = np.exp(-2.0 * radius_m**2 / float(cfg["waist_m"]) ** 2)
        return np.where(
            radius_m < float(cfg["inner_cutoff_radius_m"]),
            0.0,
            intensity,
        )
    if cfg.get("profile") == "outer_clipped_gaussian":
        intensity = np.exp(-2.0 * radius_m**2 / float(cfg["waist_m"]) ** 2)
        return np.where(
            radius_m < float(cfg["outer_cutoff_radius_m"]),
            intensity,
            0.0,
        )
    waist = waist_m or cfg.get("waist_m", cfg.get("waist_short_m"))
    return np.exp(-2.0 * radius_m**2 / float(waist) ** 2)


def _draw_radial_profiles(ax, blue_cfg, green_cfg):
    """Show an exact transverse cut so nested beams remain interpretable."""
    blue_is_elliptical = blue_cfg.get("profile") == "elliptical"
    characteristic_radii = [
        1.5
        * float(
            blue_cfg.get(
                "waist_m",
                blue_cfg.get("waist_long_m", blue_cfg.get("waist_short_m")),
            )
        ),
        1.5 * float(green_cfg["waist_m"]),
    ]
    if blue_cfg.get("profile") == "donut":
        characteristic_radii.append(float(blue_cfg["inner_cutoff_radius_m"]))
    if green_cfg.get("profile") == "outer_clipped_gaussian":
        characteristic_radii.append(float(green_cfg["outer_cutoff_radius_m"]))
    radius_m = np.linspace(0.0, max(characteristic_radii), 600)

    profiles = [(green_cfg, GREEN_COLOR, "556 nm", None, "-")]
    if blue_is_elliptical:
        profiles.extend(
            [
                (
                    blue_cfg,
                    BLUE_COLOR,
                    "399 nm short-axis cut (1.5 mm waist)",
                    float(blue_cfg["waist_short_m"]),
                    "-",
                ),
                (
                    blue_cfg,
                    BLUE_COLOR,
                    "399 nm long-axis cut (10 mm waist)",
                    float(blue_cfg["waist_long_m"]),
                    "--",
                ),
            ]
        )
    else:
        profiles.append((blue_cfg, BLUE_COLOR, "399 nm radial cut", None, "-"))

    for cfg, color, label, waist_m, linestyle in profiles:
        intensity = _normalized_radial_intensity(cfg, radius_m, waist_m=waist_m)
        ax.plot(
            radius_m * MM_PER_M,
            intensity,
            color=color,
            linewidth=2.5,
            linestyle=linestyle,
            label=label,
        )
        ax.fill_between(
            radius_m * MM_PER_M,
            0.0,
            intensity,
            color=color,
            alpha=0.08 if blue_is_elliptical else 0.15,
        )

    if blue_cfg.get("profile") == "donut":
        cutoff_mm = float(blue_cfg["inner_cutoff_radius_m"]) * MM_PER_M
        ax.axvspan(0.0, cutoff_mm, color=BLUE_COLOR, alpha=0.06)
        ax.axvline(cutoff_mm, color=BLUE_COLOR, linestyle="--", linewidth=1.2)
        ax.text(
            0.5 * cutoff_mm,
            0.52,
            "blue intensity\nexactly zero",
            color=BLUE_COLOR,
            ha="center",
            va="center",
            fontsize=9,
        )
        if green_cfg.get("profile") == "outer_clipped_gaussian":
            ax.text(
                1.22 * cutoff_mm,
                0.52,
                "green intensity\nexactly zero",
                color=GREEN_COLOR,
                ha="center",
                va="center",
                fontsize=9,
            )

    ax.set_title("Transverse intensity cuts")
    ax.set_xlabel("distance from beam axis along indicated cut [mm]")
    ax.set_ylabel("normalized intensity")
    ax.set_ylim(-0.03, 1.08)
    ax.grid(alpha=0.25)
    ax.legend()


def _draw_sequential_longitudinal_profiles(ax, profile):
    """Show the actual complementary blue/green cut along the atomic axis."""
    center = np.asarray(profile["center_position_m"], dtype=float)
    z_relative_m = np.linspace(-50.0e-3, 30.0e-3, 900)
    positions = np.column_stack(
        [
            np.full_like(z_relative_m, center[0]),
            np.full_like(z_relative_m, center[1]),
            center[2] + z_relative_m,
        ]
    )
    beams = setup_3dmot_lasers(profile)
    for wavelength, color in (("399", BLUE_COLOR), ("556", GREEN_COLOR)):
        selected = [beam for beam in beams if f"3DMOT_{wavelength}_" in beam.tag]
        intensity = sum(np.asarray(beam.get_value(positions)) for beam in selected)
        normalized = intensity / intensity.max()
        ax.plot(z_relative_m * MM_PER_M, normalized, color=color, linewidth=2.5, label=f"{wavelength} nm")
    cutoff_mm = -float(profile["399"]["green_exclusion_radius_m"]) * MM_PER_M
    ax.axvline(cutoff_mm, color="black", linestyle="--", linewidth=1.3, label="separation plane")
    ax.axvline(0.0, color="0.4", linestyle=":", linewidth=1.3, label="MOT center")
    ax.set_title("Longitudinal intensity on the atomic axis")
    ax.set_xlabel("z relative to MOT center [mm] (atoms propagate +z)")
    ax.set_ylabel("normalized intensity for each wavelength")
    ax.set_ylim(-0.03, 1.08)
    ax.grid(alpha=0.25)
    ax.legend()


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

    if profile["399"].get("profile") == "upstream_planar_clipped_gaussian":
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
    _validate_profile(profile)
    directions = _get_beam_directions(profile)
    _print_profile_summary(name, profile, directions)
    specs = _beam_display_specs(profile, beam_length_m)
    fig = plt.figure(figsize=(15.5, 8.5))
    grid = fig.add_gridspec(2, 3, width_ratios=(1.25, 1.25, 1.0))
    ax = fig.add_subplot(grid[:, :2], projection="3d")
    xz_ax = fig.add_subplot(grid[0, 2])
    yz_ax = fig.add_subplot(grid[1, 2])

    for spec in specs:
        _draw_simplified_3d_beam(ax, spec)
    ax.scatter(0, 0, 0, marker="*", s=180, color="black", zorder=20)

    # One label per optical axis, positioned at the source and detached from
    # wavelength-specific colors.
    labelled = set()
    for spec in specs:
        if spec["axis_tag"] in labelled:
            continue
        source_mm = spec["source"] * MM_PER_M
        ax.text(*source_mm, f"  {spec['axis_tag']}", color="0.18", fontsize=8)
        labelled.add(spec["axis_tag"])

    # Reference arrows are spatially separated from the optical arrows.
    atom_start = np.array([0.0, 0.0, -1.18 * beam_length_m])
    ax.quiver(
        *(atom_start * MM_PER_M), 0, 0, 0.38 * beam_length_m * MM_PER_M,
        color="#b24c00", linewidth=3.0, arrow_length_ratio=0.25,
    )
    ax.text(*(atom_start * MM_PER_M), " atoms +z", color="#b24c00", fontsize=9)
    gravity_start = np.array([0.55 * beam_length_m, 0.65 * beam_length_m, 0.0])
    ax.quiver(
        *(gravity_start * MM_PER_M), -0.38 * beam_length_m * MM_PER_M, 0, 0,
        color="black", linewidth=2.8, arrow_length_ratio=0.25,
    )
    ax.text(*(gravity_start * MM_PER_M), " gravity -x", fontsize=9)

    if name == "five_beam_gravity":
        missing_source = np.array([beam_length_m, 0.0, 0.0])
        ax.scatter(*(missing_source * MM_PER_M), marker="x", s=120, color="black")
        ax.text(*(missing_source * MM_PER_M), "  blocked upper beam", fontsize=8)

    _draw_projection(xz_ax, specs, "x", "x-z view", profile, beam_length_m)
    _draw_projection(yz_ax, specs, "y", "y-z view", profile, beam_length_m)
    _annotate_configuration_angles(name, xz_ax, yz_ax)

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

    display_names = {
        "angled_donut": "angled donut",
        "five_beam_gravity": "five-beam gravity MOT",
    }
    fig.suptitle(f"3D-MOT geometry: {display_names.get(name, name)}", fontsize=16)
    ax.set_title("Filled beam envelopes; length is schematic")
    ax.set_xlabel("x relative to MOT center [mm]\n(gravity is -x)")
    ax.set_ylabel("y relative to MOT center [mm]")
    ax.set_zlabel("z relative to MOT center [mm]\n(atoms propagate +z)")

    extent = 1.38 * beam_length_m * MM_PER_M
    ax.set_xlim(-extent, extent)
    ax.set_ylim(-extent, extent)
    ax.set_zlim(-extent, extent)
    ax.set_box_aspect((1, 1, 1))
    ax.view_init(elev=21, azim=-52)
    ax.grid(alpha=0.12)
    fig.tight_layout()
    return fig


def plot_radial_profiles(name, profile):
    """Keep intensity information separate from the geometry schematic."""
    fig, ax = plt.subplots(figsize=(8.2, 5.4))
    _draw_radial_profiles(ax, profile["399"], profile["556"])
    fig.suptitle(f"3D-MOT radial profiles: {name}", fontsize=15)
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

    args.output_dir.mkdir(parents=True, exist_ok=True)

    for name in config_names:
        fig = plot_configuration(
            name,
            MOT_3D_CONFIGURATIONS[name],
            beam_length_m,
        )
        output_names = {
            "angled_donut": "01_angled_donut_geometry.png",
            "five_beam_gravity": "02_five_beam_geometry.png",
        }
        output_path = args.output_dir / output_names[name]
        fig.savefig(output_path, dpi=220, bbox_inches="tight")
        plt.close(fig)
        print(f"Saved: {output_path}")

        radial_fig = plot_radial_profiles(name, MOT_3D_CONFIGURATIONS[name])
        radial_names = {
            "angled_donut": "01b_angled_donut_radial_profiles.png",
            "five_beam_gravity": "02b_five_beam_radial_profiles.png",
        }
        radial_path = args.output_dir / radial_names[name]
        radial_fig.savefig(radial_path, dpi=220, bbox_inches="tight")
        plt.close(radial_fig)
        print(f"Saved: {radial_path}")


if __name__ == "__main__":
    main()
