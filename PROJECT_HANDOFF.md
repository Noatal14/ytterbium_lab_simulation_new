# Project handoff: Yb-171 laser-cooling simulation

Last updated: 2026-08-26

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

`studies/compare_3d_mot_retention.py` compares all 3D-MOT profiles using the
same saved 2D-MOT survivor states. For each profile it defines a cohort at the
peak population satisfying the configured radius, minimum continuous residence,
and maximum-speed capture criteria, then counts only atoms that remain inside
the sphere continuously. Its exponential-with-plateau `tau` is reported
only when the observed decay passes explicit loss and fit-quality checks; a
rejected fit must not be interpreted as a measured lifetime.
The JSON diagnostics distinguish failure to enter the capture sphere from
failure to slow or remain there long enough, and include distance, speed, and
continuous-residence distributions.
The 3D-MOT solver is selected centrally by `MOT_3D_SIM_CONFIG` and is currently
`RK4StHybridCustom`. Its fixed grid uses `dt_s=1e-5 s`; timestep suitability
must be rechecked if the 3D-MOT geometry or operating point changes. The hybrid stochastic recoil model uses exact Poisson
sampling at low expected scattering count and the Gaussian approximation at
high count.

`studies/scan_3d_mot_blue_slower.py` performs the preceding first-stage slowing
screen: it scans only 399-nm `s0` and detuning in Gamma on a shared ensemble and
seed. Green-light, field, geometry, and capture settings remain fixed. Its CSV,
JSON, and heatmaps rank points by capture, slowing, residence, and then median
minimum speed; magnetic-gradient scans should be restricted to promising blue
parameter regions found here.
The scan additionally reports per-point 399-nm exposure diagnostics using the
real beam profiles and lab-frame trajectories. The default exposure threshold
is 1% of the summed peak intensity; this is a diagnostic threshold, not a
capture criterion or laboratory-set parameter.
For center-blocked Gaussian beams, the normalization uses the physical ring
maximum immediately outside the hard inner cutoff; the intentionally dark beam
axis is not a valid peak-intensity reference.
For multi-node Zeus scans, use the scan's `--num-shards` and `--shard-index`
options. The global seeded `--max-atoms` selection happens before deterministic
strided sharding, and each shard receives a reproducible independent simulation
seed. Shards must write to separate output directories.
Merge completed shard directories with
`studies/merge_3d_mot_blue_scan_shards.py`. Count metrics are exact sums;
distribution outputs are deliberately labeled as summaries of shard medians.
After a coarse pilot, prefer `--parameter-pairs S0:DETUNING_GAMMA ...` so the
large validation run samples only the identified slowing ridge rather than the
full Cartesian product.
The targeted gradient validation selected the provisional operating point
399-nm `s0=0.6`, detuning `-1.65 Gamma`, and `10 G/cm` for the next study stage.
`studies/scan_3d_mot_green_trap.py` holds those values fixed and scans a
provisional 556-nm `s0`/detuning grid for `angled_sequential`. This is an
optimization result and study choice, not a laboratory-set constant; the
configured green defaults remain unchanged until a result is explicitly
adopted. The script uses the same deterministic three-shard workflow and merge
format as the blue and gradient scans.
The coarse and fine green scans both retained the provisional 556-nm defaults
`s0=5`, detuning `-10 Gamma`; the fine scan tied at five fully eligible atoms
with `s0=8`, detuning `-15 Gamma` but won the predefined slowing tiebreaker
(9 versus 8 slow atoms). The resulting staged study point is therefore blue
`s0=0.6`, blue detuning `-1.65 Gamma`, green `s0=5`, green detuning
`-10 Gamma`, and gradient `10 G/cm`. These remain optimization results rather
than laboratory-set parameters.

Full-ensemble retention runs may be deterministically split with the retention
study's `--num-shards` and `--shard-index`. Each shard saves compressed inside
and eligibility masks. `studies/merge_3d_mot_retention_shards.py` concatenates
the disjoint masks first, then chooses the global peak cohort and performs the
conditional lifetime fit. Never sum independently chosen shard retention
curves, because their cohort peak times need not agree.
For resumable long runs, pass `--checkpoint-dir` to each shard and both
checkpoint options to the merger. Per-shard files contain final states plus
original ensemble indices; after the global peak is known, the merger writes
only peak-cohort atoms retained through the final sample under
`data/particle_states/after_3d_mot`. This permits continuation without storing
or recomputing the full trajectory history.
Continuation runs must pass `--prequalified-input`; otherwise the analysis
would incorrectly reapply the five-millisecond residence requirement and could
select a new, biased cohort peak after the saved checkpoint.
The unattended remaining-configuration workflow is submitted by
`studies/submit_3d_mot_overnight_pipeline.py`. It requires the completed donut
gradient shards, merges and selects that point, runs the donut green scan, and
in parallel performs blue -> top-five selection -> gradient -> best-point
selection -> green for `five_beam_gravity`. PBS `afterok` dependencies prevent
downstream work after a failed stage. Automatic choices are recorded in
`data/validation/mot_3d/optimization/final_operating_points.json` but are not
written into `config.py` without review. The overnight scans use 900 shared
input atoms, split deterministically into three 300-atom shards.

Physical force validation after the first five-beam scan found that the former
`five_beam_gravity` setup was not a stable MOT: with strong axis `z`, its green
force was anti-restoring along `z`, and the unopposed broad-line `+x` beam
imparted a transverse acceleration orders of magnitude above gravity. The
approved corrected design uses strong axis `x`, disables 399 nm on `+x`, and
sets the green `+x` helicity to left while the paired `yz` beams remain right.
Tests verify green restoring force on both sides of x, y, and z with gravity,
plus blue longitudinal slowing and transverse cancellation. Five-beam scan
results produced before this correction are invalid for optimization and must
not be reused.
`studies/submit_five_beam_reoptimization.py` submits the corrected five-beam
blue -> gradient -> green chain for 900 atoms without rerunning the valid donut
scan. Its dedicated `force_corrected_900` output paths prevent stale results
from the former force geometry from entering the new merges.
`studies/scan_3d_mot_gradient.py` is the second-stage scan. Its current defaults
are the five 399-nm candidates selected from the 600-atom targeted scan and
gradients 5, 7.5, 10, 12.5, and 15 G/cm. These are optimization candidates, not
laboratory-set values; the unchanged config default remains 10 G/cm.

The reviewed staged results are now adopted as provisional, profile-specific
defaults in `config.py`. `angled_donut` uses blue `s0=1.5`, blue detuning
`-3 Gamma`, green `s0=30`, green detuning `-25 Gamma`, and gradient `2.5 G/cm`.
`angled_sequential` uses blue `s0=0.6`, blue detuning `-1.65 Gamma`, green
`s0=5`, green detuning `-10 Gamma`, and gradient `10 G/cm`. The force-corrected
`five_beam_gravity` uses blue `s0=1`, blue detuning `-2 Gamma`, green `s0=10`,
green detuning `-20 Gamma`, and gradient `2.5 G/cm`; its 900-atom scan produced
270 capture-eligible atoms and a peak population of 249. Because its chosen
gradient and green detuning are scan-boundary values, further expansion may
improve it. These values are simulation optimization results, never
laboratory-set constants. Production 3D-MOT runs resolve the magnetic gradient
from the selected profile unless an explicit override is supplied.

Subsequent force validation found that the former `angled_donut` default
(implicit strong axis `z` and right-handed polarization on every beam) was
anti-restoring along lab `z`. Because its MOT axes are identical to those of
`angled_sequential`, the corrected profile uses strong axis `y`, right-handed
polarization on both `xz` pairs, and left-handed polarization on the `y` pair
for both wavelengths. Fixed tests verify the 556-nm restoring-force sign on
both sides of x, y, and z for both angled profiles. All donut optimization
results obtained before this correction are invalid and must be rerun.
`studies/submit_angled_donut_reoptimization.py` performs that rerun as an
isolated 900-atom, three-shard blue -> gradient -> green PBS dependency chain.
Its `polarization_corrected_900` paths prevent stale pre-correction results from
being merged, and its final summary preserves the valid force-corrected
five-beam selection.
The corrected 900-atom donut scan selected blue `s0=1.5`, blue detuning
`-3 Gamma`, gradient `2.5 G/cm`, green `s0=30`, and green detuning
`-25 Gamma`, yielding 567 capture-eligible atoms and a peak of 567. This point
is adopted only for the requested full-ensemble retention curve: all varied
parameters except blue detuning sit on scan boundaries, so a later expanded
optimization is mandatory.

The former elliptical crossed-beam implementation of `angled_sequential` was
replaced by a physically buildable planar-separated variant. It keeps the
apparatus-compatible +/-30-degree xz axes, the two upstream-propagating 399-nm
beams, and all six 556-nm MOT beams. The blue beams are circular Gaussians
transmitted only for `z <= z_MOT - green_exclusion_radius_m`; the six green
Gaussian beams are not clipped by that plane and remain present on both sides.
The boundary remains blue-illuminated. The MOT center therefore has exactly zero blue
intensity while a crossing on or upstream of the plane remains illuminated.
The configured 5-mm waist, 10-mm exclusion radius, and 20-mm upstream crossing
are provisional seeds. `studies/scan_3d_mot_sequential_geometry.py` compares
the requested 3x2x2 grid (3/5/10-mm waists, 5/10-mm exclusions, 10/20-mm
crossings) with fixed laser operating points, green light, and magnetic field.
Earlier sequential optimization and retention results used the obsolete
elliptical geometry and cannot be used to rank this replacement.

All generated long-running 3D-MOT PBS scripts use `python -u` and redirect
stdout/stderr to distinct files under `data/validation/mot_3d/logs`, including
the array index in the name. The existing simulator-level `tqdm` bar counts
completed atoms and writes to `.err`; do not wrap it in a second atom bar.
Study-level messages immediately before and after individual simulations use
flushed output so `.out` identifies the active candidate.

`graphs_scripts/plot_3d_mot_tau.py` reads a merged retention summary and writes
two independent PNGs per profile under `graphs/mot_3d_tau`: capture-eligible
population versus simulation time and continuous peak-cohort retention versus
post-peak time. It draws a lifetime curve only for a fit already accepted in
the source JSON and supports a visible `--data-label` for historical results.

`five_beam_gravity` now matches the transverse core-shell rule used by
`angled_donut`: its paired `yz` directions use center-blocked blue Gaussians and
green Gaussians clipped outside the same 10-mm radius. The unpaired `+x` beam
remains green only. All five-beam optimization and retention results produced
before this aperture change correspond to a different geometry and must not be
reused for the corrected configuration.

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

The authoritative input ensemble for downstream 3D-MOT work is
`data/particle_states/after_2d_mot/final_ensemble_s0_1.47/`. It contains 20 paired
state arrays with layout `(x, y, z, vx, vy, vz)` in SI units, plus adjacent
metadata. The replay validated all arrays as finite `float64` data with shape
`(N, 6)` and reproduced 15,840 captures from 592,319 Zeeman survivors
(2.6742347%).

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

The authoritative scientific and statistical plan for the active campaign is
[`docs/2D_MOT_OPTIMIZATION_PLAN.md`](docs/2D_MOT_OPTIMIZATION_PLAN.md). Read it
before changing search bounds, particle/seed budgets, stopping rules, objective
definitions, or the interpretation of a result.

The experimental control resolutions required for the final near-optimality
claim have not yet been confirmed. The plan contains provisional placeholders
for `s0`, detuning, and magnet radius; do not present them as measured apparatus
capabilities.

The campaign has three required outcomes: high conditional capture among Zeeman
survivors, repeatability across independent particles/seeds, and robustness to
realistic laboratory parameter-setting uncertainty. A high Optuna value alone
does not satisfy the campaign goal.

The completed campaign used `python -m studies.optimize_2d_mot_joint` to
optimize `s0`, detuning, and magnet radius simultaneously. Superseded fixed-`s0`,
candidate-validation, robustness, and early production scripts were removed
after closure; Git history retains them for historical reconstruction.

All candidate points must use the same Zeeman production ensembles, the same
particle subsets, and the same MOT seeds. Use cheap paired screening first and
reserve full ensembles and adaptive confidence-interval stopping for finalists.
The joint optimizer accepts explicit refinement domains through
`--s0-bounds`, `--detuning-bounds`, and `--magnet-radius-bounds-m`. A changed
domain, particle count, or ensemble count must use a new study name and output
directory rather than continuing an incompatible SQLite study.
The retained result chain is the Pareto scan, hybrid refinement, finalist
confirmation, local sensitivity checks, and final production prediction. Treat
the saved JSON summaries as authoritative; do not rerun removed historical
stages unless the scientific objective changes.

Zeus worker processes can take several minutes to reach full CPU utilization.
Within the 600-core project quota, prefer a few long-lived jobs that each run
several seeds or parameter points sequentially over many short array tasks.  For
workloads that scale well to 200 processes, the current practical default is
three concurrent 200-core workers.  Preserve each completed seed or point in a
separate result file so an interrupted worker can resume safely.

The final conditional-capture prediction was produced with
`python -m studies.run_2d_mot_final_production`. Its stopping rule required the
95% prediction for 10,000,000 Zeeman survivors to have a half-width no larger
than 0.05 percentage points.

The final production-prediction stopping rule passed on 2026-08-31 with 20
independent ensembles. The locked setting is `s0=1.474497`, detuning
`-1.1840645 Gamma`, and magnet radius `49.217614 mm`, using
`RK4StHybridCustom` at `dt=0.625 us`. Across 592,319 Zeeman survivors, 15,840
were captured. For 10,000,000 Zeeman survivors, the model predicts 267,423
captures, with a 95% prediction range of 263,195 to 271,652 and a half-width of
0.042285 percentage points. This result is conditional on entering the 2D MOT
as a Zeeman survivor and is the authoritative final conditional prediction.

The prediction interval combines future binomial capture-counting variance with
the larger of the pooled-binomial and empirical between-ensemble uncertainty in
the estimated mean. The pooled-binomial term controlled in the final dataset,
so the calculation used the large-sample 1.96 critical value. The result passed
the predeclared maximum half-width of 0.05 percentage points.

The retained generic diagnostic is
`python -m studies.diagnose_2d_mot_photon_counts`. It established that the
original Gaussian-only solver was not adequate in the low-photon-count regime:
found that `Ni < 15` evaluations contribute 14.3490% of all expected photons,
8.7943% on captured trajectories, and 17.2808% on non-captured trajectories.
This is material. `RK4StHybridCustom` now samples exact Poisson absorption and
isotropic emission recoil below `Ni = 15`, while retaining the Gaussian
approximation at higher counts. The one-off timestep and finalist scripts used
to establish this conclusion were removed after their JSON results were saved.

The completed hybrid follow-up did not show monotonic capture convergence from
5 to 0.3125 microseconds; the adjacent differences were dominated by uncoupled
Monte Carlo recoil noise. The practical locked protocol is therefore 1.25
microseconds for candidate screening/refinement, 0.625 microseconds for finalist
and production runs, and the existing 0.3125-microsecond result as a sensitivity
check. Do not continue halving the timestep without evidence of a reproducible
monotonic numerical bias.

Do not interpret only the highest Optuna trial. The desired scientific output is
a recommendation that includes:

- the best or near-best operating region;
- predicted capture efficiency;
- realistic detuning and magnet-setting ranges;
- dependence on available laser intensity;
- regions achieving, for example, 98-99% of the predicted maximum.

The completed local sensitivity confirmation compared the nominal point with
detuning `-1.2040645 Gamma`, radius `49.317614 mm`, at both `s0=1.474497` and
`s0=1.5`. Their paired mean changes relative to the nominal point were -0.022
and -0.027 percentage points, respectively. The associated 95% intervals were
[-0.125928, +0.081928] and [-0.102484, +0.048484] percentage points. Treat these
as evidence that the local mean response is not sharply degraded, not as a
strict simultaneous equivalence proof over an entire continuous parameter box.

The 2D-MOT optimization, timestep investigation, sensitivity campaign,
conditional production prediction, and full-thermal Zeeman-flux prediction are
closed. Do not launch more optimization or timestep runs unless the apparatus
constraints, physical model, or scientific objective changes.

The final full-source run used 5,000,000 Yb-171 atoms in 100 independent batches
with no angular cutoff and the conservative 3x-broadened microtube distribution.
It produced 17,168 Zeeman survivors: a pooled survival of 0.343360% with an
exact-binomial 95% interval of 0.338251%-0.348526%. The variation between batch
counts agrees with ordinary binomial sampling (observed count SD 13.24 versus
13.08 expected), so there is no evidence of additional seed instability.

At the modeled Yb-171 oven flux of `7.38634e13 atoms/s`, the predicted
Zeeman-survivor flux is `2.53617e11 atoms/s` with a Monte Carlo 95% range of
`2.49844e11`-`2.57433e11 atoms/s`. Applying the locked conditional 2D-MOT
efficiency yields an oven-to-2D-MOT efficiency of 0.00918225% and an expected
capture flux of `6.78232e9 atoms/s`. Independent statistical uncertainties from
the Zeeman and 2D-MOT estimates give an approximate 95% range of
`6.63701e9`-`6.92764e9 atoms/s`. Physical source-model systematics are separate.

Optuna studies may use SQLite storage so a study can continue across jobs. Avoid
allowing multiple jobs to create or initialize the same SQLite database at the
same time; this previously caused a race. Confirm storage paths and initialization
strategy before launching a PBS array.

## 8. Stochastic uncertainty

Photon-scattering recoil is stochastic. Small differences between nearby
configurations may therefore reflect random realization noise rather than a
meaningful physical difference.

Final conclusions use the accepted per-seed Zeeman production ensembles and
matching MOT seeds. The removed legacy single-ensemble seed scan is not part of
the accepted uncertainty analysis.

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
