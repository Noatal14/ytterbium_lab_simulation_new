# Full 3D-MOT optimization and prediction plan

## Scientific objective

Optimize and compare exactly two experimentally relevant 3D-MOT families:

1. the six-green/six-blue `angled_donut`, which is the present capture and
   retention reference;
2. the two-blue `single_pass` geometry, which retains the six-beam angled green
   MOT but replaces the full blue shell with one localized entrance-slowing
   pair in the `yz` plane.

The reduced-blue six-green-beam geometries are not optimization candidates.
Paired ablations, finite-gate scans, phase-space plots, and trajectories show
that removing or relocating blue directions reduces capture substantially. The
supporting evidence is collected in
`docs/3D_MOT_OPTIMIZATION_CANDIDATE_RATIONALE.md` and
`graphs/mot_3d_configuration_decision/`.

The final output for each optimized family must contain:

- a recommended nominal operating point;
- conditional 3D-MOT capture efficiency among validated 2D-MOT survivors;
- a 95% confidence interval for the mean conditional efficiency;
- a separately labeled estimate of expected variation for a new equivalent
  ensemble, when supported by the number of independent ensembles;
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
comparisons within a stage use common initial particles and matched recoil
seeds: the same recoil-seed index is applied to every candidate being compared,
which reduces Monte Carlo noise in paired differences. Changing a solver,
timestep, capture rule, or geometry creates a new
campaign and cannot be silently merged with the old one.

## Optimization variables

### Two-blue single pass: nine proposed variables

Six angled green MOT beams:

1. `green_s0`
2. `green_detuning_gamma`
3. `green_waist_m`

Two blue entrance-slowing beams:

4. `blue_s0`
5. `blue_detuning_gamma`
6. `blue_waist_m`

Field and blue geometry:

7. `magnetic_gradient_G_cm`
8. `blue_crossing_angle_deg`
9. `blue_crossing_z_offset_m`

The blue beams lie in the `yz` plane. One originates on the negative-y side
and the other on the positive-y side; both propagate with a negative-z
component toward their shared crossing. The initial seed is a 45-degree
included angle and a crossing 10 mm upstream of the MOT center. The approved
angle domain is 45--70 degrees. The six green beams retain the fixed angled
60/120-degree geometry used by the donut candidate.

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
3. the mechanically accessible range and positioning resolution for the blue
   crossing along z and for the included angle;
4. whether the beams within each wavelength group share one power/frequency/waist
   control, as assumed here;
5. the largest absolute loss in conditional 3D-MOT capture that the team agrees
   is experimentally negligible.

Optimizing `s0` and waist as an unconstrained rectangle is not physically valid
when laser power is limited. For Gaussian beams the required power scales
approximately as `s0 * waist^2`; infeasible trials must be rejected by a
laboratory power constraint rather than allowed to win numerically.

Until the remaining measured constraints are supplied, the following broad
domains are planning placeholders, except for the confirmed hard upper limit
`blue_s0 <= 1.5`:

| Parameter group | Provisional domain |
|---|---:|
| green `s0` | 0.5 to 40 |
| green detuning | -35 to -5 Gamma |
| green waist | 5 to 20 mm |
| blue `s0` | 0.2 to 1.5 (confirmed hard upper limit) |
| blue detuning | -6 to -0.5 Gamma |
| blue waist | 10 to 25 mm |
| single-pass gradient | 0.5 to 6 G/cm |
| single-pass blue included angle | 45 to 70 degrees (confirmed) |
| single-pass blue crossing z offset | provisional; centered initially at -10 mm |
| donut gradient | 0.5 to 6 G/cm |

The upper limit `blue_s0 <= 1.5` applies to every 399-nm beam group in both
candidate families. The lower bound remains a planning value until the full
laboratory control range is confirmed.

The donut's present green intensity and detuning came from earlier boundary
points, so the new domain must not be centered too narrowly on those
provisional values. The single-pass z-offset bounds remain provisional until
the short geometry screen and the laboratory's mechanical access are reviewed.

## Input ensembles and data separation

The accepted 2D-MOT production output contains 20 independent ensembles and
15,840 survivors in total, with 756--840 particles per ensemble. These are
sufficient for discovery and refinement, but reusing all of them for both
parameter selection and final prediction would make the reported uncertainty
optimistically selected.

Use the current 20 ensembles as follows:

- 12 ensembles: Optuna discovery pool; the fixed 600-particle screening batch
  contains 50 particles from each ensemble;
- 4 ensembles: focused refinement and hyperrectangle construction;
- 4 ensembles: preliminary held-out check before expensive production.

Every broad trial uses the same balanced 600-particle batch and matched recoil
seeds for efficient paired comparisons. Before costly refinement, at most 12
leading regions per family are evaluated on a separate balanced 600-particle
batch drawn only from the four preliminary-check ensembles. The four refinement
ensembles are not used by Optuna, and the final newly generated survivor set
remains unopened until all parameter choices and the robust-region procedure
are locked.

The existing 15,840 survivors are used for final candidate selection, not for
the final unbiased performance claim. That claim is evaluated only on the
newly generated sealed ensembles.

After both operating points and hyperrectangles are locked, generate new
independent 2D-MOT survivor ensembles for final production validation. Start
with approximately 16,000 new survivors and add ensembles adaptively if the
confidence-interval stopping rule is not met. Do not regenerate survivors merely to
increase the discovery-stage trial count.

The final absolute-performance target is a 95% confidence-interval half-width
no larger than 0.75 percentage points for the mean conditional 3D-MOT capture.
A binomial planning estimate at 31% capture requires about 14,600 particles; at
83% it requires about 9,700. The recoil-seed realizations are crossed across
the ensemble groups, not nested separately within each ensemble. The actual
interval therefore uses a crossed hierarchical bootstrap: independently
resample 2D-MOT ensemble clusters and recoil-seed realizations while preserving
the particle grouping within each ensemble. Report expected variation for a
new equivalent ensemble separately, using a bootstrap predictive distribution that adds a new
ensemble effect, recoil-seed effect, and finite-particle variation at the stated
ensemble size. If the data cannot support that second calculation, report the
observed between-ensemble spread and do not call it a prediction interval. Add
independent ensembles until the confidence-interval precision target passes.

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

1. expose the single-pass crossing angle and z offset as bounded optimizer variables;
2. centralize both search spaces and all campaign settings in `config.py`;
3. verify restoring-force signs on both sides of x, y, and z for sampled trials;
4. verify exact zero blue intensity inside every protected core;
5. reject nonphysical or laboratory-infeasible power combinations before a
   simulation starts;
6. run two-atom and twelve-atom smoke tests for both families;
7. verify that every completed trial is written atomically and can be resumed;
8. verify live atom-level progress in each Zeus `.err` file.

## Approved-budget envelope

The following are planning ceilings, not promised runtimes. Replace the
node-hour estimates with measured values from Stage 0 before submitting the
campaign; if the calibrated estimate exceeds a row ceiling, stop and request
approval rather than silently reducing statistical validation.

| Stage | Maximum evaluations | Atoms x recoil seeds per point | Node-hour ceiling | Approx. elapsed on 3 nodes |
|---|---:|---:|---:|---:|
| implementation and timing | 24 diagnostics | 2--600 x 1 | 6 | <=2 h |
| donut discovery | 350 valid trials | 600 x 1 | 72 | <=24 h |
| single-pass discovery | 600 valid trials | 600 x 1 | 144 | <=48 h |
| early independent check | 12 points/family | 600 x 3 | 72 | <=24 h |
| refinement | 16 points/family | 3,000 x 3 | 288 | <=96 h |
| finalist selection | 3 points/family | 15,840 x 3 | 216 | <=72 h |
| box construction screen | 69 points/family | 1,800 x 1 | 216 | <=72 h |
| worst-point box validation | 8 points/family | 3,000 x 3 | 144 | <=48 h |
| initial final prediction | 2 nominal points | about 16,000 x 3 | 144 | <=48 h |

The hard pre-extension ceiling is 1,302 node-hours, including the explicit
6-node-hour implementation and timing row. Discovery may receive only one
additional approved block of at most 100 donut trials or 150 single-pass trials,
followed by a mandatory stop-or-approve decision. Its cap is 72 node-hours only
when the Stage-0 timing estimate shows the selected block fits; otherwise the
trial count is reduced to fit the cap. Final prediction
may add ensembles only to meet the declared confidence-interval precision and
must report the additional calibrated cost before submission.

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

Hard discovery budgets:

```text
single-pass, 9 dimensions: at most 600 completed valid trials
donut, 7 dimensions:     at most 350 completed valid trials
```

These are fixed first-pass ceilings, not convergence claims. One additional
predefined block of at most 100 additional donut trials or 150 additional
single-pass trials may be
requested only if the preliminary held-out estimate improves by more than one
percentage point near the end, an important optimum remains on a boundary, or
the sampler seeds locate incompatible regions. After that block the campaign
stops unless the laboratory explicitly approves a new budget.

The objective is usable fraction at 100 ms. Do not optimize
usable-at-least-once count. Record it only to diagnose loading followed by loss.

## Stage 2: successive refinement

Optuna's best single 600-particle trial is not the recommendation. Cluster the
top trials into distinct regions, include lower-power and interior candidates,
and carry at most 16 representatives per family forward.

Evaluate these representatives with:

```text
3,000 particles per candidate
at least 3 recoil seeds
common particles and seeds across candidates
```

Rank candidates lexicographically: require physical and laboratory feasibility;
maximize a conservative lower confidence bound on usable fraction; then, among
statistically tied points, prefer the point that passes the robustness
tolerance, lies farther from control and power boundaries, requires less
optical power, and has lower local sensitivity. For statistically close
candidates, allocate additional
paired particles and seeds until the 95% half-width of their capture-fraction
difference is at most 0.4 percentage points, or until they can safely be
declared tied. Reject narrow peaks whose small nominal advantage is smaller
than their stochastic variation or whose settings lie too close to a
power/calibration boundary.

Carry at most three finalists per family to all 15,840 existing survivors with
three matched recoil seeds. Add a fourth or fifth seed only for unresolved
paired comparisons. This is final candidate selection, not final held-out
validation. The later new ensembles are reserved for unbiased production
reporting.

Optuna trials that violate a declared power or hardware constraint are marked
`PRUNED_INFEASIBLE` before simulation and retain the reason. Numerical errors,
timeouts, or corrupted outputs are marked `FAIL` and do not receive an
artificial zero objective. Retry a failed trial once only when the failure is
demonstrably infrastructural and parameters and seed remain unchanged.

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

Construct an axis-aligned box around a robust nominal point using a local
surrogate fitted to a space-filling design. Snap every bound to the confirmed
laboratory resolution, then shrink the box until the following risk-directed
validation design contains no unresolved point whose upper confidence bound on
loss exceeds `delta`:

1. the center and all one-parameter face midpoints (14 or 20 points);
2. at most 16 risk-directed or fractional-factorial corners;
3. at most 24 space-filling interior and boundary points;
4. at most 8 adversarial points found by optimizing surrogate loss and
   uncertainty within the box;
5. high-statistics reevaluation of at most 8 worst predicted points;
6. one-sided 95% max-T bootstrap simultaneous upper bounds across the finite
   high-statistics set, preserving ensemble and recoil clusters.

The 9D plan therefore does not evaluate all 512 corners. Finite simulation
cannot prove behavior throughout a continuous box. The surrogate interpolates
between evaluated points, and targeted adversarial sampling searches for
failures of that interpolation.

The defensible claim is:

```text
The recommended box is an empirically supported operating region. For the
finite high-statistics validation design, one-sided max-T bootstrap bounds show
that no evaluated point loses more than delta percentage points of conditional
capture at simultaneous 95% confidence. Behavior between evaluated points is
assessed by the surrogate and targeted adversarial sampling, not guaranteed
mathematically.
```

This is a simulation-based guarantee over a declared finite validation design,
not a mathematical proof over every real-valued point and not an experimental
guarantee before calibration.

## Stage 4: held-out production prediction

Lock both nominal points and hyperrectangles before opening the new validation
ensembles. Run each nominal point on identical new survivors and crossed,
independent recoil-seed realizations. Continue adding independent ensembles
until the crossed hierarchical-bootstrap 95% confidence-interval half-width
for mean conditional capture is
at most 0.75 percentage points
for both families. This final reporting precision is separate from the tighter
0.4-percentage-point paired-difference target used to resolve finalists.

For a reporting reference of 10,000,000 atoms leaving the 2D MOT, report:

```text
expected usable 3D-MOT atoms = 10,000,000 * conditional 3D efficiency
95% confidence interval for the mean, plus separately labeled new-ensemble
variation when estimable
```

The existing end-to-end 2D-MOT prediction is:

```text
modeled Yb-171 oven flux:       7.39e13 atoms/s
expected 2D-MOT capture flux:   6.78e9 atoms/s
95% interval:                   6.64e9 to 6.93e9 atoms/s
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

## Approval requested before implementation

The optimization code should not be written against guessed laboratory limits.
The team must confirm:

1. approve the angled donut and two-blue single-pass geometry as the two
   production-search families;
2. confirm or revise the parameter bounds, resolutions, drift, and optical-
   power constraints;
3. approve the 1,302-node-hour planning ceiling, the single bounded discovery
   extension, and the stop-or-approve checkpoints;
4. confirm whether `delta = 1.0` percentage point is an experimentally
   negligible conditional-capture loss;
5. confirm the mechanically feasible z-offset range and positioning resolution
   for the blue crossing;
6. confirm whether the proposed 0.4-percentage-point 95% half-width for paired
   finalist differences and 0.75-percentage-point 95% confidence-interval
   half-width for the final mean efficiency are sufficient.

Once these are fixed, implementation proceeds in the order Stage 0 through
Stage 5. Before the expensive campaign, a short 600-particle screen must verify
that the new `yz` single-pass seed reaches a useful capture level.
