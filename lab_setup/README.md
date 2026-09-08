# lab_setup

The `lab_setup` package maps the physical apparatus into the simulation environment. It assembles the laser beams, magnetic-field objects, gravity force, and spatial boundaries used by the atomsmltr simulation.

## Role in the project

The apparatus model is broken into the following conceptual components:

- Zeeman slower field and laser
- 2D MOT laser geometry and quadrupole field
- downstream apparatus and transport zones
- optional 3D MOT field and lasers
- gravity and simulation boundary conditions

Thermal-beam initial conditions are generated separately in `simulations/thermal_beam.py`.

These parts are assembled by `config_builder.py` into an atomsmltr `Configuration` object.

## Key modules

### `config_builder.py`

This is the central factory for building a simulation environment. It calls the individual setup functions for the laser beams and magnetic fields, then combines them with gravity and optional spatial zones.

The function `build_base_config(...)` is the key entry point used by the main simulation scripts. It wires together:

- the atomic species
- the selected laser configuration
- the magnetic-field configuration
- gravity
- the relevant apparatus zones

This is how the abstract experimental model becomes a concrete atomsmltr environment.

### `zones.py`

Defines finite-cylinder zones and the stop/ignore conditions used to model the apparatus volume and the Zeeman slower region. These zones help keep atoms within the physical chamber geometry and enforce stopping conditions when atoms leave the valid region.

### `laser_setup_2d_mot.py`

Builds the 2D MOT laser beams. These are elliptical Gaussian beams arranged in the X/Y counter-propagating configuration used for 2D cooling.

### `zeeman_laser_setup.py`

Builds the Zeeman slower beam. It sets the beam direction, waist, polarization, and detuning for the slower.

### `laser_setup_3d.py`

Builds 3D MOT laser beams for the final capture region when applicable.

The 3D-MOT configuration is profile-based and selectable through `ACTIVE_MOT_3D_CONFIGURATION` in `config.py`. The supported experimental concepts are intentionally narrow and explicit:

- `angled_donut`: two xz axes at ±30° from z and one y axis. The coaxial beams are complementary at a 10-mm radius: the blue 399-nm Gaussian is exactly zero inside that radius and begins at the boundary, while the green 556-nm Gaussian is transmitted only inside the radius and is exactly zero from the boundary outward. Its quadrupole strong axis is `y`; both wavelengths use right-handed polarization on the xz pairs and left-handed polarization on the y pair. Force tests verify that the green core is restoring on both sides of all three lab axes
- `angled_sequential`: the crossed-beam scheme: a six-beam 556-nm MOT and two elliptical 399-nm slowing beams using the same ±30-degree xz axes as `angled_donut`, crossing 1 cm upstream of the MOT
- `five_beam_gravity`: gravity-assisted five-beam 556-nm geometry with the
  `-x` beam removed and the quadrupole strong axis along `x`. The unpaired
  upward `+x` direction is green only, with opposite helicity; enabling an
  unopposed broad-line 399-nm beam there would cause a large transverse kick.
  Four center-blocked 399-nm beams and four green beams occupy the two paired
  axes in the `yz` plane, rotated by 45° from atomic `+z`. Force tests verify
  longitudinal blue slowing, transverse cancellation, and green restoring
  force along all three lab axes including gravity.

For `angled_sequential`, parameter provenance is intentionally separated:

- **Directly reported by Plotkin-Swing et al. (2020):** two 399-nm crossed slowing beams; 45-degree beam angle relative to the atomic beam; crossing point 10 mm before the MOT center; 1/e^2 short-axis width of 1.5 mm; long ellipse axis oriented perpendicular to the top-down view and sized to match the MOT-beam height; optimized crossed-beam saturation parameter `sX = 0.3`; and crossed-beam detuning of approximately -42 MHz.
- **Geometry and sign-convention choices used by this implementation:** the xz axes use ±30 degrees from lab `z`, matching `angled_donut`; this is an intentional project geometry choice and differs from the paper's 45-degree value. Atoms propagate along lab `+z`, so both slowing beams have negative `z` propagation components; their transverse components are opposite; the ellipse long axis maps to lab `y`; its 10-mm waist follows from the approximately 2-cm MOT diameter used in the paper; the 556-nm MOT uses the same two orthogonal axes in the `xz` plane plus the `y` axis; and, for the configured field convention, the quadrupole strong axis is `y` with right-handed circular polarization on the `xz` pairs and left-handed circular polarization on the `y` pair. Force tests verify slowing, transverse cancellation, and restoring behavior on both sides of all three axes.
- **Provisional optimized operating point:** the currently adopted scan result is blue `s0 = 0.6`, blue `detuning_gamma = -1.65`, green `s0 = 5`, green `detuning_gamma = -10`, and magnetic gradient `10 G/cm`. The green `waist_m = 10 mm` remains a temporary geometry default. These are simulation-optimization choices rather than a fixed reproduction of the paper or laboratory-set values.

The polarization-corrected provisional retention point is blue `s0 = 1.5`,
blue `detuning_gamma = -3`, green `s0 = 30`, green
`detuning_gamma = -25`, and gradient `2.5 G/cm` for `angled_donut`; and blue `s0 = 1`, blue
`detuning_gamma = -2`, green `s0 = 10`, green `detuning_gamma = -20`, and
gradient `2.5 G/cm` for the force-corrected `five_beam_gravity`. Magnetic
gradients are profile-specific, and an explicit simulation argument may
override them for controlled studies. All of these numerical operating points
remain provisional and are not laboratory-set values. Every varied donut
parameter except blue detuning is on a current scan boundary, so expanded
optimization is still required.

The configuration plot shows separate short-axis and long-axis intensity cuts for the elliptical 399-nm beams. The other experimental concepts retain their own explicit configurable defaults; values from one profile must not be treated as finalized parameters for another.

### `mag_field_2d_mot.py`

Defines the 2D MOT quadrupole magnetic field model. This uses a custom permanent-magnet field representation that matches the simulation geometry.

### `mag_field_Zeeman.py`

Defines the Zeeman slower magnetic field distribution used to capture and slow the atomic beam.

### `_3d_mot_mag_field.py`

Defines the simpler 3D MOT magnetic-field generator used for the final-stage quadrupole field.

### `gravity.py`

Provides the constant gravity force object used by the simulation environment when gravity is enabled.

## How the pieces fit together

The project does not hardcode a single monolithic environment. Instead, `build_base_config(...)` assembles a configuration object from modular pieces:

- atomic species from `lab_setup/atom_species.py`
- laser beams from the laser setup modules
- magnetic fields from the field modules
- gravity from `gravity.py`
- spatial constraints from `zones.py`

That configuration is then passed to the atomsmltr simulation engine for integration.

## Atomic-data source and conventions

The Yb-171 mass and the 399-nm and 556-nm transition constants in `config.py` follow the tabulated Yb-171 reference data of Kroeze, Kristensen, and Pucher (2026). This includes the vacuum wavelengths, natural linewidths, saturation intensities, electronic `g_J` values, and the measured F=3/2 Zeeman coefficients.

The `Transition.lande_g` field stores the excited-state hyperfine `g_F`, obtained from the tabulated Zeeman coefficient `mu_B g_F / h`. The atomsmltr `J0J1Transition` approximation instead has excited model states with magnetic quantum numbers ±1. To reproduce the physical stretched-state shifts for F=3/2, `atom_species.py` therefore passes `(3/2)g_F` to that model. The tabulated `g_J` values are retained in `config.py` for provenance and consistency checks, but are not substituted directly for `g_F`.
