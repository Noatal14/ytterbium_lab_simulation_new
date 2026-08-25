import numpy as np
from lab_setup.zeeman_laser_setup import CircularGaussianBeam
from atomsmltr.environment.lasers.polarization import CircularRight
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
        wavelength=399e-9,
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


def _five_beam_gravity_directions():
    # Gravity acts along -x, but source position and propagation direction are not
    # the same quantity. A laser source physically above the MOT can still
    # propagate downward (-x), while the remaining upward beam is the +x
    # propagation direction that opposes gravity.
    #
    # The other two counter-propagating axes lie in the yz plane, perpendicular
    # to gravity. They are rotated by 45 degrees from the atomic +z transport
    # axis. The axes remain mutually orthogonal, but no beam is parallel or
    # antiparallel to the atomic transport direction.
    diagonal = 1.0 / np.sqrt(2.0)
    return [
        ("+X", _normalize_vector((1.0, 0.0, 0.0))),
        ("+YZ_1", _normalize_vector((0.0, diagonal, diagonal))),
        ("-YZ_1", _normalize_vector((0.0, -diagonal, -diagonal))),
        ("+YZ_2", _normalize_vector((0.0, -diagonal, diagonal))),
        ("-YZ_2", _normalize_vector((0.0, diagonal, -diagonal))),
    ]


def _get_beam_directions(profile):
    layout = profile.get("beam_layout")
    if layout == "angled_xz_y":
        theta_deg = float(profile.get("xz_angle_from_z_deg", 30.0))
        return _angled_xz_y_directions(theta_deg)
    if layout == "rotated_yz_minus_upper_x":
        return _five_beam_gravity_directions()
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
        for key in ("enabled", "s0", "detuning_gamma", "waist_m", "profile"):
            if key not in component:
                raise ValueError(
                    f"3D-MOT {wavelength_key} component is missing '{key}'."
                )
        if float(component["waist_m"]) <= 0.0:
            raise ValueError(f"3D-MOT {wavelength_key} waist_m must be positive.")
        if component["profile"] not in {"gaussian", "donut"}:
            raise ValueError(
                f"Unsupported 3D-MOT {wavelength_key} profile "
                f"'{component['profile']}'."
            )

    blue = profile["399"]
    if blue["enabled"] and blue["profile"] == "donut":
        cutoff = blue.get("inner_cutoff_radius_m")
        if cutoff is None or float(cutoff) <= 0.0:
            raise ValueError(
                "Set a positive 399.inner_cutoff_radius_m in config.py before "
                "using the center-blocked Gaussian 3D-MOT profile."
            )

    if layout == "rotated_yz_minus_upper_x":
        components = profile.get("beam_components")
        if not isinstance(components, dict):
            raise ValueError("five_beam_gravity requires beam_components.")
        for axis_tag, _ in _five_beam_gravity_directions():
            axis = components.get(axis_tag)
            if not isinstance(axis, dict):
                raise ValueError(f"Missing beam_components entry for {axis_tag}.")
            for key in ("399_enabled", "556_enabled"):
                if axis.get(key) not in (True, False):
                    raise ValueError(
                        f"Choose True or False for beam_components.{axis_tag}."
                        f"{key} before using five_beam_gravity."
                    )


def _beam_profile_center(profile, wavelength_key, base_center):
    base_center = np.asarray(base_center, dtype=float)
    center = base_center
    if profile.get("blue_green_center_separation_m", 0.0) == 0.0:
        return center.copy()
    if wavelength_key == "399":
        offset = -0.5 * profile["blue_green_center_separation_m"]
    else:
        offset = 0.5 * profile["blue_green_center_separation_m"]
    return center + np.array([0.0, 0.0, offset])


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
    peak_intensity_399 = profile["399"]["s0"] * blue_sat_W_m2
    peak_intensity_556 = profile["556"]["s0"] * GREEN_SATURATION_INTENSITY_W_M2
    beam_axes = _get_beam_directions(profile)

    # Because atomsmltr defines circular polarization in each beam's own
    # propagation frame, using the same handedness on a counter-propagating pair
    # produces opposite helicity in the lab frame.
    polarization = CircularRight()

    def make_beam(
        wavelength,
        waist,
        peak_intensity,
        direction,
        tag,
        beam_center,
        profile_kind,
        inner_cutoff_radius=None,
    ):
        beam_cls = DonutGaussianBeam if profile_kind == "donut" else CircularGaussianBeam
        beam_kwargs = dict(
            wavelength=wavelength,
            waist=waist,
            waist_position=beam_center,
            direction_type="vector",
            direction=direction,
            polarization=polarization,
            tag=tag,
        )
        if profile_kind == "donut":
            beam_kwargs["inner_cutoff_radius"] = inner_cutoff_radius
        beam = beam_cls(**beam_kwargs)
        beam.profile_kind = profile_kind
        beam.set_power_from_peak_I(peak_intensity)
        return beam

    beams = []
    for axis_tag, direction in beam_axes:
        beam_399_cfg = profile.get("399", {})
        beam_556_cfg = profile.get("556", {})
        axis_components = profile.get("beam_components", {}).get(axis_tag, {})

        enabled_399 = axis_components.get(
            "399_enabled", beam_399_cfg.get("enabled", True)
        )
        enabled_556 = axis_components.get(
            "556_enabled", beam_556_cfg.get("enabled", True)
        )

        if enabled_399:
            beam_center = _beam_profile_center(profile, "399", center_position)
            beams.append(
                make_beam(
                    wavelength=BLUE_TRANSITION.wavelength_m,
                    waist=beam_399_cfg["waist_m"],
                    peak_intensity=peak_intensity_399,
                    direction=direction,
                    tag=f"3DMOT_399_{axis_tag}",
                    beam_center=beam_center,
                    profile_kind=beam_399_cfg["profile"],
                    inner_cutoff_radius=beam_399_cfg.get("inner_cutoff_radius_m"),
                )
            )

        if enabled_556:
            beam_center = _beam_profile_center(profile, "556", center_position)
            beams.append(
                make_beam(
                    wavelength=GREEN_TRANSITION.wavelength_m,
                    waist=beam_556_cfg["waist_m"],
                    peak_intensity=peak_intensity_556,
                    direction=direction,
                    tag=f"3DMOT_556_{axis_tag}",
                    beam_center=beam_center,
                    profile_kind=beam_556_cfg["profile"],
                )
            )

    return beams
