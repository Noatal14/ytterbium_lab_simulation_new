# lab_setup

The `lab_setup` package maps the physical apparatus into the simulation environment. It assembles the laser beams, magnetic-field objects, gravity force, and spatial boundaries used by the atomsmltr simulation.

## Role in the project

The apparatus model is broken into the following conceptual components:

- Zeeman slower field and laser
- 2D MOT laser geometry and quadrupole field
- downstream apparatus and transport zones
- optional 3D MOT field and lasers
- gravity and simulation boundary conditions

Thermal-beam initial conditions are generated separately in `thermal_beam.py`.

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

- `angled_concentric`: two xz axes at ±30° from z, one y axis, blue 399-nm annular/donut component plus green 556-nm central component
- `angled_sequential`: the same angled geometry, but with blue and green cooling regions separated along z by a configurable provisional offset
- `five_beam_gravity`: orthogonal geometry with the beam that would propagate in the downward -x direction removed; gravity still acts along -x, while the remaining +x beam propagates upward and can oppose gravity

The final experimental geometry is still under investigation, so the ring size, blue/green separation, and per-direction wavelength choices are kept as numeric provisional defaults rather than `None`. This keeps each profile runnable, directly editable, and easy to scan or optimize without changing the simulation logic.

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

- atomic species from `atom_species.py`
- laser beams from the laser setup modules
- magnetic fields from the field modules
- gravity from `gravity.py`
- spatial constraints from `zones.py`

That configuration is then passed to the atomsmltr simulation engine for integration.
