# Yb-171 Laser-Cooling Simulation

This repository models a Yb-171 atomic beam and the downstream laser-cooling stages used to study a compact apparatus: a thermal source, a Zeeman slower, a 2D MOT, and, where applicable, a 3D MOT and transport region.

The code is primarily a simulation and analysis project for understanding how atoms move through the apparatus and how survival/capture depend on geometry, laser detuning, magnetic fields, and timestep choices.

## Project overview

The project simulates a neutral ytterbium beam produced from a thermal source, follows the atoms through a Zeeman slower, and then evaluates capture in the 2D MOT stage. The repository also contains models for the downstream apparatus and a 3D MOT stage, although the main production workflow currently focuses on the Zeeman slower and 2D MOT.

An important use of the repository is to study capture efficiency and optimize 2D-MOT operating parameters after fixing the upstream Zeeman-slower conditions.

The main conceptual sequence is:

1. Thermal beam generation from the oven/microcapillary source.
2. Zeeman slower phase, where atoms are slowed and filtered by the magnetic field and laser beam.
3. 2D MOT capture and confinement in the transverse cooling stage.
4. Transport through the apparatus / laboratory geometry.
5. Optional 3D MOT stage for the final capture region.

The code is built around a Yb-171 atom model with the relevant optical transitions and magnetic-field geometry defined in the central configuration module.

New contributors should also read `PROJECT_HANDOFF.md`. It records the scientific
status, parameter categories, data-authority convention, Zeus workflow, and
current priorities that cannot be inferred safely from code alone.

## Repository structure

- `config.py` — the single source of truth for physical constants, atomic parameters, geometry, laser settings, magnetic-field configuration, and runtime defaults.
- `simulations/` — stage engines for the thermal beam, Zeeman slower, 2D MOT, 3D MOT, and the compatibility pipeline.
- `studies/` — research workflows that use the stage engines for optimization and stochastic-seed analysis.
- `lab_setup/` — apparatus modeling: laser setup, magnetic-field setup, zones, gravity, and config assembly.
- `utils/` — shared numerical helper functions, time-grid generation, and simulation utilities.
- `graphs_scripts/` — plotting and graph-generation scripts for analysis and publication output.
- `data/` — reference data, optimization summaries, and generated survivor ensembles.
- `dt_comparison/` — archival exploratory work around timestep and stochastic/numerical investigations; not part of the normal production workflow.
- `atomsmltr/` — a local vendored copy of the external `atomsmltr` library used by the project.

## Configuration

`config.py` is the authoritative configuration location for the project. It defines:

- physical constants and unit conversions
- Yb-171 mass and optical transitions
- apparatus geometry
- oven source parameters
- Zeeman slower profiles and field configuration
- 2D MOT and 3D MOT configuration blocks
- laser settings and simulation defaults
- runtime defaults such as random seed and particle count

This project follows the refactored naming convention in `config.py` and expects active code to use the updated names instead of older aliases. The configuration module should be the first place to look when adjusting a simulation parameter. When changing the laboratory setup, prefer changing `config.py` rather than introducing stage parameters directly inside simulation scripts.

## How to run the simulation

The production workflow is split into three explicit stages. Each stage writes
an ensemble that can be inspected, reused, or replaced before running the next.

### 1) Generate and save Zeeman survivors

Before generating a survivor ensemble, validate the active field, laser,
polarization, and resonance conventions:

```bash
python -m studies.validate_zeeman_configuration
```

This writes a JSON audit and a four-panel diagnostic plot under
`data/validation/zeeman/`. A `REVIEW_REQUIRED` result must be understood before
starting convergence or production runs.

Then inspect a few deterministic, on-axis trajectories around the expected
capture velocity:

```bash
python -m studies.diagnose_zeeman_trajectories
```

This is a fast local physics diagnostic, not an estimate of capture efficiency.
It stores its report and plot under `data/validation/zeeman/trajectories/`.

To bracket the ideal on-axis capture velocity more precisely, run:

```bash
python -m studies.scan_zeeman_capture_velocity
```

Before a new production ensemble, validate the stochastic RK4 timestep with
several shared seeds. Each cluster task must write a separate result file:

```bash
python -m studies.zeeman_stochastic_convergence run \
  --n-atoms 5000 --dt-us 40 --seed 1000 --npools 80
```

After all timestep/seed jobs finish, aggregate them with:

```bash
python -m studies.zeeman_stochastic_convergence summarize
```

The summary reports the mean and 95% across-seed interval for every timestep,
plus same-seed comparisons against the finest timestep. The convergence jobs
must use a committed, clean working tree.

```bash
python -m simulations.zeeman --n_atoms 50000 --output data/particle_states/after_zeeman/zeeman_survivors.npy
```

This stage always starts from a newly generated thermal beam.

### 2) Run the 2D MOT from saved states

```bash
python -m simulations.mot_2d --input data/particle_states/after_zeeman/zeeman_survivors.npy --output data/particle_states/after_2d_mot/mot_2d_survivors.npy
```

Any compatible `(N, 6)` state array may be supplied as the input.

### 3) Run the 3D MOT and calculate capture

```bash
python -m simulations.mot_3d --input data/particle_states/after_2d_mot/mot_2d_survivors.npy
```

The 3D stage saves the captured states and a JSON summary containing the capture
percentage and exact criterion. Run any stage with `--help` to see its numerical
and file-path options.

## Recommended entry point

For a new user, the recommended entry points are the three stage scripts:

- `python -m simulations.zeeman`
- `python -m simulations.mot_2d`
- `python -m simulations.mot_3d`

The former combined workflow is available as `python -m simulations.pipeline`.
Existing Zeus PBS commands must be updated to the package-based entry points.

## Optimization

Before optimization, validate the 2D-MOT timestep with
`python -m studies.mot_2d_timestep_convergence`. The production optimizer is
`python -m studies.optimize_2d_mot_joint`; it jointly scans:

- `s0` (saturation parameter)
- `detuning_gamma`
- magnet radius

Every trial uses the same per-seed Zeeman production ensembles, deterministic
particle subsets, and MOT seeds. Candidate comparisons are therefore paired.
Screening results are stored under `data/optimization/mot_2d/`.
The optimizer accepts narrower follow-up domains through `--s0-bounds`,
`--detuning-bounds`, and `--magnet-radius-bounds-m`. Always use a new study
name and output directory when changing bounds or the statistical design.
After screening and refinement, `python -m studies.validate_2d_mot_candidates`
compares the shortlisted power/capture trade-offs on larger paired samples with
fresh MOT seeds. Its summary reports confidence intervals for the paired
efficiency differences and a 0.05-percentage-point noninferiority check.
Independent candidates can run concurrently through `--candidate-index 0`,
`1`, or `2`. After all candidate files exist, use `--summarize-only` to create
the shared paired-comparison summary without concurrent writes.
Local setting robustness is evaluated by
`python -m studies.validate_2d_mot_robustness`. It scans the full 3x3x3 box at
one provisional control step around the selected candidate and reports both
ordinary paired intervals and Bonferroni-adjusted simultaneous 95% intervals.

The older `studies.optimize_2d_mot` and fixed-`s0` scripts are retained only for
historical reproducibility and are not the recommended production workflow.

## Outputs and data

The project writes results into the `data/` directory.

New outputs are grouped under `data/particle_states/after_zeeman/`,
`data/particle_states/after_2d_mot/`,
`data/particle_states/after_3d_mot/`, and `data/optimization/`. See
`data/README.md` for the layout and file conventions.

The `graphs/` and `graphs_scripts/` directories are used for plotting and interpretation of these results.

## Reproducibility

The project keeps key default values in `config.py`, including the random seed and main simulation defaults. The current configuration uses explicit defaults such as a reproducible random seed and the main simulation timestep values from the config module.

For reproducibility, the most important things to preserve are:

- the selected Zeeman magnet profile in `config.py`
- laser detuning and saturation values in `config.py`
- simulation timing parameters in `config.py`
- the same random seed and particle-count defaults when re-running the same workflow

## atomsmltr

This repository contains a local copy of `atomsmltr` under the `atomsmltr/` directory. The project uses this local package as part of the simulation environment.

The exact upstream revision and the full set of project-specific modifications cannot be established confidently from the current working tree alone. For that reason, the checked-in `atomsmltr` directory should be treated as the version associated with this project rather than assumed to be identical to a particular upstream release.

## dt_comparison

The `dt_comparison/` directory is archival and exploratory. It contains investigation code around timestep choices, numerical checks, and force/step-size comparisons. It is not part of the normal production workflow and does not need to follow the same cleanup conventions as the main simulation scripts.

## Environment and dependency setup

This project relies on Python scientific libraries, plus the local vendored `atomsmltr` package.

### Recommended setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install -e ./atomsmltr
```

`requirements.txt` contains the core runtime dependencies for the project. The vendored `atomsmltr` package declares Python 3.12 in its metadata, and that is the safest supported version to use unless you have verified compatibility with another interpreter.

If the local `atomsmltr` package is not installed in editable mode, the project may need the repository root and/or `atomsmltr/src` on `PYTHONPATH` depending on how the environment is configured.

## Notes for future students

This repository is a research codebase rather than a polished end-user package. The main things to understand are:

- `config.py` is the source of truth
- the main workflow is split into Zeeman + MOT stages
- generated survivors are a key reusable artifact
- plotting and analysis scripts sit next to the simulation code
- exploratory work is intentionally separated from the main production workflow

The project is best understood by starting with `PROJECT_HANDOFF.md`, then reading
the three stage scripts, `config.py`, and the lab setup modules that define the
actual apparatus model.

## Possible future improvements

These are not implemented here, but they are reasonable ideas for later work:

- a cleaner user-facing CLI layer
- a single top-level orchestration script for major workflows
- a smaller set of curated example commands for common runs
- a dedicated analysis package for output post-processing

These ideas are intentionally left out of the current scope to keep the repository stable and low-risk.
