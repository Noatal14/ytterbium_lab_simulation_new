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
not necessarily a single sharp maximum. For a reporting reference of ten
million Zeeman survivors, the target statement has the following form:

```text
For the recommended 2D-MOT settings and 10,000,000 Zeeman survivors,
a new equivalent run has 95% predicted probability of capturing between
240,000 and 250,000 atoms.

Expected conditional capture efficiency: 2.45%
Target prediction half-width: 0.05 percentage points
```

The value `10,000,000` is a reporting reference chosen for communicating the
conditional efficiency. It is not an experimentally established Zeeman-survivor
count and does not come from the research proposal.

The current angle-prefiltered thermal source is valid for generating Zeeman
survivors for conditional 2D-MOT optimization. The angular cutoff was separately
validated as excluding atoms that do not survive the Zeeman stage. The resulting
prefiltered Zeeman survival percentage must not be reported as the end-to-end
survival percentage from the full oven flux.

After the 2D-MOT settings are locked, a separate end-to-end production campaign
will use the unfiltered thermal beam to predict total transmission from the oven.

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
10 microseconds using 20 independent Zeeman/MOT seed pairs. The final timestep
confirmation must reuse those exact 20 ensembles and MOT seeds at 5
microseconds. Treat the timestep as equivalent only if the paired 95% interval
for `5 us - 10 us` lies entirely within +/-0.05 percentage points.

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

Status as of 2026-08-27: **passed at the 10-microsecond production timestep.**
For the selected parameters, 20 independent ensembles give a mean conditional
capture of 2.568102%. For 10,000,000 Zeeman survivors, the model predicts
256,810 captured atoms, with a 95% prediction range of 252,372 to 261,248
atoms (2.523720% to 2.612484%). The prediction half-width is 0.044382
percentage points, below the predeclared 0.05-percentage-point target.

Run the locked finalists across all accepted independent Zeeman ensembles. Add
new Zeeman/MOT seeds adaptively until the predictive target for a new equivalent
run is met.

The current campaign starts this adaptive extension with five new independent
Zeeman ensembles.  After combining them with the ten accepted ensembles, apply
the predeclared stopping rule.  Combine uncertainty in the estimated mean with
the counting noise expected in a new run of 10,000,000 Zeeman survivors.  If
that 95% prediction has a half-width greater than 0.05 percentage points, add
another batch of five; do not keep running merely to reach an arbitrary round
seed count.

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

After the conditional 2D-MOT recommendation is locked:

1. Generate the full unfiltered thermal distribution.
2. Run the Zeeman slower.
3. Run the locked 2D MOT on its survivors.
4. Save the 2D-MOT survivors for the 3D-MOT campaign.
5. Estimate end-to-end transmission from the oven and convert it to laboratory
   flux/count predictions using a clearly stated time interval.

Keep the conditional 2D-MOT result and the end-to-end oven result separate. They
have different denominators and answer different experimental questions.
