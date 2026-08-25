# Project handoff: Yb-171 laser-cooling simulation

Last updated: 2026-08-19

## 1. Purpose and scientific context

This repository simulates the atomic-source and laser-cooling chain of the
planned Technion Yb-171 apparatus:

```text
thermal beam -> Zeeman slower -> 2D MOT -> science region / 3D MOT
```

The broader experimental program aims to load Yb-171 atoms into optical
tweezers and eventually realize fully confined atomic interferometry. This
repository does **not** simulate that complete interferometer. Its role is to
provide a useful and trustworthy model of the upstream apparatus, estimate
atomic transmission and capture, optimize experimentally adjustable operating
parameters, and help guide laboratory design decisions.

There is no single final numerical target because the laboratory is still being
designed. A useful result is often a robust operating region with realistic
experimental tolerances, rather than the single best simulated point.

The physical design status described in this handoff is project-level context:
the source, Zeeman slower, 2D MOT, vacuum system, and downstream apparatus through
the science region are largely selected designs. The current repository
configuration is authoritative for what the simulation actually implements,
while curated `data/` is authoritative for accepted simulation results. If the
implementation appears inconsistent with a supposedly fixed apparatus parameter,
do not silently change either one; document the discrepancy and ask which value
reflects the latest laboratory design.

## 2. Current scientific status

The apparatus through the Zeeman slower and 2D MOT is largely defined at the
physical and geometrical design level. Selected designs include the source,
Zeeman slower, permanent-magnet 2D MOT, differential-pumping system, vacuum
apparatus, and 399-nm optical layout. Parameters explicitly selected for an
optimization study are exceptions; they should not be mistaken for arbitrary
geometry.

The 3D MOT is **not a finalized laboratory design**. Integration of the 556-nm
cooling stage and optimization of transfer into the science chamber are future
experimental work. Its current implementation is therefore a runnable design
framework intended for exploration. Its geometry, laser parameters,
magnetic-field choices, and capture criterion are provisional unless clearly
documented otherwise.

Current work has concentrated on the Zeeman-slower-to-2D-MOT chain. Zeeman
survivor states are saved and reused as a fixed input ensemble for many 2D-MOT
simulations. This makes parameter comparisons both practical and scientifically
cleaner, because every 2D-MOT configuration can start from the same particles.

## 3. Parameter categories

When reading `config.py`, distinguish the following categories. A value appearing
in the configuration file is not, by itself, proof that it is experimentally
final. Confirm the current laboratory-design status before changing a physical
design parameter.

### 3.1 Fixed apparatus and physical parameters

These should reflect the planned laboratory and should not be optimized without
an explicit scientific reason:

- Yb-171 atomic properties and relevant transitions;
- oven/source geometry and source conditions;
- vacuum and apparatus geometry;
- Zeeman-arm, slower, laser, and magnetic-field geometry;
- 2D-MOT chamber and laser geometry;
- science-arm geometry, apertures, and differential-pumping section;
- fixed wavelengths, beam directions, and waists specified by the design.

### 3.2 Numerical simulation parameters

These include timestep, number of simulated particles, solver choice, stochastic
mode, random seed, worker count, and convergence settings. They require numerical
validation and are not laboratory controls.

### 3.3 Experimentally adjustable 2D-MOT parameters

The main optimization variables have been:

- saturation parameter `s0`;
- detuning in units of the transition linewidth, `detuning_gamma`;
- effective magnet radius and its corresponding magnetic-field configuration.

The experimentally relevant laser-intensity range is approximately `s0 <= 1.5`.
Results at `s0 = 1.6` or from older searches extending toward `s0 = 2` are useful
exploration, but may not represent achievable operating points.

### 3.4 Provisional 3D-MOT parameters

The entire 3D-MOT design should currently be treated as provisional. The current
operational capture definition is also provisional. An atom is classified as
captured when it:

- finishes within the configured radius of the 3D-MOT center;
- has remained there continuously for the configured final residence time;
- finishes below the configured maximum speed.

The exact values are centralized in `MOT_3D_CAPTURE_CONFIG` in `config.py`. They
are intended to be tested and revised, not cited as established experimental
criteria.

## 4. Code architecture and stage contracts

`config.py` is the single source of truth for physical configuration and runtime
defaults. Avoid unexplained constants in simulation scripts.

The production workflow is deliberately split into three stages:

1. `simulations/zeeman.py`
   - generates a new thermal-beam ensemble;
   - propagates it through the Zeeman stage;
   - saves the Zeeman survivor states.

2. `simulations/mot_2d.py`
   - loads any compatible saved `(N, 6)` particle-state array;
   - runs the 2D-MOT stage;
   - saves states that reach the downstream capture region for use by the 3D MOT.

3. `simulations/mot_3d.py`
   - loads a saved particle-state ensemble;
   - runs the provisional 3D-MOT configuration;
   - applies the configured capture criterion;
   - saves captured states and a JSON summary containing the capture percentage.

Particle states use SI units and the column order:

```text
x, y, z, vx, vy, vz
```

`simulations/pipeline.py` retains the former combined workflow. New code should
import the appropriate stage module directly. `studies/` contains research
workflows built on those stages, while `dt_comparison/` is an archive of numerical
investigations and is not the normal production entry point.

## 5. Running the stages locally

Set up Python 3.12 and the local `atomsmltr` package as described in `README.md`.
The default stage sequence is:

```bash
python -m simulations.zeeman
python -m simulations.mot_2d
python -m simulations.mot_3d
```

Each script exposes `--help`. Before a large run, verify the input and output
paths, number of particles, timestep, stochastic setting, seed, and `npools`.

The stage outputs default to:

```text
data/particle_states/after_zeeman/
data/particle_states/after_2d_mot/
data/particle_states/after_3d_mot/
```

Accepted Optuna summaries and stochastic-seed results belong under:

```text
data/optimization/
data/optimization/seed_scan/
```

## 6. Data authority and provenance

The project convention is:

> `data/` contains accepted, scientifically valid simulation results.

Known-invalid, obsolete, or bug-affected results are deleted rather than kept
beside accepted data. In particular, a historical seed-forwarding bug in
`mot_simulation` has been fixed, and affected outputs were already removed. Do
not mark the current `data/` directory as suspect merely because old debugging
logs mention this bug.

Terminal output, PBS stdout/stderr, development scripts, and discussion history
are useful diagnostics but do not have the same authority as curated results in
`data/`.

For every important new dataset, preserve enough provenance to reconstruct it:

- code commit;
- input state file;
- physical configuration or changed parameters;
- timestep and solver mode;
- number of input particles;
- random seed or seed range;
- optimization search space and number of trials.

Accepted `.npy` particle-state ensembles are versioned scientific inputs and
should be committed with adjacent provenance metadata. If a future ensemble is
too large for ordinary Git, use Git LFS or documented external storage; do not
leave a required downstream input only on Zeus without recording its location
and generation parameters.

## 7. 2D-MOT optimization

The current production strategy uses
`python -m studies.optimize_2d_mot_joint` to optimize `s0`, detuning, and magnet
radius simultaneously. Fixed-`s0` scripts are historical and should not be used
for the new campaign. First validate the 2D-MOT timestep with
`python -m studies.mot_2d_timestep_convergence`.

All candidate points must use the same Zeeman production ensembles, the same
particle subsets, and the same MOT seeds. Use cheap paired screening first and
reserve full ensembles and adaptive confidence-interval stopping for finalists.

Do not interpret only the highest Optuna trial. The desired scientific output is
a recommendation that includes:

- the best or near-best operating region;
- predicted capture efficiency;
- realistic detuning and magnet-setting ranges;
- dependence on available laser intensity;
- regions achieving, for example, 98-99% of the predicted maximum.

Optuna studies may use SQLite storage so a study can continue across jobs. Avoid
allowing multiple jobs to create or initialize the same SQLite database at the
same time; this previously caused a race. Confirm storage paths and initialization
strategy before launching a PBS array.

## 8. Stochastic uncertainty

Photon-scattering recoil is stochastic. Small differences between nearby
configurations may therefore reflect random realization noise rather than a
meaningful physical difference.

`python -m studies.mot_seed_scan` is a legacy single-ensemble uncertainty check.
For final conclusions, repeat the same physical 2D-MOT configuration across
the accepted per-seed Zeeman production ensembles and matching MOT seeds. The
legacy command repeats the configuration with different
random seeds. Use the resulting distribution of captured counts or efficiencies
to estimate stochastic uncertainty. Report this uncertainty when comparing close
optimization points or defining a robust near-optimal region.

## 9. Zeus HPC workflow

Heavy simulations run on the Technion Zeus cluster. The normal workflow is:

```text
local edit/test
    -> git commit and push
    -> Zeus git pull
    -> activate the atomsmltr environment
    -> inspect and submit a PBS job
    -> monitor stdout/stderr and qstat
    -> write accepted results under data/
    -> commit and push results
    -> pull and analyze locally
```

PBS files are generally stored in the user's Zeus home directory rather than in
this repository. Recent examples include `~/mot_optimization.pbs` and
`~/mot_fixed_s0_fine_array.pbs`, but filenames are not a stable interface.

Large optimization jobs commonly use one 80-core node with `npools = 80`.
Before submission, inspect the PBS file and verify:

- Python entry point and arguments;
- requested CPUs and matching `npools`;
- trial count;
- PBS array values, if applicable;
- walltime and memory;
- input, output, and Optuna storage paths.

Typical commands are:

```bash
qsub <pbs_file>
qstat -t -u tal.noa
qstat -f <job_id>
```

The job must load the required Python module and activate the Zeus `atomsmltr`
virtual environment before running the repository script.

## 10. Current priorities

### A. Complete the scientific interpretation of the 2D-MOT optimization

Turn the accepted full and fixed-`s0` results into a clear recommendation of the
best and robust near-best operating regions within the experimentally relevant
intensity range.

### B. Quantify stochastic uncertainty

Run repeated seeds for important physical configurations and determine whether
differences between nearby operating points exceed stochastic variation.

### C. Produce reproducible final figures

Plotting scripts should read accepted files directly from `data/`, not manually
copied arrays. Important outputs include full and fixed-`s0` optimization maps,
near-optimal regions, uncertainty results, and relevant convergence figures.
Save figures systematically under `graphs/`.

### D. Consolidate numerical validation

Summarize the evidence supporting production timestep, particle count, and
stochastic/numerical choices. Preserve `dt_comparison/` as provenance, but create
a concise explanation of the conclusions for future users.

### E. Maintain the architecture and documentation

Keep configuration centralized, stage boundaries explicit, data organized, and
important scripts documented. Changes to the physical apparatus should normally
be made through the configuration system rather than by rewriting stage logic.

## 11. Guidance for a future student or AI assistant

Before changing code or interpreting results:

1. Read `README.md`, this file, `data/README.md`, and `lab_setup/README.md`.
2. Inspect `config.py` and identify which parameter category a proposed change
   belongs to.
3. Do not treat provisional 3D-MOT values as finalized design choices.
4. Treat current curated `data/` results as valid unless new concrete evidence
   demonstrates a problem.
5. Preserve reproducibility and do not overwrite accepted datasets silently.
6. Test locally before submitting expensive Zeus jobs.
7. Prefer experimentally robust regions over overinterpreting a single optimum.

When scientific intent is unclear, ask before changing fixed apparatus geometry
or redefining a capture/survival criterion.
