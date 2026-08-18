import numpy as np
from lab_setup.zeeman_laser_setup import CircularGaussianBeam
from atomsmltr.environment.lasers.polarization import CircularRight
from config import BLUE_TRANSITION, GREEN_TRANSITION, BLUE_CALCULATED_SATURATION_INTENSITY_W_M2, GREEN_SATURATION_INTENSITY_W_M2

def setup_3dmot_lasers(
    center_position=(0.0, 0.0, 0.0),
    s0_399=0.5,
    detuning_gamma_399=-1.0,
    waist_399=0.01,
    enabled_399=True,
    s0_556=5.0,
    detuning_gamma_556=-10.0,
    waist_556=0.015,
    enabled_556=True,
    atom_species_name="Yb171"
):
    """
    Set up the proposal-grounded 3D MOT beam geometry.

    The proposal describes the 3D MOT as three orthogonal pairs of
    counter-propagating beams and later adds a 556 nm narrow-line core MOT.
    We therefore build six orthogonal beam directions (±X, ±Y, ±Z), with
    optional overlapping 399 nm and 556 nm beams on each axis.
    """
    del detuning_gamma_399, detuning_gamma_556, atom_species_name

    center_position = np.asarray(center_position, dtype=float)
    peak_intensity_399 = s0_399 * BLUE_CALCULATED_SATURATION_INTENSITY_W_M2
    peak_intensity_556 = s0_556 * GREEN_SATURATION_INTENSITY_W_M2

    beams = []

    beam_axes = [
        ("+X", (1.0, 0.0, 0.0)),
        ("-X", (-1.0, 0.0, 0.0)),
        ("+Y", (0.0, 1.0, 0.0)),
        ("-Y", (0.0, -1.0, 0.0)),
        ("+Z", (0.0, 0.0, 1.0)),
        ("-Z", (0.0, 0.0, -1.0)),
    ]

    # Because atomsmltr defines circular polarization in each beam's own
    # propagation frame, using the same handedness on a counter-propagating pair
    # produces opposite helicity in the lab frame.
    polarization = CircularRight()

    def make_beam(wavelength, waist, peak_intensity, direction, tag):
        beam = CircularGaussianBeam(
            wavelength=wavelength,
            waist=waist,
            waist_position=center_position,
            direction_type="vector",
            direction=direction,
            polarization=polarization,
            tag=tag,
        )
        beam.set_power_from_peak_I(peak_intensity)
        return beam

    for axis_tag, direction in beam_axes:
        if enabled_399:
            beams.append(
                make_beam(
                    wavelength=BLUE_TRANSITION.wavelength_m,
                    waist=waist_399,
                    peak_intensity=peak_intensity_399,
                    direction=direction,
                    tag=f"3DMOT_399_{axis_tag}",
                )
            )

        if enabled_556:
            beams.append(
                make_beam(
                    wavelength=GREEN_TRANSITION.wavelength_m,
                    waist=waist_556,
                    peak_intensity=peak_intensity_556,
                    direction=direction,
                    tag=f"3DMOT_556_{axis_tag}",
                )
            )

    return beams
