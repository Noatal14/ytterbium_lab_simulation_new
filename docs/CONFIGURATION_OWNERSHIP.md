# Configuration ownership and frozen baseline

Updated from the characterized UI architecture baseline at
`8bd42b97d8dd6e696561b2efa16667607261a6fc`.

This document records the configuration that the production code currently
resolves.  It is a characterization, not an endorsement of every value.  The
companion test, `tests/test_configuration_characterization.py`, makes changes
to this baseline deliberate and reviewable.

## Ownership model

| Domain | Authoritative definitions | Principal consumers | Change rule |
| --- | --- | --- | --- |
| Versioned laboratory identity | `lab_setup/specifications/laboratory_physical_v1.json`, strictly loaded by `lab_setup/physical_specification.py` | `config.py`, Zeeman generation, campaign defaults, characterization tests | New reviewed specification version for laboratory changes |
| Atomic constants and transitions | `config.py`: `YB171`, `BLUE_TRANSITION`, `GREEN_TRANSITION`, saturation intensities | `lab_setup/atom_species.py`, force and laser setup modules | Scientific review; preserve SI units |
| Apparatus geometry | `config.py`: `Geometry`, `ZEEMAN_BEAM_DIRECTION` | `lab_setup/zones.py`, `lab_setup/config_builder.py`, laser and magnetic-field setup modules | Laboratory-change review |
| Zeeman slower | `config.py`: `ZEEMAN_MAGNET_PROFILES`, `ACTIVE_ZEEMAN_MAGNET_PROFILE`, `ZEEMAN_FIELD_CONFIG`, `ZEEMAN_LASER_CONFIG`, `ZEEMAN_SIM_CONFIG` | `lab_setup/config_builder.py`, `lab_setup/zeeman_laser_setup.py`, `simulations/zeeman.py`, `studies/zeeman/*` | Profile identity and generated ensembles must change together |
| Generic 2D MOT defaults | `config.py`: `MOT_2D_*`, `FORCE_SCALE_N`; search bounds in `studies/mot_2d/optimization.py` | `simulations/mot_2d.py`, studies, and executable campaign design | Scientific review |
| Executable 2D campaign science | `workflow_api/mot_2d_spec.py`: `ROLE_SEEDS`, `RELEVANT_FILES`, `FIXED_DESIGN`; orchestration constants in `studies/mot_2d_s0_campaign.py` | Campaign planner, runner, repository snapshot | Campaign design/provenance review |
| Versioned 2D UI/job contract | `workflow_api/specifications/mot_2d_v1.json`, validated by `workflow_api/mot_2d_specification.py` | UI mutation and Zeus transfer presentation | Contract/schema review and generated-artifact verification |
| 3D MOT | `config.py`: `MOT_3D_CONFIGURATIONS`, `MOT_3D_OPTIMIZATION_CONFIG`, `MOT_3D_SIM_CONFIG`, `MOT_3D_CAPTURE_CONFIG` | `lab_setup/laser_setup_3d.py`, `simulations/mot_3d.py`, `studies/mot_3d_campaign.py`, `studies/mot_3d/**` | Scientific review and new campaign identity |
| Full-pipeline numerics | `config.py`: `FULL_SIM_CONFIG`, `DEFAULT_NUM_*`, `DEFAULT_RANDOM_SEED` | `simulations/pipeline.py`, simulation entry points and studies | Numerical validation |
| Campaign serialization and provenance | `workflow_api/mot_2d_spec.py`, `studies/mot_2d_s0_campaign.py`, `studies/mot_3d_campaign.py`, `utils/file_helpers.py` | Generated manifests, PBS files, merge/final-report stages | Schema/design changes require regression tests; manifests freeze exact runs |

There is no single configuration source for the whole system.  The versioned
laboratory specification owns stable physical identity and the canonical
Zeeman array; `config.py` owns the remaining reusable physical/numerical defaults;
`workflow_api/mot_2d_spec.py` owns executable 2D campaign science; and the
versioned JSON owns the UI/job presentation contract.  These authorities
deliberately overlap in solver, timestep, trial-budget, and scheduling fields.
The characterization tests require exact agreement wherever they overlap so
drift fails loudly.  A campaign manifest then freezes the values used by one
concrete run.  Documentation explains intent but is not executable authority.

## Unit contract

SI is the default.  Names make exceptions or dimensions explicit:

- `_M`, `_S`, `_KG`, `_N`, `_W_M2`, and `_RAD_S` mean metres, seconds,
  kilograms, newtons, watts per square metre, and radians per second.
- `_G_CM`, `_KHZ_PER_G`, `_MW_CM2`, `_DEG`, and `_C` explicitly denote the
  retained non-SI laboratory units.
- `s0`, `detuning_gamma`, probabilities, relative intensities, seed values,
  counts, and trial budgets are dimensionless.
- A Gaussian `waist_m` is a 1/e^2 radius.  A hard optical boundary is named
  `*_aperture_radius_m` or `*_cutoff_radius_m`; it is not a beam diameter.

## Characterized production baseline

The normalized baseline includes all exported physical constants, atom and
transition records, all uppercase `Geometry` fields, the resolved Zeeman beam
direction, oven/source settings, every stored Zeeman profile, complete 2D and
3D configuration trees, `FULL_SIM_CONFIG`, runtime defaults, executable 2D
campaign design, the complete versioned 2D UI/job contract, and 3D campaign
seed/round defaults.  Canonical sorted JSON for this payload has SHA-256
`e687fab3bcac25721c4b4d03ae826d837b88a05af275924797d1cb57e6b50578`.

- 2D production timestep: `0.625 us`; 2D campaign working timestep:
  `1.25 us`; solver: `RK4StHybridCustom`.
- 3D screening/production/reference timesteps: `1.25 us`, `0.625 us`, and
  `0.3125 us`.  Candidate validation grid: `10, 5, 2.5, 1.25, 0.625 us`.
- Active 3D presentation configuration: `angled_donut`; the campaign still
  evaluates both `angled_donut` and `single_pass`.
- 2D sealed-validation Zeeman seeds: `3015..3034`.  The 3D handoff expects
  those same 20 seeds, split 12/4/4 for discovery/refinement/preliminary
  checking.  Final 3D validation reserves Zeeman seeds `3035..3054` and MOT
  seeds `43035..43054`.
- Critical campaign code is included in each campaign's physical-model hash;
  the 3D closure additionally includes Python sources under `lab_setup/`,
  `simulations/`, `utils/`, and `atomsmltr/src/atomsmltr/`.

## Canonical Zeeman profile and historical readability

The scientific decision is now explicit: the only active generic default is
`corrected_projectant_19ring_20261005`, with 19 radii, positions, and tilts and
canonical-array SHA-256
`7159e48b25124c3083b0dfa004f07bfdad8ad1aa6ae840a7bae1db970ab7d534`.
The complete normalized laboratory specification has SHA-256
`8a5fb876dce0825c7cc9154d1a0f0fb4ba01fe9d179e052e747a201246dcd0ab`.
The mistaken 20-ring profile formerly named `active` is absent from
`ZEEMAN_MAGNET_PROFILES` and cannot be selected for a new run.

Historical manifests and metadata are not rewritten.  The versioned contract
records the retired name and array hash, and the historical full-thermal
reader recognizes that exact embedded-array hash as `active`.  This is a
read-only compatibility path: it does not expose the removed field to any
simulation entry point.

New full-thermal runs write by default to
`data/validation/zeeman/full_thermal_flux_corrected_projectant_19ring_20261005_v1`.
The old `full_thermal_flux_v1` directory is therefore readable for historical
summaries without being a destination for new canonical results.

## Direct consumer inventory

This ledger is scoped to non-test Python files that directly import `config`.
It was generated from the Python AST, and the test suite regenerates it and
requires exact set equality.  Transitive consumers are deliberately outside
this ledger and are covered by campaign physical-model closures.

- Presentation: `graphs_scripts/mot_3d_velocity_style.py`,
  `graphs_scripts/plot_3d_mot_configurations.py`.
- Apparatus construction: `lab_setup/_3d_mot_mag_field.py`,
  `lab_setup/atom_species.py`, `lab_setup/config_builder.py`,
  `lab_setup/laser_setup_2d_mot.py`, `lab_setup/laser_setup_3d.py`,
  `lab_setup/zeeman_laser_setup.py`, `lab_setup/zones.py`.
- Simulation stages: `simulations/mot_2d.py`, `simulations/mot_3d.py`,
  `simulations/pipeline.py`, `simulations/thermal_beam.py`,
  `simulations/zeeman.py`.
- Beam-source studies: `studies/beam_source/estimate_oven_flux.py`,
  `studies/beam_source/full_thermal_flux.py`.
- 2D studies and campaign: `studies/mot_2d/optimization.py`,
  `studies/mot_2d/production.py`,
  `studies/mot_2d/validation/photon_counts.py`,
  `studies/mot_2d_s0_campaign.py`.
- 3D studies and campaign: `studies/mot_3d_campaign.py`,
  `studies/mot_3d/analysis/retention.py`,
  `studies/mot_3d/discovery/optimize.py`,
  `studies/mot_3d/discovery/select.py`, `studies/mot_3d/finalists/run.py`,
  `studies/mot_3d/preliminary/run.py`, `studies/mot_3d/refinement/run.py`,
  `studies/mot_3d/refinement/select.py`,
  `studies/mot_3d/refinement/select_closure.py`,
  `studies/mot_3d/timestep_validation.py`,
  `studies/mot_3d/validation/single_pass_stability.py`.
- Zeeman studies: `studies/zeeman/capture_velocity.py`,
  `studies/zeeman/generate_ensembles.py`,
  `studies/zeeman/stochastic_convergence.py`,
  `studies/zeeman/trajectories.py`,
  `studies/zeeman/validate_configuration.py`.
- Shared runtime helper: `utils/simulation_helpers.py`.

The same AST characterization freezes the two additional direct-consumer
ledgers:

- Executable `workflow_api.mot_2d_spec`: `studies/mot_2d_s0_campaign.py`,
  `workflow_api/mot_2d_plan.py`, `workflow_api/repository_snapshot.py`.
- Versioned `workflow_api.mot_2d_specification`:
  `tools/verify_mot_2d_specification.py`, `workflow_api/mutation.py`,
  `workflow_api/zeus_transfer.py`.
