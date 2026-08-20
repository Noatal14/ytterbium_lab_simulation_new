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
- `zeeman_simulation.py` — generates a thermal beam, runs the Zeeman stage, and saves its survivors.
- `mot_2d_simulation.py` — loads saved states, runs the 2D MOT, and saves states for the 3D MOT.
- `mot_3d_simulation.py` — runs the 3D MOT, applies the capture criterion, and saves captured states and a summary.
- `split_simulation.py` — a thin compatibility wrapper for older combined commands and imports.
- `optimize_2d_mot.py` — Optuna-based optimization of 2D MOT parameters using saved Zeeman-survivor states.
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

```bash
python zeeman_simulation.py --n_atoms 50000 --output data/particle_states/after_zeeman/zeeman_survivors.npy
```

This stage always starts from a newly generated thermal beam.

### 2) Run the 2D MOT from saved states

```bash
python mot_2d_simulation.py --input data/particle_states/after_zeeman/zeeman_survivors.npy --output data/particle_states/after_2d_mot/mot_2d_survivors.npy
```

Any compatible `(N, 6)` state array may be supplied as the input.

### 3) Run the 3D MOT and calculate capture

```bash
python mot_3d_simulation.py --input data/particle_states/after_2d_mot/mot_2d_survivors.npy
```

The 3D stage saves the captured states and a JSON summary containing the capture
percentage and exact criterion. Run any stage with `--help` to see its numerical
and file-path options.

## Recommended entry point

For a new user, the recommended entry points are the three stage scripts:

- `zeeman_simulation.py`
- `mot_2d_simulation.py`
- `mot_3d_simulation.py`

`split_simulation.py` remains available so existing Zeus commands do not need
to change immediately.

## Optimization

`optimize_2d_mot.py` is an Optuna-based parameter search for the 2D MOT. It expects a fixed Zeeman-survivor dataset, then scans over values such as:

- `s0` (saturation parameter)
- `detuning_gamma`
- magnet radius

It reads the precomputed survivor file and maximizes a capture/success metric for the MOT stage. The script stores optimization summaries under `data/optimization/`; repeated-seed uncertainty results are grouped under `data/optimization/seed_scan/`.

The fixed-s0 companion script, `optimize_2d_mot_fixed_s0.py`, runs the same idea while holding one MOT parameter fixed and optimizing the others.

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
