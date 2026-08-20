# dt_comparison

This directory contains exploratory and archival work used to compare simulation settings and timestep choices.

It is not part of the normal production workflow.

## Why this directory exists

The code here was used to investigate how different timestep choices, force normalizations, and stochastic/numerical parameters affected the results. It is useful for understanding numerical sensitivity, but it was not intended to become the main runtime entry point for the project.

## Typical contents

- `main.py` — script-level entry point for comparison work
- `consts.py` — local constant definitions used by the investigation scripts
- `find_f_min/` — force-threshold and force-scale investigations related to timestep selection
- `find_N_min/` — investigation used to choose the minimum scattering-count regime / validity threshold for the stochastic approximation
- `graphs/` — plots and graph-related outputs from the numerical investigations
- `data/` — experiment-specific data used by the analysis scripts

## Important note

This directory may not follow the same config refactor conventions as the main production code. Its scripts are historical and exploratory by design.

Do not treat `dt_comparison/` as the canonical workflow. For active simulation and reproducible production runs, use the stage modules under `simulations/` and the central configuration in `config.py`.
