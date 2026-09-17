# Why the full donut and five-beam MOT are the two optimization candidates

## Purpose and scope

This note records why the next full 3D-MOT optimization should concentrate on
two configurations:

1. the full six-blue-beam `angled_donut`, as the current performance reference;
2. the gravity-assisted `five_beam_gravity` MOT, as the experimentally simpler
   alternative.

The present simulations do **not** yet decide which of these two configurations
the laboratory should build. Their purpose is to show why both deserve a fair
full optimization, and why the tested reduced-blue variants of the six-beam MOT
do not currently justify replacing the full donut.

All operating points quoted below are simulation-study values, not measured or
approved laboratory settings.

## Common comparison rule

Unless stated otherwise, the paired comparisons use the same 600 survivors of
the 2D MOT, the same initial states, the same numerical settings, and the same
capture definition. The primary usable-atom criterion at 100 ms is

- distance from the 3D-MOT center no larger than 5 mm; and
- total speed no larger than 1 m/s at that time.

An atom is not permanently disqualified for leaving the region earlier: it may
return and count as usable at 100 ms. This is the relevant metric for deciding
how many atoms are available after the loading interval. “Usable at least once”
is retained as a diagnostic, but it is not substituted for the final count.

## The full angled donut

### Geometry

The full donut has six 556-nm MOT beams and six coaxial 399-nm blue beams on
three axes: two axes in the xz plane at ±30 degrees from lab z, and the y axis.
The blue beams are center-blocked and the green beams are confined to the
complementary core. The trapped central region is therefore exactly dark to
399-nm light. The magnetic quadrupole strong axis is y. The two xz pairs use
right-handed polarization and the y pair uses left-handed polarization; force
tests verify restoring green force on both sides of all three lab axes.

The geometry is shown in
[`01_angled_donut_geometry.png`](../graphs/mot_3d_configuration_decision/01_angled_donut_geometry.png).

### Present performance evidence

On the shared 600-particle comparison, the full donut produced 491 usable atoms
(81.8%). On the full 15,840-particle ensemble it produced approximately 82%
usable atoms at 100 ms. A continuation from 100 to 400 ms lost only 10 of
12,989 donut survivors, so the population was effectively flat on this time
scale and no defensible exponential lifetime could be extracted.

The loading and long-hold comparison is shown in
[`03_historical_retention_comparison.png`](../graphs/mot_3d_configuration_decision/03_historical_retention_comparison.png).
The five-beam trace in that historical figure belongs to an older operating
point and should not be interpreted as the expected lifetime of a future
optimized five-beam MOT.

## Why reduced-blue six-beam variants were rejected

The initial hypothesis was that some of the blue beams might be redundant. We
tested this directly by changing only selected blue-beam groups while retaining
the same input atoms, green MOT, magnetic field, and blue operating point.

| Blue configuration | Usable atoms | Fraction of 600 | What the comparison tests |
|---|---:|---:|---|
| full donut | 491 | 81.8% | reference with all six blue beams |
| remove the blue pair with positive-z propagation components | 65 | 10.8% | role of cooling reversed/oscillatory longitudinal motion |
| remove the transverse y blue pair | 333 | 55.5% | role of nominally transverse blue cooling |
| retain only one counterpropagating blue pair with continuous shell access | 53 | 8.8% | whether one blue axis is sufficient |
| same counterpropagating pair, restricted to a single upstream pass | 5 | 0.8% | whether one blue encounter is sufficient |

The primary population comparison is
[`04_donut_blue_beam_ablation.png`](../graphs/mot_3d_configuration_decision/04_donut_blue_beam_ablation.png).
The corresponding entrance phase-space acceptance is summarized in
[`06_capture_probability_by_entrance_condition.png`](../graphs/mot_3d_configuration_decision/06_capture_probability_by_entrance_condition.png),
and the individual longitudinal-velocity histories are figures 08--12 in the
same
[`graphs/mot_3d_configuration_decision`](../graphs/mot_3d_configuration_decision/)
directory.

These results support three conclusions.

First, the y-directed blue pair is not redundant even though it is transverse
to the incoming atomic-beam axis. Removing it reduced capture by 158 atoms,
from 491 to 333, a relative loss of 32% of the full-donut captured population.
The incoming ensemble has nonzero transverse position and velocity spread, and
the atoms acquire transverse and oscillatory motion during loading. A
three-dimensional cooling geometry therefore cannot be judged only from the
initial mean +z motion.

Second, the blue beams that address the opposite longitudinal sense are
essential. Removing the pair with positive-z propagation components reduced
capture from 491 to 65. Trajectories show that atoms can reverse direction or
cross the central region more than once; a beam group that looks unimportant
for the first entrance can become the restoring/cooling group after reversal.

Third, repeated access to blue light matters. For the same isolated
counterpropagating pair, continuous shell access captured 53 atoms whereas a
single upstream pass captured only 5, an improvement by a factor of 10.6.
The representative trajectory in
[`05_representative_donut_trajectory.png`](../graphs/mot_3d_configuration_decision/05_representative_donut_trajectory.png)
contains separated blue-exposure episodes, including a later encounter well
after the entrance interaction. This trajectory illustrates the mechanism;
the paired 600-particle population result is the stronger evidence.

Focused tuning did improve the reduced-blue alternatives, so the conclusion is
not based only on an intentionally poor single-pass operating point. The
initial one-pair single-pass ablation captured 5/600 atoms (0.8%). A focused
scan of blue detuning and intensity increased the best one-pair result to
52/600 (8.7%). A later finite entrance-gate implementation reached 115/600
atoms usable at 100 ms (19.2%). Finally, adding and positioning a second finite
blue pair as a downstream slowing backstop reached 188/600 (31.3%). These
numbers come from successive study versions whose diagnostic labels evolved,
so the intermediate values should not be interpreted as one rigorously paired
optimization curve. The decisive endpoint comparison is nevertheless paired:
the best retained four-blue geometry gave 188/600 versus 491/600 (81.8%) for
the full donut on the same 600-atom input ensemble and 100-ms usability
criterion.

The four-blue endpoint demonstrates that a downstream backstop can rescue
overshooting atoms, but it remains 303 atoms below the full donut. Its position
optimum was also locally bracketed: the best crossing was +35 mm, while +40 and
+45 mm performed worse. The result is therefore not explained simply by having
stopped the gate scan too close to the MOT.

Together, the ablations and finite-gate studies show that the donut's advantage
is not merely “more laser power.” Its six blue directions provide repeated,
three-dimensional access to atoms whose directions change during capture. The
tested removals and relocations narrow the accepted phase space substantially.
For a six-green-beam MOT, the current evidence therefore supports keeping the
full blue donut rather than optimizing another reduced-blue geometry.

## The gravity-assisted five-beam MOT

### Geometry and experimental motivation

The five-beam configuration removes one green beam along the gravity axis and
uses gravity together with the remaining unpaired green beam. The other four
green beams form two counterpropagating pairs. Its quadrupole strong axis is x,
the gravity axis. The paired yz directions have complementary green cores and
blue shells; the unpaired +x direction is green only. The polarizations and
strong-axis assignment have dedicated force-sign tests confirming restoring
force on both sides of x, y, and z when gravity is included.

The geometry is shown in
[`02_five_beam_geometry.png`](../graphs/mot_3d_configuration_decision/02_five_beam_geometry.png).

Its main advantage is experimental: one fewer green MOT beam and a geometry
that avoids the difficult alignment of the complete six-blue angled donut.
Its main physical disadvantage is the absence of an optical counterbeam on one
axis. Gravity is a fixed force rather than a velocity-selective counterbeam, so
the equilibrium and capture volume can be more sensitive to intensity,
detuning, and magnetic gradient. It may also accept a narrower set of incoming
trajectories and retain a smaller fraction of atoms that are temporarily slow.

### Completed pre-optimization evidence

The first targeted local grid found 194/600 atoms at 100 ms at gradient
1.5 G/cm and lower-green `s0=2`. Because the intensity lay at the scan boundary,
a second 3-by-4 grid tested gradients 1.4/1.5/1.6 G/cm and lower-green
`s0=1/1.5/2/2.5`. It selected the following provisional starting point:

- magnetic gradient: 1.4 G/cm;
- unpaired lower-green saturation parameter: `s0 = 2.5`;
- paired-green saturation parameter: `s0 = 10`;
- green detuning: `-20 Gamma`;
- blue saturation parameter: `s0 = 1`;
- blue detuning: `-2 Gamma`.

At this point, 232/600 atoms were usable at least once and 202/600 were usable
at 100 ms (33.67%), giving 87.1% final retention among the ever-usable set. The
ranked local comparison and its first grid are shown in
[`13_five_beam_local_grid_ranking.png`](../graphs/mot_3d_configuration_decision/13_five_beam_local_grid_ranking.png)
and
[`14_five_beam_local_grid_heatmap.png`](../graphs/mot_3d_configuration_decision/14_five_beam_local_grid_heatmap.png).
The completed boundary check is shown in
[`15_five_beam_boundary_grid_ranking.png`](../graphs/mot_3d_configuration_decision/15_five_beam_boundary_grid_ranking.png)
and
[`16_five_beam_boundary_grid_heatmap.png`](../graphs/mot_3d_configuration_decision/16_five_beam_boundary_grid_heatmap.png).

The selected five-beam point was then repeated on the same 600 initial atoms
across five recoil seeds. It gave a mean usable fraction of 31.23%, sample
standard deviation 1.70 percentage points, and observed range 29.67--33.83%.
The paired donut gave 83.40% ± 1.37 percentage points, with range
81.50--84.83%. The repeatability comparison is shown in
[`17_finalist_repeatability.png`](../graphs/mot_3d_configuration_decision/17_finalist_repeatability.png).
The non-overlapping ranges establish that the performance gap is much larger
than the simulated recoil-seed variation.

This result is comparable to the best reduced-blue four-beam geometry
(202 versus 188 atoms), but both remain far below the unoptimized paired donut
control (491 atoms). The five-beam design nevertheless remains worth a full
optimization because it is a different experimental architecture with a large
practical simplification—not because its present simulated capture matches the
donut.

## What the reported percentages and ranges mean

The single values such as 491/600 = 81.8% are exact fractions for one specified
600-particle Monte Carlo run. They are not experimental efficiencies with a
measurement error bar.

To estimate sensitivity to stochastic recoil, the same 600 initial atoms were
rerun with five independent recoil seeds. The full donut gave
`83.40% ± 1.37 percentage points`, with a minimum-to-maximum range of
81.50--84.83%. Here:

- 83.40% is the mean of the five captured fractions;
- 1.37 percentage points is the **sample standard deviation across those five
  recoil seeds**;
- 81.50--84.83% is the observed minimum-to-maximum range;
- this is not a standard error, confidence interval, experimental uncertainty,
  or alignment-tolerance estimate.

The finite four-blue representative gave `29.60% ± 1.48 percentage points` in
the earlier three-family repeat. The completed finalist repeat supersedes that
study's pre-refinement five-beam number: the selected five-beam point gave
`31.23% ± 1.70 percentage points`, with an observed 29.67--33.83% range. The
donut/five-beam separation is therefore much larger than the observed
stochastic spread.

A subsequent direct stability comparison used all 15,840 validated 2D-MOT
survivors and propagated the corrected five-beam point continuously through
400 ms. The five-beam population contained 4,706 usable atoms at 100 ms,
reached its maximum of 4,721 atoms at 118.9 ms, and contained 4,718 atoms at
400 ms. The paired historical donut curve contained 12,992 usable atoms at
100 ms and 12,989 at 400 ms. The best retained four-blue entrance-plus-backstop
configuration contained 4,629 and 4,631 atoms at the same times. None of the
three curves had sufficient post-peak loss to justify an exponential lifetime
fit. Thus the present five-beam disadvantage is capture efficiency, not an
observed 100--400 ms retention failure. The common-scale comparison is shown
in
[`18_finalist_loading_and_stability.png`](../graphs/mot_3d_configuration_decision/18_finalist_loading_and_stability.png).

## Advantages and disadvantages to present to the laboratory team

| Candidate | Advantages | Disadvantages | Current evidence status |
|---|---|---|---|
| full angled donut | highest capture by a large margin; broad initial phase-space acceptance; repeated cooling after reversals; effectively no loss from 100 to 400 ms in the tested run | six blue beams and six green beams; more optics, alignment, and access constraints | strong performance, ablation, trajectory, phase-space, force, and long-hold evidence; still needs a systematic full optimization |
| five-beam gravity MOT | fewer MOT beams; simpler and likely more practical laboratory construction; repeatable nonzero capture; no measurable population decay through 400 ms at the tested corrected point | currently much lower capture; asymmetric force balance; likely greater sensitivity to gradient and unpaired-beam settings; alignment tolerance remains unknown | force, boundary-grid, stochastic-repeat, full-ensemble trajectory, and 400-ms stability evidence complete; still needs a systematic full optimization |

## Recommendation before full optimization

Proceed with separate, fair full optimizations of the donut and five-beam
families. Do not spend the main optimization budget on the tested reduced-blue
six-beam variants: their best result remains far below the donut, and the
paired ablations explain why the omitted blue directions are physically useful.

The boundary check and matched five-seed repeat are complete. The selected
gradient remains at the low edge of the boundary grid, so the full five-beam
optimization must extend below 1.4 G/cm; a reasonable initial gradient range is
approximately 1.0--1.6 G/cm. This edge result is now an optimization-range
constraint rather than a reason for another separate screening run. After both
full optimizations, compare them on a common full ensemble using:

1. usable population versus time through 100 ms;
2. longer retention and `tau` only if a genuine exponential tail exists;
3. capture fraction and stochastic repeatability;
4. initial phase-space acceptance and representative failure trajectories;
5. sensitivity to small parameter and alignment changes;
6. beam count, optical access, alignment time, and implementation risk.

The final choice should then be made by the laboratory team as an explicit
trade-off: the donut is presently the clear performance reference, while the
five-beam MOT is the only simplified architecture that still merits serious
optimization because its construction advantage may justify some loss in atom
number.
