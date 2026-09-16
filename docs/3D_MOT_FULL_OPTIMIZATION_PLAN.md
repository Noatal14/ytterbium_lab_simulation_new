# Full 3D-MOT optimization and prediction plan

## Scientific objective

Optimize and compare exactly two experimentally relevant 3D-MOT families:

1. the six-green/six-blue `angled_donut`, which is the present capture and
   retention reference;
2. the gravity-assisted `five_beam_gravity` MOT, which currently captures fewer
   atoms but is substantially simpler to build and align.

The reduced-blue six-green-beam geometries are not optimization candidates.
Paired ablations, finite-gate scans, phase-space plots, and trajectories show
that removing or relocating blue directions reduces capture substantially. The
supporting evidence is collected in
`docs/3D_MOT_OPTIMIZATION_CANDIDATE_RATIONALE.md` and
`graphs/mot_3d_configuration_decision/`.

The final output for each optimized family must contain:

- a recommended nominal operating point;
- conditional 3D-MOT capture efficiency among validated 2D-MOT survivors;
- a 95% prediction interval for a new equivalent ensemble;
- expected usable atoms per 10,000,000 atoms leaving the 2D MOT;
- expected usable 3D-MOT flux obtained by combining the conditional result with
  the existing oven-to-2D-MOT prediction;
- an experimentally meaningful near-optimal hyperrectangle;
- evidence that the hyperrectangle, not only its center, satisfies a declared
  maximum acceptable capture loss;
- retention, phase-space, and representative-trajectory diagnostics at the
  recommended point.

All optimized settings remain simulation recommendations until implemented and
validated in the laboratory.

## Capture metric and simulation model

The primary objective is the usable fraction at 100 ms:

```text
usable at 100 ms =
    distance from MOT center <= 5 mm
    and total speed <= 1 m/s
```

Leaving the region earlier does not permanently disqualify an atom. The
secondary diagnostics are usable-at-least-once count, peak usable count,
population versus time, loss after the peak, and an exponential lifetime only
when the decay tail passes the existing fit checks.

All stages use `RK4StHybridCustom`, the timestep in `MOT_3D_SIM_CONFIG`, gravity,
the same physical capture definition, and the same input ordering. Candidate
comparisons within a stage use common initial particles and common random
streams. Changing a solver, timestep, capture rule, or geometry creates a new
campaign and cannot be silently merged with the old one.

## Optimization variables

### Five-beam gravity MOT: ten proposed variables

Unpaired green beam opposing gravity:

1. `green_unpaired_s0`
2. `green_unpaired_detuning_gamma`
3. `green_unpaired_waist_m`

Four paired green beams:

4. `green_paired_s0`
5. `green_paired_detuning_gamma`
6. `green_paired_waist_m`

Four paired blue beams:

7. `blue_s0`
8. `blue_detuning_gamma`
9. `blue_waist_m`

Magnetic field:

10. `magnetic_gradient_G_cm`

The current code supports an intensity override for the unpaired green beam,
but not yet separate unpaired-green detuning and waist. The production
optimizer must add explicit per-axis detuning and waist support, with force-sign
and profile tests, before launching this ten-dimensional search.

### Full angled donut: seven variables

Six green core beams:

1. `green_s0`
2. `green_detuning_gamma`
3. `green_waist_m`

Six blue shell beams:

4. `blue_s0`
5. `blue_detuning_gamma`
6. `blue_waist_m`

Magnetic field:

7. `magnetic_gradient_G_cm`

The cutoff radius, beam angles, polarizations, strong magnetic axis, MOT center,
and gravity direction remain fixed geometry choices. They are not silently
re-optimized with the laser operating point.

## Required laboratory constraints before production search

The following inputs must be confirmed by the laboratory team before the final
search domain is frozen:

1. minimum, maximum, adjustment resolution, calibration uncertainty, and drift
   for every optimized `s0`, detuning, waist, and gradient;
2. available optical power for each beam group, or an empirical feasible
   relationship between `s0` and waist;
3. whether the unpaired green beam can have an independently controlled
   detuning from the four paired green beams;
4. whether the four beams within a group share one power/frequency/waist
   control, as assumed here;
5. the largest absolute loss in conditional 3D-MOT capture that the team agrees
   is experimentally negligible.

Optimizing `s0` and waist as an unconstrained rectangle is not physically valid
when laser power is limited. For Gaussian beams the required power scales
approximately as `s0 * waist^2`; infeasible trials must be rejected by a
laboratory power constraint rather than allowed to win numerically.

Until measured constraints are supplied, the following broad domains are
planning placeholders, not approved scan ranges:

| Parameter group | Provisional domain |
|---|---:|
| green `s0` | 0.5 to 40 |
| green detuning | -35 to -5 Gamma |
| green waist | 5 to 20 mm |
| blue `s0` | 0.2 to 4 |
| blue detuning | -6 to -0.5 Gamma |
| blue waist | 10 to 25 mm |
| five-beam gradient | 0.75 to 3 G/cm |
| donut gradient | 0.5 to 6 G/cm |

The five-beam pre-optimization winner was on the 1.4-G/cm lower boundary, so
the production domain must extend below 1.4 G/cm. The donut's present green
intensity and detuning also came from earlier boundary points, so the new domain
must not be centered too narrowly on those provisional values.

## Input ensembles and data separation

The accepted 2D-MOT production output contains 20 independent ensembles and
15,840 survivors in total, with 756--840 particles per ensemble. These are
sufficient for discovery and refinement, but reusing all of them for both
parameter selection and final prediction would make the reported uncertainty
optimistically selected.

Use the current 20 ensembles as follows:

- 12 ensembles: Optuna discovery pool;
- 4 ensembles: focused refinement and hyperrectangle construction;
- 4 ensembles: preliminary held-out check before expensive production.

After both operating points and hyperrectangles are locked, generate new
independent 2D-MOT survivor ensembles for final production validation. Start
with approximately 16,000 new survivors and add ensembles adaptively if the
prediction stopping rule is not met. Do not regenerate survivors merely to
increase the discovery-stage trial count.

The final absolute-performance target is a 95% half-width no larger than 0.75
percentage points for conditional 3D-MOT capture. A binomial planning estimate at 31%
capture requires about 14,600 particles; at 83% it requires about 9,700. The
actual stopping rule must use the larger of pooled counting uncertainty and
empirical between-ensemble/recoil-seed variation. If the measured half-width is
larger than 0.75 points, generate more independent survivors until it passes.

This absolute reporting target is distinct from the precision used to choose
between nearby finalists. Paired comparisons of finalists must target a 95%
half-width no larger than 0.4 percentage points for the capture-fraction
difference. Every pair uses the same initial particles and matched recoil
seeds, so the uncertainty of the paired difference can be substantially smaller
than the uncertainty of either absolute capture fraction. If two finalists
remain closer than this resolution, they are statistically tied: prefer the
lower-power, more interior, and less sensitive operating point rather than
claiming a numerically unique optimum.

## Stage 0: implementation and smoke validation

Before any long Optuna allocation:

1. add the five-beam per-group detuning and waist controls;
2. centralize both search spaces and all campaign settings in `config.py`;
3. verify restoring-force signs on both sides of x, y, and z for sampled trials;
4. verify exact zero blue intensity inside every protected core;
5. reject nonphysical or laboratory-infeasible power combinations before a
   simulation starts;
6. run two-atom and twelve-atom smoke tests for both families;
7. verify that every completed trial is written atomically and can be resumed;
8. verify live atom-level progress in each Zeus `.err` file.

## Stage 1: broad Optuna discovery

Use a fixed, stratified set of 600 particles drawn from the 12 discovery
ensembles for the broad first-pass evaluation. Every trial in a family receives
the same particles and common random streams. This makes differences between
trials much more precise than independent resampling, while remaining cheap
enough for hundreds of trials.

Six hundred particles do not imply 33% CPU utilization. One candidate is run
on one 200-core node, so the node receives three waves of approximately 200
atoms and can keep all 200 workers occupied except for the short final load
imbalance. The three nodes evaluate three different candidates concurrently;
they do not split one 600-particle candidate into three 200-particle shards.
Increasing the broad-search population would primarily improve objective
precision while reducing the number of distinct points explored per 24-hour
allocation.

Use a multi-fidelity rule instead of increasing every broad trial blindly:

1. evaluate every new Optuna proposal on the common 600-particle set;
2. promote the best region and statistically unresolved challengers to a nested
   1,800-particle set;
3. use the 3,000-particle, multi-seed refinement below for finalists.

The nested sets contain the same original 600 particles, so promotion adds
information without changing the comparison population. After a timing smoke
test, the 600-particle base may be raised only if the cluster completes the
minimum search-space coverage comfortably within the planned 24-hour rounds.

Run three long-lived PBS workers:

```text
3 nodes
200 cores per node
64 GB per node
walltime: 24 hours
one complete candidate at a time per node
three candidates evaluated concurrently
```

Each worker saves every trial immediately, including parameters, seed, particle
indices, final count, diagnostic counts, runtime, failure reason, and software
revision. The campaign is restart-safe: a new 24-hour allocation resumes the
same study without repeating completed trials.

Use Optuna's multivariate TPE sampler with independent sampler seeds for the
three workers. If shared journal locking is reliable on Zeus, workers may share
one study; otherwise use three independent studies and merge their completed
trial tables between 24-hour rounds. Do not use a shared SQLite database over
the cluster filesystem without a concurrency smoke test.

Minimum discovery budgets:

```text
five-beam, 10 dimensions: at least 600 completed valid trials
donut, 7 dimensions:     at least 350 completed valid trials
```

These are minimum budgets, not convergence claims. Continue another 24-hour
round if the best held-out estimate improves by more than 1 percentage point in
the final 100 trials, important parameter ranges still collapse onto a search
boundary, or the three sampler seeds locate incompatible regions.

The objective is usable fraction at 100 ms. Do not optimize
usable-at-least-once count. Record it only to diagnose loading followed by loss.

## Stage 2: successive refinement

Optuna's best single 600-particle trial is not the recommendation. Cluster the
top trials into distinct regions, include lower-power and interior candidates,
and carry approximately 20 representatives per family forward.

Evaluate these representatives with:

```text
3,000 particles per candidate
at least 3 recoil seeds
common particles and seeds across candidates
```

Rank candidates by a conservative lower confidence bound on usable fraction,
then by mean capture. For statistically close candidates, allocate additional
paired particles and seeds until the 95% half-width of their capture-fraction
difference is at most 0.4 percentage points, or until they can safely be
declared tied. Reject narrow peaks whose small nominal advantage is smaller
than their stochastic variation or whose settings lie too close to a
power/calibration boundary.

Carry approximately five finalists per family to all 15,840 existing survivors
with five recoil seeds. This stage selects the nominal points; the later new
ensembles are reserved for unbiased production reporting.

## Stage 3: construct the near-optimal hyperrectangle

The desired result is a joint 7- or 10-dimensional region, not independent
one-dimensional error bars. Parameter interactions are explicitly allowed.

Before this stage, declare an absolute negligible-loss tolerance. This is a
physical robustness tolerance, not the statistical uncertainty of the nominal
capture estimate. The proposed planning value is:

```text
delta = 1.0 percentage point of conditional 3D-MOT capture
```

This is intentionally larger than the 2D-MOT campaign's 0.05-point tolerance.
At 30--85% capture, proving 0.05-point equivalence would require an impractical
particle budget and would not be experimentally meaningful. The laboratory team
must approve or replace `delta` before production.

Construct the largest axis-aligned box around a robust nominal point using a
local surrogate fitted to a space-filling design. For each parameter, propose
bounds aligned to the confirmed experimental resolution. A box is accepted
only after all of the following tests:

1. the center and every one-parameter face midpoint;
2. every corner at a cheap paired particle budget (128 corners for seven
   dimensions; 1,024 corners for ten dimensions);
3. a space-filling sample of interior and face points;
4. adversarial optimization of the surrogate to search the box for the largest
   predicted capture loss;
5. high-statistics reevaluation of the worst corners, worst adversarial points,
   and representative interior points;
6. simultaneous, multiplicity-adjusted confidence bounds for loss relative to
   the nominal setting.

The cheap all-corner pass is necessary because one-dimensional scans cannot
detect interactions. High-statistics simulation of all 1,024 ten-dimensional
corners is not required unless many remain unresolved; allocate particles
adaptively to the worst challengers.

The defensible claim is:

```text
Within the stated parameter domain, control resolution, tested corner set,
and adversarial validation design, the data provide 95% simultaneous
confidence that no validated point in the recommended hyperrectangle loses
more than delta percentage points of conditional capture.
```

This is a simulation-based guarantee over a declared finite validation design,
not a mathematical proof over every real-valued point and not an experimental
guarantee before calibration.

## Stage 4: held-out production prediction

Lock both nominal points and hyperrectangles before opening the new validation
ensembles. Run each nominal point on identical new survivors and independent
recoil seeds. Continue adding independent ensembles until the 95% interval
half-width for absolute conditional capture is at most 0.75 percentage points
for both families. This final reporting precision is separate from the tighter
0.4-percentage-point paired-difference target used to resolve finalists.

For a reporting reference of 10,000,000 atoms leaving the 2D MOT, report:

```text
expected usable 3D-MOT atoms = 10,000,000 * conditional 3D efficiency
95% prediction interval in both fraction and atom count
```

The existing end-to-end 2D-MOT prediction is:

```text
modeled Yb-171 oven flux:       7.38634e13 atoms/s
expected 2D-MOT capture flux:   6.78232e9 atoms/s
95% range:                      6.63701e9 to 6.92764e9 atoms/s
```

For each 3D-MOT family, multiply the 2D-MOT flux by the independently estimated
conditional 3D-MOT efficiency and propagate both uncertainty contributions.
Keep the conditional 3D efficiency and total oven-to-3D efficiency separate;
they have different denominators and answer different questions.

## Stage 5: final physics and retention package

At each recommended nominal point:

1. rerun force-sign and protected-core tests;
2. save the population-versus-time curve through 100 ms;
3. continue the usable population beyond 100 ms when sufficient atoms remain;
4. fit `tau` only when the observed tail is genuinely exponential and passes
   the declared loss and goodness-of-fit tests;
5. save final survivor states for continuation;
6. produce common-scale phase-space acceptance and representative captured and
   failed trajectories;
7. report required total optical power and alignment complexity.

The laboratory recommendation must present capture performance and practical
complexity separately. The simulation should not decide how many atoms are
worth one fewer beam; it should provide the quantitative trade-off so the team
can decide.

## Checkpointing and failure recovery

Every trial is an immutable record. A 24-hour job may stop between trials, but
must never lose completed results. Before starting a trial, write its requested
parameters and status; after completion, atomically add counts, runtime, seed,
and status. Failed or infeasible trials remain recorded with a reason.

Each campaign has:

- a human-readable manifest containing domains, resolutions, solver, timestep,
  particle files, seeds, git commit, and objective definition;
- one trial-result file per completed trial;
- a merged Optuna-compatible table;
- periodic study snapshots;
- a status command showing completed, running, failed, and remaining work;
- deterministic commands to resume, refine, validate, and report.

No stage silently adopts its numerical winner into the laboratory configuration.
The final nominal values are written only after the declared validation and
uncertainty stopping rules pass.

## Decisions required before implementation

The optimization code should not be written against guessed laboratory limits.
The team must confirm:

1. feasible bounds and resolutions for all 7/10 variables;
2. optical-power constraints coupling `s0` and waist;
3. whether the unpaired green detuning is independently controllable;
4. the negligible-loss tolerance `delta` for the hyperrectangle;
5. whether the proposed 0.4-percentage-point 95% half-width for paired finalist
   differences and 0.75-percentage-point 95% half-width for final absolute
   performance are sufficient.

Once these are fixed, implementation proceeds in the order Stage 0 through
Stage 5. No additional geometry screening is required.
