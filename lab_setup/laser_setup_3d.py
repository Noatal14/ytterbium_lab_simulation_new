import numpy as np
from lab_setup.zeeman_laser_setup import CircularGaussianBeam
from lab_setup.laser_setup_2d_mot import EllipticalLaserBeam
from atomsmltr.environment.lasers.polarization import CircularLeft, CircularRight
from config import (
    ACTIVE_MOT_3D_CONFIGURATION,
    MOT_3D_CONFIGURATIONS,
    BLUE_TRANSITION,
    GREEN_TRANSITION,
    BLUE_SATURATION_INTENSITY_MW_CM2,
    GREEN_SATURATION_INTENSITY_W_M2,
)


class DonutGaussianBeam(CircularGaussianBeam):
    """A regular Gaussian beam with a completely blocked central aperture.

    The optical Gaussian is unchanged outside ``inner_cutoff_radius``. Inside
    that radius its intensity is exactly zero, representing the experimental
    beam after its center is removed by the mirror arrangement.
    """

    def __init__(
        self,
        wavelength=BLUE_TRANSITION.wavelength_m,
        waist=1e-3,
        power=1e-3,
        waist_position=None,
        direction=None,
        direction_type="vector",
        polarization=None,
        tag=None,
        inner_cutoff_radius=0.5e-3,
        **kwargs,
    ):
        self.inner_cutoff_radius = float(inner_cutoff_radius)
        if self.inner_cutoff_radius <= 0.0:
            raise ValueError("inner_cutoff_radius must be positive.")
        super().__init__(
            wavelength=wavelength,
            waist=waist,
            power=power,
            waist_position=waist_position,
            direction=direction,
            direction_type=direction_type,
            polarization=polarization,
            tag=tag,
            **kwargs,
        )

    @property
    def type(self):
        return "Center-blocked Gaussian Beam"

    @property
    def disp_type(self):
        return "Center-blocked beam"

    @staticmethod
    def _intensity_func(self, position):
        position_laser = self._convert_coordinates_to_laser_frame(position)
        x_laser, y_laser, _ = position_laser.T
        rho_laser = np.sqrt(x_laser**2 + y_laser**2)
        intensity = CircularGaussianBeam._intensity_func(self, position)
        intensity = np.where(rho_laser < self.inner_cutoff_radius, 0.0, intensity)
        return intensity


class OuterClippedGaussianBeam(CircularGaussianBeam):
    """A Gaussian beam transmitted only inside a hard outer aperture."""

    def __init__(self, *args, outer_cutoff_radius=0.5e-3, **kwargs):
        self.outer_cutoff_radius = float(outer_cutoff_radius)
        if self.outer_cutoff_radius <= 0.0:
            raise ValueError("outer_cutoff_radius must be positive.")
        super().__init__(*args, **kwargs)

    @property
    def type(self):
        return "Outer-clipped Gaussian Beam"

    @property
    def disp_type(self):
        return "Outer-clipped beam"

    @staticmethod
    def _intensity_func(self, position):
        position_laser = self._convert_coordinates_to_laser_frame(position)
        x_laser, y_laser, _ = position_laser.T
        rho_laser = np.sqrt(x_laser**2 + y_laser**2)
        intensity = CircularGaussianBeam._intensity_func(self, position)
        return np.where(rho_laser < self.outer_cutoff_radius, intensity, 0.0)


class UpstreamPlanarClippedGaussianBeam(CircularGaussianBeam):
    """Circular Gaussian transmitted only on the upstream side of a lab-z plane."""

    def __init__(self, *args, maximum_lab_z_m, **kwargs):
        self.maximum_lab_z_m = float(maximum_lab_z_m)
        if not np.isfinite(self.maximum_lab_z_m):
            raise ValueError("maximum_lab_z_m must be finite.")
        super().__init__(*args, **kwargs)

    @property
    def type(self):
        return "Upstream planar-clipped Gaussian Beam"

    @property
    def disp_type(self):
        return "Planar-clipped beam"

    @staticmethod
    def _intensity_func(self, position):
        position = np.asarray(position, dtype=float)
        intensity = CircularGaussianBeam._intensity_func(self, position)
        # The boundary belongs to the illuminated upstream half-space. This
        # preserves a crossing located exactly on the physical cutoff plane.
        return np.where(position[..., 2] <= self.maximum_lab_z_m, intensity, 0.0)


class UpstreamClippedDonutGaussianBeam(DonutGaussianBeam):
    """Center-blocked Gaussian additionally terminated at a lab-z plane."""

    def __init__(self, *args, maximum_lab_z_m, **kwargs):
        self.maximum_lab_z_m = float(maximum_lab_z_m)
        if not np.isfinite(self.maximum_lab_z_m):
            raise ValueError("maximum_lab_z_m must be finite.")
        super().__init__(*args, **kwargs)

    @property
    def type(self):
        return "Upstream-clipped center-blocked Gaussian Beam"

    @staticmethod
    def _intensity_func(self, position):
        position = np.asarray(position, dtype=float)
        intensity = DonutGaussianBeam._intensity_func(self, position)
        return np.where(position[..., 2] <= self.maximum_lab_z_m, intensity, 0.0)


class WindowClippedDonutGaussianBeam(DonutGaussianBeam):
    """Center-blocked Gaussian transmitted only between two lab-z planes."""

    def __init__(self, *args, minimum_lab_z_m, maximum_lab_z_m, **kwargs):
        self.minimum_lab_z_m = float(minimum_lab_z_m)
        self.maximum_lab_z_m = float(maximum_lab_z_m)
        if not (
            np.isfinite(self.minimum_lab_z_m)
            and np.isfinite(self.maximum_lab_z_m)
            and self.minimum_lab_z_m < self.maximum_lab_z_m
        ):
            raise ValueError("Finite beam-window bounds must satisfy min < max.")
        super().__init__(*args, **kwargs)

    @property
    def type(self):
        return "Window-clipped center-blocked Gaussian Beam"

    @staticmethod
    def _intensity_func(self, position):
        position = np.asarray(position, dtype=float)
        intensity = DonutGaussianBeam._intensity_func(self, position)
        inside_window = (position[..., 2] >= self.minimum_lab_z_m) & (
            position[..., 2] <= self.maximum_lab_z_m
        )
        return np.where(inside_window, intensity, 0.0)


def _normalize_vector(vec):
    vec = np.asarray(vec, dtype=float)
    norm = np.linalg.norm(vec)
    if norm == 0.0:
        raise ValueError("Direction vector must be non-zero.")
    return vec / norm


def _angled_xz_y_directions(theta_deg):
    theta = np.deg2rad(float(theta_deg))
    s = np.sin(theta)
    c = np.cos(theta)
    return [
        ("+XZ_1", _normalize_vector((s, 0.0, c))),
        ("-XZ_1", _normalize_vector((-s, 0.0, -c))),
        ("+XZ_2", _normalize_vector((-s, 0.0, c))),
        ("-XZ_2", _normalize_vector((s, 0.0, -c))),
        ("+Y", _normalize_vector((0.0, 1.0, 0.0))),
        ("-Y", _normalize_vector((0.0, -1.0, 0.0))),
    ]


def _single_pass_yz_directions(crossing_angle_deg):
    """Return the two blue entrance-slower directions in the yz plane.

    Both beams propagate toward -z.  The first originates at negative y and
    therefore has a +y component; the second originates at positive y and has
    a -y component.  Their full included angle is ``crossing_angle_deg``.
    """
    half_angle = 0.5 * np.deg2rad(float(crossing_angle_deg))
    transverse = np.sin(half_angle)
    longitudinal = np.cos(half_angle)
    return [
        ("SP_FROM_NEG_Y", _normalize_vector((0.0, transverse, -longitudinal))),
        ("SP_FROM_POS_Y", _normalize_vector((0.0, -transverse, -longitudinal))),
    ]


def _get_beam_directions(profile):
    layout = profile.get("beam_layout")
    if layout == "angled_xz_y":
        theta_deg = float(profile.get("xz_angle_from_z_deg", 30.0))
        return _angled_xz_y_directions(theta_deg)
    if layout == "angled_green_yz_single_pass":
        green_directions = _angled_xz_y_directions(
            float(profile.get("xz_angle_from_z_deg", 30.0))
        )
        blue_directions = _single_pass_yz_directions(
            float(profile["blue_crossing_angle_deg"])
        )
        return [*green_directions, *blue_directions]
    raise ValueError(f"Unsupported 3D-MOT beam layout '{layout}'.")


def _validate_profile(profile):
    """Reject incomplete or internally inconsistent 3D-MOT profiles."""
    required = {"beam_layout", "center_position_m", "399", "556"}
    missing = sorted(required.difference(profile))
    if missing:
        raise ValueError(f"3D-MOT profile is missing required keys: {missing}")

    center = np.asarray(profile["center_position_m"], dtype=float)
    if center.shape != (3,) or not np.all(np.isfinite(center)):
        raise ValueError("3D-MOT center_position_m must be a finite 3-vector.")

    layout = profile["beam_layout"]
    if layout == "angled_xz_y":
        angle = profile.get("xz_angle_from_z_deg")
        if angle is None or not 0.0 < float(angle) < 90.0:
            raise ValueError(
                "Angled 3D-MOT profiles require 0 < xz_angle_from_z_deg < 90."
            )

    if layout == "angled_green_yz_single_pass":
        angle = profile.get("blue_crossing_angle_deg")
        if angle is None or not 0.0 < float(angle) < 180.0:
            raise ValueError(
                "Single-pass profiles require 0 < blue_crossing_angle_deg < 180."
            )
        offset = profile.get("blue_crossing_z_offset_m")
        if offset is None or not np.isfinite(offset) or float(offset) >= 0.0:
            raise ValueError(
                "Single-pass profiles require a finite negative "
                "blue_crossing_z_offset_m."
            )

    strong_axis = profile.get("magnetic_strong_axis", "z")
    if strong_axis not in {"x", "y", "z"}:
        raise ValueError("3D-MOT magnetic_strong_axis must be x, y, or z.")

    separation = profile.get("blue_green_center_separation_m", 0.0)
    if separation is None:
        raise ValueError(
            "Set blue_green_center_separation_m in config.py before using "
            "the angled_sequential 3D-MOT profile."
        )
    if float(separation) < 0.0:
        raise ValueError("blue_green_center_separation_m must be non-negative.")

    for wavelength_key in ("399", "556"):
        component = profile[wavelength_key]
        for key in ("enabled", "s0", "profile"):
            if key not in component:
                raise ValueError(
                    f"3D-MOT {wavelength_key} component is missing '{key}'."
                )
        if "detuning_gamma" not in component:
            raise ValueError(
                f"3D-MOT {wavelength_key} component is missing 'detuning_gamma'."
            )
        if component["profile"] not in {
            "gaussian",
            "donut",
            "elliptical",
                "outer_clipped_gaussian",
                "upstream_planar_clipped_gaussian",
                "upstream_clipped_donut",
        }:
            raise ValueError(
                f"Unsupported 3D-MOT {wavelength_key} profile "
                f"'{component['profile']}'."
            )
        if component["profile"] == "elliptical":
            for key in ("waist_short_m", "waist_long_m"):
                if float(component.get(key, 0.0)) <= 0.0:
                    raise ValueError(
                        f"3D-MOT {wavelength_key} {key} must be positive."
                    )
        elif float(component.get("waist_m", 0.0)) <= 0.0:
            raise ValueError(f"3D-MOT {wavelength_key} waist_m must be positive.")

        if component["profile"] == "outer_clipped_gaussian":
            cutoff = component.get("outer_cutoff_radius_m")
            if cutoff is None or float(cutoff) <= 0.0:
                raise ValueError(
                    f"Set a positive {wavelength_key}.outer_cutoff_radius_m "
                    "for an outer-clipped Gaussian beam."
                )

        if component["profile"] == "upstream_planar_clipped_gaussian":
            exclusion = component.get("green_exclusion_radius_m")
            if exclusion is None or float(exclusion) <= 0.0:
                raise ValueError(
                    f"Set a positive {wavelength_key}.green_exclusion_radius_m "
                    "for an upstream planar-clipped Gaussian beam."
                )
            offset = np.asarray(component.get("center_offset_m"), dtype=float)
            if offset.shape != (3,) or not np.all(np.isfinite(offset)):
                raise ValueError(
                    f"Set a finite {wavelength_key}.center_offset_m 3-vector."
                )
            if offset[2] > -float(exclusion):
                raise ValueError(
                    "The blue crossing must lie on or upstream of its cutoff "
                    "plane: crossing_distance_m >= green_exclusion_radius_m."
                )

        polarization_by_axis = component.get("polarization_by_axis", {})
        invalid_polarizations = {
            axis_tag: handedness
            for axis_tag, handedness in polarization_by_axis.items()
            if handedness not in {"left", "right"}
        }
        if invalid_polarizations:
            raise ValueError(
                "3D-MOT polarization_by_axis values must be 'left' or 'right': "
                f"{invalid_polarizations}"
            )
        s0_by_axis = component.get("s0_by_axis", {})
        invalid_s0 = {
            axis_tag: value
            for axis_tag, value in s0_by_axis.items()
            if not np.isfinite(value) or float(value) <= 0.0
        }
        if invalid_s0:
            raise ValueError(
                "3D-MOT s0_by_axis values must be finite and positive: "
                f"{invalid_s0}"
            )

    blue = profile["399"]
    if blue["enabled"] and blue["profile"] in {"donut", "upstream_clipped_donut"}:
        cutoff = blue.get("inner_cutoff_radius_m")
        if cutoff is None or float(cutoff) <= 0.0:
            raise ValueError(
                "Set a positive 399.inner_cutoff_radius_m in config.py before "
                "using the center-blocked Gaussian 3D-MOT profile."
            )
    blue_groups = blue.get("beam_groups")
    if blue_groups is not None:
        if not isinstance(blue_groups, (list, tuple)) or not blue_groups:
            raise ValueError("399.beam_groups must be a non-empty sequence.")
        names = [group.get("name") for group in blue_groups]
        if any(not isinstance(name, str) or not name for name in names):
            raise ValueError("Every 399 beam group requires a non-empty name.")
        if len(set(names)) != len(names):
            raise ValueError("399 beam-group names must be unique.")
        valid_tags = {tag for tag, _ in _get_beam_directions(profile)}
        for group in blue_groups:
            tags = group.get("axis_tags")
            if not tags or not set(tags) <= valid_tags:
                raise ValueError(
                    f"Invalid axis_tags for 399 beam group {group['name']!r}."
                )
            if group.get("profile", blue.get("profile")) not in {
                "upstream_clipped_donut",
                "window_clipped_donut",
                "upstream_planar_clipped_gaussian",
            }:
                raise ValueError("Finite 399 beam groups require a planar-clipped profile.")

    if layout == "angled_green_yz_single_pass":
        components = profile.get("beam_components")
        if not isinstance(components, dict):
            raise ValueError("single_pass requires beam_components.")
        for axis_tag, _ in _get_beam_directions(profile):
            axis = components.get(axis_tag)
            if not isinstance(axis, dict):
                raise ValueError(f"Missing beam_components entry for {axis_tag}.")
            for key in ("399_enabled", "556_enabled"):
                if axis.get(key) not in (True, False):
                    raise ValueError(
                        f"Choose True or False for beam_components.{axis_tag}."
                        f"{key} before using single_pass."
                    )


def _beam_profile_center(profile, wavelength_key, base_center):
    base_center = np.asarray(base_center, dtype=float)
    center = base_center
    wavelength_cfg = profile.get(wavelength_key, {})
    if (
        wavelength_key == "399"
        and profile.get("beam_layout") == "angled_green_yz_single_pass"
    ):
        return center + np.array(
            [0.0, 0.0, float(profile["blue_crossing_z_offset_m"])]
        )
    if "center_offset_m" in wavelength_cfg:
        return center + np.asarray(wavelength_cfg["center_offset_m"], dtype=float)
    if profile.get("blue_green_center_separation_m", 0.0) == 0.0:
        return center.copy()
    if wavelength_key == "399":
        offset = -0.5 * profile["blue_green_center_separation_m"]
    else:
        offset = 0.5 * profile["blue_green_center_separation_m"]
    return center + np.array([0.0, 0.0, offset])


def _beam_polarization(wavelength_config, axis_tag):
    handedness = wavelength_config.get("polarization_by_axis", {}).get(
        axis_tag, "right"
    )
    if handedness == "right":
        return CircularRight()
    if handedness == "left":
        return CircularLeft()
    raise ValueError(
        f"Unsupported circular polarization '{handedness}' for axis {axis_tag}."
    )


def setup_3dmot_lasers(mot_3d_config=None, center_position=None, profile_name=None):
    """Build the active 3D-MOT beam geometry from a selected profile config.

    Detuning is intentionally not applied here. The selected profile is passed in
    from the configuration layer, where atom-light coupling and detuning are set
    in the atomsmltr configuration object.
    """
    if mot_3d_config is None:
        if profile_name is None:
            profile_name = ACTIVE_MOT_3D_CONFIGURATION
        mot_3d_config = MOT_3D_CONFIGURATIONS.get(profile_name)
        if mot_3d_config is None:
            available = ", ".join(sorted(MOT_3D_CONFIGURATIONS))
            raise ValueError(
                f"Unknown 3D-MOT profile '{profile_name}'. Available profiles: {available}"
            )
    elif profile_name is not None:
        selected_profile = MOT_3D_CONFIGURATIONS.get(profile_name)
        if selected_profile is not None and selected_profile is not mot_3d_config:
            raise ValueError(
                "Selected 3D-MOT profile object and profile_name disagree; "
                "pass one authoritative profile config only."
            )

    profile = mot_3d_config
    _validate_profile(profile)
    if center_position is None:
        center_position = profile["center_position_m"]
    center_position = np.asarray(center_position, dtype=float)
    blue_sat_W_m2 = BLUE_SATURATION_INTENSITY_MW_CM2 * 10.0
    beam_axes = _get_beam_directions(profile)

    def make_beam(
        wavelength,
        waist,
        peak_intensity,
        direction,
        tag,
        beam_center,
        profile_kind,
        polarization,
        inner_cutoff_radius=None,
        outer_cutoff_radius=None,
        maximum_lab_z_m=None,
        minimum_lab_z_m=None,
        waist_short=None,
        waist_long=None,
    ):
        if profile_kind == "donut":
            beam_cls = DonutGaussianBeam
        elif profile_kind == "upstream_clipped_donut":
            beam_cls = UpstreamClippedDonutGaussianBeam
        elif profile_kind == "window_clipped_donut":
            beam_cls = WindowClippedDonutGaussianBeam
        elif profile_kind == "outer_clipped_gaussian":
            beam_cls = OuterClippedGaussianBeam
        elif profile_kind == "elliptical":
            beam_cls = EllipticalLaserBeam
        elif profile_kind == "upstream_planar_clipped_gaussian":
            beam_cls = UpstreamPlanarClippedGaussianBeam
        else:
            beam_cls = CircularGaussianBeam
        beam_kwargs = dict(
            wavelength=wavelength,
            waist=waist,
            waist_position=beam_center,
            direction_type="vector",
            direction=direction,
            polarization=polarization,
            tag=tag,
        )
        if profile_kind in {"donut", "upstream_clipped_donut", "window_clipped_donut"}:
            beam_kwargs["inner_cutoff_radius"] = inner_cutoff_radius
            if profile_kind == "upstream_clipped_donut":
                beam_kwargs["maximum_lab_z_m"] = maximum_lab_z_m
            elif profile_kind == "window_clipped_donut":
                beam_kwargs["minimum_lab_z_m"] = minimum_lab_z_m
                beam_kwargs["maximum_lab_z_m"] = maximum_lab_z_m
        elif profile_kind == "outer_clipped_gaussian":
            beam_kwargs["outer_cutoff_radius"] = outer_cutoff_radius
        elif profile_kind == "elliptical":
            beam_kwargs.pop("waist")
            beam_kwargs["wx"] = waist_short
            beam_kwargs["wy"] = waist_long
        elif profile_kind == "upstream_planar_clipped_gaussian":
            beam_kwargs["maximum_lab_z_m"] = maximum_lab_z_m
        beam = beam_cls(**beam_kwargs)
        beam.profile_kind = profile_kind
        beam.set_power_from_peak_I(peak_intensity)
        return beam

    beams = []
    direction_by_tag = dict(beam_axes)
    blue_groups = profile.get("399", {}).get("beam_groups")
    for axis_tag, direction in beam_axes:
        beam_399_cfg = profile.get("399", {})
        beam_556_cfg = profile.get("556", {})
        axis_components = profile.get("beam_components", {}).get(axis_tag, {})

        enabled_399 = not blue_groups and beam_399_cfg.get("enabled", True) and axis_components.get(
            "399_enabled", True
        )
        enabled_556 = beam_556_cfg.get("enabled", True) and axis_components.get(
            "556_enabled", True
        )

        if enabled_399:
            axis_s0_399 = beam_399_cfg.get("s0_by_axis", {}).get(
                axis_tag, beam_399_cfg["s0"]
            )
            beam_center = _beam_profile_center(profile, "399", center_position)
            beams.append(
                make_beam(
                    wavelength=BLUE_TRANSITION.wavelength_m,
                    waist=beam_399_cfg.get("waist_m", 0.01),
                    peak_intensity=axis_s0_399 * blue_sat_W_m2,
                    direction=direction,
                    tag=f"3DMOT_399_{axis_tag}",
                    beam_center=beam_center,
                    profile_kind=beam_399_cfg["profile"],
                    polarization=_beam_polarization(beam_399_cfg, axis_tag),
                    inner_cutoff_radius=beam_399_cfg.get("inner_cutoff_radius_m"),
                    waist_short=beam_399_cfg.get("waist_short_m"),
                    waist_long=beam_399_cfg.get("waist_long_m"),
                    maximum_lab_z_m=(
                        center_position[2]
                        - beam_399_cfg.get("green_exclusion_radius_m", 0.0)
                    ),
                )
            )

        if enabled_556:
            axis_s0_556 = beam_556_cfg.get("s0_by_axis", {}).get(
                axis_tag, beam_556_cfg["s0"]
            )
            beam_center = _beam_profile_center(profile, "556", center_position)
            beams.append(
                make_beam(
                    wavelength=GREEN_TRANSITION.wavelength_m,
                    waist=beam_556_cfg["waist_m"],
                    peak_intensity=axis_s0_556 * GREEN_SATURATION_INTENSITY_W_M2,
                    direction=direction,
                    tag=f"3DMOT_556_{axis_tag}",
                    beam_center=beam_center,
                    profile_kind=beam_556_cfg["profile"],
                    polarization=_beam_polarization(beam_556_cfg, axis_tag),
                    outer_cutoff_radius=beam_556_cfg.get(
                        "outer_cutoff_radius_m"
                    ),
                )
            )

    if blue_groups:
        beam_399_cfg = profile["399"]
        for group in blue_groups:
            group_cfg = {**beam_399_cfg, **group}
            group_name = group_cfg["name"]
            beam_center = center_position + np.asarray(
                group_cfg.get("center_offset_m", (0.0, 0.0, 0.0)), dtype=float
            )
            maximum_lab_z_m = group_cfg.get(
                "maximum_lab_z_m",
                center_position[2] - group_cfg.get("green_exclusion_radius_m", 0.0),
            )
            for axis_tag in group_cfg["axis_tags"]:
                beams.append(
                    make_beam(
                        wavelength=BLUE_TRANSITION.wavelength_m,
                        waist=group_cfg["waist_m"],
                        peak_intensity=group_cfg["s0"] * blue_sat_W_m2,
                        direction=direction_by_tag[axis_tag],
                        tag=f"3DMOT_399_{group_name}_{axis_tag}",
                        beam_center=beam_center,
                        profile_kind=group_cfg["profile"],
                        polarization=_beam_polarization(group_cfg, axis_tag),
                        inner_cutoff_radius=group_cfg.get("inner_cutoff_radius_m"),
                        maximum_lab_z_m=maximum_lab_z_m,
                        minimum_lab_z_m=group_cfg.get("minimum_lab_z_m"),
                    )
                )

    return beams
