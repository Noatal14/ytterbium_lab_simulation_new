# 2D-MOT optimization and prediction plan

## Corrected-Zeeman rerun contract (2026-10)

The current corrected campaign instance supplies fixed `s0=1.3` and uses profile
`corrected_projectant_19ring_20261005`, the four-way seed split in the campaign
guide, five-by-10,000 refinement, held-out candidate confirmation, and a
separate 20-ensemble sealed final validation. Selection intervals are not
unbiased performance intervals. Robustness and epsilon-near-optimality remain
`not established` unless adaptive challenger testing and familywise paired
comparisons pass. Final uncertainty uses a cluster-aware bootstrap over
independent Zeeman/MOT ensemble pairs plus finite-count uncertainty. If this
plan, the guide, configuration, implementation, or prompt disagree, stop before
submission and report the discrepancy.

This document is the authoritative scientific plan for the current 2D-MOT
campaign. Update it when the experimental constraints, statistical target, or
accepted workflow changes. Do not infer the campaign goal only from an Optuna
script or one result directory.

The sources of truth have distinct roles. The code and configuration define
supported behavior and defaults. A campaign manifest freezes the exact inputs,
parameters, numerical settings, provenance, and seed roles for one run. This
plan records the scientific rationale, while the campaign guide and prompt
describe operation. If these disagree, stop rather than silently choosing one.

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
not necessarily a single sharp maximum. The numbers below are the historical
pre-correction production result and must not be reported as the outcome of the
corrected-Zeeman campaign:

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

## Canonical corrected-Zeeman parameters and constraints

The joint optimization variables are:

```text
s0
detuning_gamma
magnet_radius
```

Each campaign instance fixes every explicitly supplied intensity and searches
only detuning and radius for that intensity. The current canonical instance is:

```text
s0:             exactly 1.3
detuning_gamma: -1.55 to -0.85
magnet_radius:  0.045 to 0.051 m
```

The tool also accepts other positive finite fixed values, or several explicit
values in one campaign. Those values are frozen in the manifest and cannot be
changed during resume.

## Stage 1: cheap paired screening

Use the same fixed particles and random streams for every parameter point:

```text
5 discovery Zeeman ensembles (seeds 3000-3004)
2,000 particles per ensemble
10,000 particles per parameter point
3 workers x 17 completed trials
```

This stage is only for locating promising regions, identifying parameter
interactions, rejecting poor regions, and detecting optima that reach search
boundaries. At a capture efficiency near 2.5%, only about 150 atoms are captured
per 6,000-particle point, so these trial values are too noisy for final reporting.

## Stage 2: focused refinement

Narrow the domain around promising regions and increase the statistical effort:

```text
exactly 5 refinement ensembles (seeds 3005-3009)
10,000 particles per ensemble
paired particles and MOT random streams for every candidate
```

Map the joint high-performing region rather than reporting three independent
one-dimensional ranges. Parameter correlations can make some combinations of
otherwise acceptable individual ranges perform poorly.

## Stage 3: held-out validation

Use five held-out Zeeman/MOT pairs (seeds 3010-3014), 10,000 particles per
ensemble, to select among five distinguishable finalists and then evaluate the
deduplicated sensitivity union. These data are held out from Optuna discovery,
but because they select/tune the recommendation they are not the sealed unbiased
performance estimate. That estimate uses seeds 3015-3034 and all survivors.

Use the hybrid stochastic solver at 0.625 microseconds for finalist selection,
sensitivity, and the sealed production estimate. This is the active numerical
protocol. Screening and refinement use the same solver at 1.25 microseconds for
efficiency. Do not substitute the historical 10- or 5-microsecond protocols.

For a new experimentally available laser intensity, use the maintained
`studies.mot_2d_s0_campaign` workflow rather than recreating the historical
timestep investigations.

## Numerical-method provenance (historical, not operational)

Earlier work compared 10 and 5 microseconds, then extended the study from 5 to
0.3125 microseconds. The old 10-versus-5 comparison found a paired difference of
+0.060106 percentage points, with a 95% interval from +0.032474 to +0.087739
percentage points; those two historical settings were therefore not equivalent
under the predeclared +/-0.05-point tolerance. Later comparisons found no
monotonic capture trend as the timestep was repeatedly halved. Repeated
1.25-versus-0.625 batches gave mean differences of +0.054 and +0.047 percentage
points, while 0.625 versus 0.3125 gave -0.067 percentage points with an interval
that included zero. These results motivated the active 1.25/0.625-microsecond
working/production split.

The exploratory calibration selected `Ni = 15` as the transition point at which
the mean relative discrepancy between Poisson and Gaussian recoil sampling was
approximately 1.99%. This value is not a requirement to use the Gaussian
approximation. `RK4StHybridCustom` samples the absorption count and associated
isotropic emission recoils from the exact Poisson model whenever `Ni < 15`, and
uses the faster Gaussian approximation only at or above the calibrated threshold.

`F_min` belonged to the same superseded Gaussian-only timestep estimate: it was
a historical force scale used with `N_min` to construct a proposed lower bound
on `dt`. It is not an active force or capture cutoff, and that lower-bound
argument does not constrain `RK4StHybridCustom`. The current 1.25-microsecond
working timestep and 0.625-microsecond production timestep are locked empirical
protocol choices, not consequences of `N_min` or `F_min`.

A trajectory diagnostic on three independent 2,000-particle ensembles found
that 95.1738% of laser-step evaluations had `Ni < 15`, accounting for 14.3490%
of the expected photons. The corresponding photon fractions were 8.7943% for
captured trajectories and 17.2808% for non-captured trajectories. The low-count
regime is therefore material, which is precisely why the accepted solver uses
Poisson sampling there. Re-run `studies.mot_2d.validation.photon_counts` if the
laser settings, recoil model, or solver transition rule changes.

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

This numerical result belongs to the historical pre-correction campaign and is
not the canonical corrected-Zeeman result. Its original interval calculation is
retained only for provenance. New campaign reports use a 20,000-draw
cluster-aware parametric bootstrap: independent Zeeman/MOT pairs are resampled,
finite within-pair capture uncertainty is sampled with a Jeffreys beta model,
the probabilities are pooled with the resampled survivor counts as weights,
and future counting noise for 10,000,000 survivors is sampled binomially.

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

No further optimization, timestep, sensitivity, or conditional-production runs
are required to close the historical pre-correction campaign. The active
corrected 19-ring campaign and a corrected full-angular flux calculation remain
outstanding before making a current apparatus-level claim.

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

Status as of 2026-10-06: **historical result; corrected-profile rerun required.**

The result described below used the former `active` 20-ring Zeeman profile, as
verified from all 100 run-metadata files. It must not be combined with the
corrected 19-ring 2D-MOT campaign. The procedure remains valid, but a new
versioned full-angular run with explicit corrected-profile provenance is needed.

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
