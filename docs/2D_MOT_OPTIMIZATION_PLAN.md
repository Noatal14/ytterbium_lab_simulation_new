# 2D-MOT optimization and prediction plan

This document is the authoritative scientific plan for the current 2D-MOT
campaign. Update it when the experimental constraints, statistical target, or
accepted workflow changes. Do not infer the campaign goal only from an Optuna
script or one result directory.

## Scientific target

The optimization target is the conditional capture efficiency among atoms that
have already survived the Zeeman slower:

```text
conditional efficiency =
    number captured by the 2D MOT
    / number entering as Zeeman survivors
```

The campaign has exactly three primary goals:

1. **High conditional capture.** Find settings that maximize the captured
   fraction among Zeeman survivors.
2. **Stochastic repeatability.** Show that the predicted capture is stable when
   the initial particles and random seeds change.
3. **Experimental parameter robustness.** Find a sufficiently broad joint
   parameter region so that realistic setting errors and drifts remain inside a
   validated near-optimal region.

The third goal is a required validation, not something to infer automatically
from a visually broad Optuna cluster or from older simulation plots. Around the
recommended nominal setting, construct the experimentally reachable uncertainty
neighborhood using the confirmed `s0`, detuning, and magnet-position
uncertainties. Verify representative boundary/interior points and unresolved
worst-case challengers. Every distinguishable point in that neighborhood must
remain within the accepted capture-loss tolerance:

```text
maximum acceptable loss from parameter variation:
0.05 percentage points of conditional capture
```

Choose the nominal operating point with enough margin from the validated
region's boundaries that the expected laboratory setting uncertainty does not
leave the region. If no such interior point exists, the result is not yet a
robust laboratory recommendation even if it is the highest simulated point.

The desired final result is a robust operating point or joint parameter region,
not necessarily a single sharp maximum. The completed production result for a
reporting reference of ten million Zeeman survivors is:

```text
For the recommended 2D-MOT settings and 10,000,000 Zeeman survivors,
a new equivalent run is predicted to capture 267,423 atoms, with a 95%
prediction range of 263,195 to 271,652 atoms.

Expected conditional capture efficiency: 2.6742347%
Achieved prediction half-width: 0.042285 percentage points
Target prediction half-width:   0.05 percentage points (PASS)
```

The value `10,000,000` is a reporting reference chosen for communicating the
conditional efficiency. It is not an experimentally established Zeeman-survivor
count and does not come from the research proposal.

The current angle-prefiltered thermal source is valid for generating Zeeman
survivors for conditional 2D-MOT optimization. The angular cutoff was separately
validated as excluding atoms that do not survive the Zeeman stage. The resulting
prefiltered Zeeman survival percentage must not be reported as the end-to-end
survival percentage from the full oven flux.

After the 2D-MOT settings were locked, the completed end-to-end campaign used
the unfiltered thermal beam to predict total transmission from the oven.

## Adjustable parameters and current experimental constraints

The joint optimization variables are:

```text
s0
detuning_gamma
magnet_radius
```

The current boundary-follow-up search uses:

```text
s0:             1.4 to 1.5
detuning_gamma: -1.55 to -0.85
magnet_radius:  0.045 to 0.051 m
```

The laboratory can provide `s0 = 1.4`. Approximately `s0 = 1.5` is the expected
upper limit, but its availability is not guaranteed. The current Pareto study
therefore maximizes conditional capture while minimizing `s0` within the
experimentally relevant interval. It should reveal whether operating above 1.4
provides a meaningful capture improvement.

## Stage 1: cheap paired screening

Use the same fixed particles and random streams for every parameter point:

```text
3 independent Zeeman ensembles
2,000 particles per ensemble
6,000 particles per parameter point
50 parameter points in the current Pareto follow-up
```

This stage is only for locating promising regions, identifying parameter
interactions, rejecting poor regions, and detecting optima that reach search
boundaries. At a capture efficiency near 2.5%, only about 150 atoms are captured
per 6,000-particle point, so these trial values are too noisy for final reporting.

## Stage 2: focused refinement

Narrow the domain around promising regions and increase the statistical effort:

```text
at least 5 independent ensembles
10,000 to 20,000 particles per ensemble
paired particles and MOT random streams for every candidate
```

Map the joint high-performing region rather than reporting three independent
one-dimensional ranges. Parameter correlations can make some combinations of
otherwise acceptable individual ranges perform poorly.

## Stage 3: held-out validation

Reserve Zeeman ensembles and MOT seeds that did not participate in screening or
candidate selection. Validate the center, boundaries, representative interior
points, and nearby exterior points of the proposed operating region. This tests
whether the recommendation generalizes rather than fitting the screening seeds.

Recheck finalists at the finer 2D-MOT timestep of 5 microseconds. The 10
microsecond timestep is the accepted screening choice, not an excuse to skip the
final numerical cross-check.

The selected setting subsequently passed the production prediction target at
10 microseconds using 20 independent Zeeman/MOT seed pairs. Repeating those
exact 20 pairs at 5 microseconds produced a paired difference of +0.060106
percentage points, with a 95% interval from +0.032474 to +0.087739 percentage
points. Therefore 5 and 10 microseconds are not equivalent at the predeclared
+/-0.05-percentage-point tolerance.

The library's current stochastic solver samples Gaussian recoil fluctuations
with expected photon count `Ni = scattering_rate * dt` for each laser and time
step. A smaller timestep is not automatically more physical when `Ni` becomes
too small for that approximation. Before choosing the production timestep, run
`python -m studies.diagnose_2d_mot_photon_counts` at 5 microseconds. It reports,
separately for every laser and for captured/non-captured trajectories, both the
fraction of evaluations below the provisional `Ni = 15` threshold and the
fraction of expected photon impulse contributed by those evaluations. The next
solver validation should use exact Poisson sampling in the low-`Ni` regime and
the Gaussian approximation only where it is justified, then repeat the paired
timestep comparison and finalist checks.

That diagnostic was completed on three independent 2,000-particle ensembles.
Across all lasers, 95.1738% of laser-step evaluations had `Ni < 15`, accounting
for 14.3490% of the expected photons. For captured trajectories the corresponding
photon fraction was 8.7943%; for non-captured trajectories it was 17.2808%.
The four 2D-MOT beams individually received about 9.0%-13.1% of their expected
photons from `Ni < 15` evaluations, while the residual Zeeman laser received
99.18% of its expected photons there (and contributed 5.008% of the combined
expected photons). The low-count regime is therefore materially present and
cannot be dismissed by counting only high-force steps.

`RK4StHybridCustom` implements the next validation model. Below `Ni = 15`, it
samples an exact Poisson absorption count and the isotropic recoil directions of
the same spontaneous-emission events. At and above 15 it retains the fast
Gaussian approximation. Use `python -m studies.validate_2d_mot_hybrid_timestep`
to screen 2.5, 5, and 10 microseconds on identical input ensembles before
launching a larger confirmation.

The follow-up campaign found no monotonic capture trend from 5 down to 0.3125
microseconds; adjacent comparisons were dominated by uncoupled Monte Carlo
recoil noise. Repeated 1.25-versus-0.625 batches gave mean differences of
+0.054 and +0.047 percentage points, while 0.625 versus 0.3125 gave -0.067
percentage points with a 95% interval that included zero. Continuing to halve
the timestep would therefore spend rapidly increasing compute on the random
realization rather than resolve a clear numerical trend.

Use 1.25 microseconds as the efficient working timestep for candidate screening
and local refinement. Recheck finalists at 0.625 microseconds, which is the
production timestep. Retain the completed 0.3125-microsecond run as a sensitivity
check on the final recommendation; do not recursively halve the timestep unless
a future comparison shows a reproducible monotonic numerical bias.

## Stage 4: establish near-optimality within experimental resolution

The desired optimization claim uses a tolerance of:

```text
epsilon = 0.05 percentage points of conditional capture efficiency
```

Optuna trials alone cannot establish that no untested continuous point is better.
Before the final campaign, obtain the experimentally meaningful control
resolutions for `s0`, detuning, and magnet position. These resolutions turn the
physical search domain into a finite set of distinguishable laboratory settings.

Until the experimental team supplies measured values, use the following
explicitly provisional resolutions for planning and analysis:

```text
s0 resolution:             0.01
detuning_gamma resolution: 0.01 linewidth
magnet-radius resolution:  0.01 mm = 0.00001 m
```

These placeholders are not claims about the completed apparatus. Replace them
before the final near-optimality campaign. For each parameter, the effective
experimental resolution must be the least precise of:

```text
commanded adjustment step
absolute calibration uncertainty
run-to-run reproducibility
long-term drift during data taking
```

For example, a translation stage may have a 0.01 mm readout step while the
magnet can only be repositioned reproducibly to 0.05 mm. In that case, 0.05 mm
is the scientifically relevant resolution. The same principle applies to laser
intensity and detuning.

At the provisional resolutions, the current rectangular domain contains far too
many combinations for brute-force production runs. Use adaptive screening and
challenger elimination rather than assuming every grid point must receive the
full production particle budget.

Use the following challenger-elimination procedure:

1. Select the current recommended point or robust region.
2. Use the screening/refinement model to identify every setting that could still
   plausibly improve conditional capture by more than epsilon.
3. Evaluate those challenger settings with paired particles and seeds.
4. Use uncertainty intervals for the paired difference between each challenger
   and the recommendation.
5. Add particles and seeds adaptively to unresolved challengers.
6. Stop only when no distinguishable setting in the defined domain has a
   plausible improvement larger than epsilon.

Account for the fact that many challengers are compared; do not treat many
ordinary pointwise 95% intervals as one simultaneous 95% guarantee. Use an
appropriate simultaneous-confidence or familywise-error procedure in the final
analysis.

The defensible conclusion is therefore:

```text
Within the stated physical domain and experimental control resolution,
the data provide 95% confidence that no distinguishable setting improves
conditional capture by more than 0.05 percentage points over the
recommended setting or region.
```

This is strong statistical evidence of epsilon-near-optimality within the tested
laboratory domain. It is not an assumption-free mathematical proof over every
real-valued parameter combination.

## Stage 5: production prediction

Status as of 2026-08-31: **complete; stopping rule passed.**

The locked production setting is:

```text
s0:             1.474497
detuning_gamma: -1.1840645
magnet_radius:  0.049217614 m = 49.217614 mm
solver:         RK4StHybridCustom
dt:             0.625 microseconds
```

The final dataset uses all available particles from 20 independent Zeeman/MOT
ensemble pairs: 592,319 Zeeman survivors were simulated and 15,840 were
captured. The pooled conditional efficiency is 2.6742346607%.

For a new equivalent input of 10,000,000 Zeeman survivors:

```text
expected captured atoms: 267,423
95% prediction range:    263,195 to 271,652 atoms
efficiency range:        2.6319496% to 2.7165198%
95% half-width:          0.042285 percentage points
stopping target:         <= 0.05 percentage points (PASS)
```

The prediction combines the binomial counting variance expected in a future
10,000,000-particle run with uncertainty in the estimated mean. The latter is
chosen conservatively as the larger of the pooled-binomial estimate and the
empirical between-ensemble estimate. In the final data the pooled-binomial term
was larger, so the normal 1.96 critical value was used.

The local sensitivity confirmation evaluated the most actionable shifted point,
`detuning=-1.2040645 Gamma` and `radius=49.317614 mm`, at the selected `s0` and
at `s0=1.5`. Their mean conditional captures were 2.690% and 2.685%, compared
with 2.712% for the nominal point in the matched confirmation sample. Paired
mean differences were -0.022 and -0.027 percentage points. The corresponding
95% intervals, [-0.125928, +0.081928] and [-0.102484, +0.048484] percentage
points, remain wider than the strict +/-0.05-point equivalence margin. The
observed local response is therefore practically flat in its means, but the
data do not prove simultaneous equivalence of every continuous setting in a
parameter box.

No further 2D-MOT optimization, timestep, sensitivity, or conditional
production runs are required under the present model and apparatus constraints.

On Zeus, scheduler and multiprocessing startup are material.  Use three
long-lived 200-core workers within the 600-core quota, and let each worker run
multiple assigned seeds sequentially.  Save every seed independently so that a
partial batch remains reusable.

The particle count and seed count have different roles:

```text
more particles per setting:
    reduce capture-counting noise

more independent seeds:
    establish repeatability and estimate run-to-run prediction

same paired particles and seeds across candidates:
    make differences between candidates much more precise
```

At a conditional efficiency near 2.45%, a simple independent-particle estimate
suggests that several hundred thousand simulated Zeeman survivors will be needed
to reach a prediction half-width near 0.05 percentage points. This is only a
planning estimate. The actual stopping decision must use the measured stochastic
and between-ensemble variation.

Report both the percentage and the count-scale prediction:

```text
recommended joint parameter region or setting
expected conditional capture efficiency
95% predicted range for a new run
expected captured atoms per 10,000,000 Zeeman survivors
paired near-optimality tolerance and conclusion
simulation domain, experimental resolution, particle count, and seed count
```

## Stage 6: full unfiltered apparatus prediction

Status as of 2026-09-01: **complete.**

The completed campaign followed this procedure:

1. Generate the full unfiltered thermal distribution.
2. Run the Zeeman slower.
3. Estimate the physical Zeeman-survivor flux from the simulated survival
   fraction and the Yb-171 oven flux.
4. Apply the already completed conditional 2D-MOT prediction to that flux; do
   not rerun the 2D MOT merely for this conversion.
5. Report the expected oven-to-Zeeman and oven-to-2D-MOT atom fluxes with their
   uncertainty intervals.

Keep the conditional 2D-MOT result and the end-to-end oven result separate. They
have different denominators and answer different experimental questions.

The production design and result were:

```text
thermal atoms simulated:           5,000,000
independent batches:               100 x 50,000
angular cutoff:                    none
microtube divergence broadening:   3x
Zeeman survivors:                  17,168
Zeeman survival fraction:          0.343360%
exact-binomial 95% interval:       0.338251%-0.348526%

modeled Yb-171 oven flux:          7.38634e13 atoms/s
expected Zeeman-survivor flux:     2.53617e11 atoms/s
Zeeman flux 95% interval:          2.49844e11-2.57433e11 atoms/s

conditional 2D-MOT efficiency:     2.6742347%
total oven-to-2D-MOT efficiency:   0.00918225%
expected 2D-MOT capture flux:      6.78232e9 atoms/s
combined statistical 95% range:    6.63701e9-6.92764e9 atoms/s
```

For the combined interval, let `p_Z` be the full-angle Zeeman survival estimate
and `p_M` the conditional 2D-MOT estimate. The total efficiency is `p_Z p_M`.
Independent statistical variances are propagated with the first-order product
formula

```text
Var(p_Z p_M) ~= p_M^2 Var(p_Z) + p_Z^2 Var(p_M)
```

with the small variance-product term included in the numerical calculation and
a normal 1.96 critical value. This interval describes simulation sampling
uncertainty. It does not include systematic uncertainty in the vapor-pressure
correlation, oven temperature and geometry, natural abundance, or angular
distribution model.
