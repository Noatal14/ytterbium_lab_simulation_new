# Configuration ownership and frozen baseline

Updated from the characterized UI architecture baseline at
`b74626f`.

This document records the configuration that the production code currently
resolves.  It is a characterization, not an endorsement of every value.  The
companion test, `tests/test_configuration_characterization.py`, makes changes
to this baseline deliberate and reviewable.

## Ownership model

| Domain | Authoritative definitions | Principal consumers | Change rule |
| --- | --- | --- | --- |
| Stable laboratory physics | `lab_setup/specifications/laboratory_physical_v2.json`, strictly loaded by `lab_setup/physical_specification.py` | Compatibility facade, apparatus construction, Zeeman generation, provenance | New reviewed version for changes to species, transitions, source, apparatus geometry, canonical 19-ring profile, measured Zeeman hardware, or Zeeman-laser geometry |
| Zeeman model conventions | `lab_setup/specifications/zeeman_model_conventions_v1.json`, strictly loaded by `lab_setup/physical_specification.py` | Magnetic-field and Zeeman-laser construction | New reviewed version for coordinate axes, tilt sign, azimuth sampling, or software construction tag/type; these are model semantics, not measured laboratory facts |
| Historical laboratory identity | Exact pinned `laboratory_physical_v1.json` version and SHA-256, loaded only through the explicit legacy path | Historical display/resume/readers | Read-only; never relabel or rewrite an existing artifact as v2 |
| Versioned numerical policy | `lab_setup/specifications/numerical_policy_v1.json`, strictly loaded by `lab_setup/numerical_policy.py` | `config.py` compatibility facade; simulations and campaigns consume the facade | Numerical convergence review and new policy version; no laboratory geometry or campaign budgets belong here |
| Compatibility facade | `config.py` exposes legacy public names and derives `g_F` and the model-effective factor from the v2 measured Zeeman coefficients | Existing simulation and study imports | Moved physical/model/numerical values must not be re-authored here; aliases and derived values must remain characterized |
| Zeeman operating point | `lab_setup/specifications/zeeman_operating_v1.json`, strictly loaded by `lab_setup/zeeman_operating_specification.py` | `config.py` compatibility facade, Zeeman engine/studies, individual-run plans | New reviewed version for the default laser s0/detuning or propagation start/cutoff; numerical values remain in numerical policy |
| Generic 2D MOT operating defaults | `lab_setup/specifications/mot_2d_operating_v1.json`, strictly loaded by `lab_setup/mot_2d_operating_specification.py` | `config.py` compatibility facade, generic stage engines/studies | New reviewed version for generic laser s0/detuning/polarization, magnet radius, or propagation start; not the individual UI or campaign authority |
| Remaining shared operating values | `config.py`: `FORCE_SCALE_N`; search bounds in `studies/mot_2d/optimization.py` | Simulation engines, studies, and executable campaign design | Scientific review; keep outside the generic 2D operating contract until separately migrated |
| Executable 2D campaign science | `workflow_api/mot_2d_spec.py`: `ROLE_SEEDS`, `RELEVANT_FILES`, `FIXED_DESIGN`; orchestration constants in `studies/mot_2d_s0_campaign.py` | Campaign planner, runner, repository snapshot | Campaign design/provenance review |
| Versioned 2D UI/job contract | `workflow_api/specifications/mot_2d_v1.json`, validated by `workflow_api/mot_2d_specification.py` | UI mutation and Zeus transfer presentation | Contract/schema review and generated-artifact verification |
| 3D MOT | `config.py`: `MOT_3D_CONFIGURATIONS`, `MOT_3D_OPTIMIZATION_CONFIG`, `MOT_3D_SIM_CONFIG`, `MOT_3D_CAPTURE_CONFIG` | `lab_setup/laser_setup_3d.py`, `simulations/mot_3d.py`, `studies/mot_3d_campaign.py`, `studies/mot_3d/**` | Scientific review and new campaign identity |
| Full-pipeline numerics | `config.py`: `FULL_SIM_CONFIG`, `DEFAULT_NUM_*`, `DEFAULT_RANDOM_SEED` | `simulations/pipeline.py`, simulation entry points and studies | Numerical validation |
| Campaign serialization and provenance | `workflow_api/mot_2d_spec.py`, `studies/mot_2d_s0_campaign.py`, `studies/mot_3d_campaign.py`, `utils/file_helpers.py` | Generated manifests, PBS files, merge/final-report stages | Schema/design changes require regression tests; manifests freeze exact runs |

There is no single configuration source for the whole system.  The v2
laboratory specification owns stable measured physical identity and the
canonical Zeeman array; the Zeeman model-conventions specification owns the
coordinate/sign/azimuth and software construction semantics; the
numerical-policy specification owns reusable solver, timestep, horizon, and
3D timestep-validation defaults; the generic 2D-MOT operating specification
owns only its reusable five-field baseline; `config.py` preserves the public
compatibility facade and owns only remaining reusable operating defaults;
`workflow_api/mot_2d_spec.py` owns executable 2D campaign science; and the
versioned JSON owns the UI/job presentation contract.  These authorities
deliberately overlap in solver, timestep, trial-budget, and scheduling fields.
The characterization tests require exact agreement wherever they overlap so
drift fails loudly.  A campaign manifest then freezes the values used by one
concrete run.  Documentation explains intent but is not executable authority.

Campaign working/final timesteps remain explicit campaign-design fields even
when their present values equal reusable defaults. Search bounds, seeds, trial
budgets, particle counts, and PBS resources are not numerical-policy fields.

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
`7ab56fadf365f6ec57d41860fa7ef4eaaf29f6e979aa16396bcbe378167ce74c`.

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
The active v2 laboratory specification has SHA-256
`1ef77eecdd306d2d92c08fde9897f283de57e741e9f1a45a6bc6c0063779eac3`.
The separate Zeeman model-conventions contract has SHA-256
`33913b023cae5775312d8f6f5b99ea0e7abdb5623a7bc8d6b02c92418835a7e8`.
The pinned read-only v1 laboratory identity has SHA-256
`8a5fb876dce0825c7cc9154d1a0f0fb4ba01fe9d179e052e747a201246dcd0ab`.
The mistaken 20-ring profile formerly named `active` is absent from
`ZEEMAN_MAGNET_PROFILES` and cannot be selected for a new run.

Historical manifests and metadata are not rewritten.  The pinned v1 contract
records the retired name and array hash, and the historical full-thermal
reader recognizes only that exact published identity.  This is a
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
- Individual-run admission: `workflow_api/zeeman_run_plan.py`,
  `workflow_api/zeeman_run_specification.py`.

The same AST characterization freezes these additional direct-consumer
ledgers:

- Versioned `lab_setup.zeeman_operating_specification`: `config.py`.

- Versioned `lab_setup.mot_2d_operating_specification`: `config.py`.

- Neutral `lab_setup.strict_specification`: the laboratory physical, numerical
  policy, Zeeman operating, and generic 2D-MOT operating loaders only.

- Versioned `lab_setup.numerical_policy`: `config.py`,
  `workflow_api/zeeman_run_plan.py`.

- Executable `workflow_api.mot_2d_spec`: `studies/mot_2d_s0_campaign.py`,
  `workflow_api/mot_2d_plan.py`, `workflow_api/repository_snapshot.py`.
- Versioned `workflow_api.mot_2d_specification`:
  `tools/verify_mot_2d_specification.py`, `workflow_api/mutation.py`,
  `workflow_api/zeus_transfer.py`.
