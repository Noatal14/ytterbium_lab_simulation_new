# Why the full donut and two-blue single pass are the optimization candidates

## Decision

The full optimization campaign will compare two experimentally relevant
architectures:

1. the full six-beam blue `angled_donut`, retained as the performance
   reference; and
2. a new `single_pass` geometry, retained as the simpler laboratory
   alternative.

The single-pass candidate keeps the same six 556-nm MOT beams as the donut but
uses only two localized 399-nm beams. The blue beams lie in the yz plane, cross
at a shared point upstream of the MOT, and both propagate with a negative-z
component against the incoming atoms. The initial implementation uses a 45°
included angle and a crossing at z = -10 mm. Both quantities will be optimized.

Geometry figures:

- [`01_angled_donut_geometry.png`](../graphs/mot_3d_configuration_decision/01_angled_donut_geometry.png)
- [`02_single_pass_geometry.png`](../graphs/mot_3d_configuration_decision/02_single_pass_geometry.png)

## Why the donut remains the performance reference

Paired 600-atom ablations used the same incoming atoms for every geometry. The
full donut produced 491/600 usable atoms (81.8%). Removing or localizing blue
beam groups reduced capture substantially:

| Blue-beam configuration | Usable atoms | Fraction |
|---|---:|---:|
| full six-beam donut | 491/600 | 81.8% |
| remove the +z blue pair | 65/600 | 10.8% |
| remove the transverse-y blue pair | 333/600 | 55.5% |
| retain one blue pair as a continuous shell | 53/600 | 8.8% |
| retain one blue pair as a single pass | 5/600 | 0.8% |

These results show that transverse cooling, forces in both longitudinal senses,
and repeated access to blue light all contribute to the demonstrated donut
performance. No reduced-blue geometry tested so far matches it.

Supporting figure:
[`05_donut_ablation_overview.png`](../graphs/mot_3d_configuration_decision/05_donut_ablation_overview.png).

## Why the single-pass candidate still merits optimization

The reduced-blue studies also show that a localized entrance pair is tunable.
In the earlier single-pass geometry, the initial point captured 5/600 atoms;
scanning blue intensity and detuning raised this to 52/600, and jointly tuning
blue intensity, detuning, and gate position raised it to 115/600 (19.2%). A
four-blue entrance-plus-return endpoint reached 188/600 (31.3%), but required a
second blue pair and still remained far below the full donut.

Those results motivate optimizing a two-blue architecture instead of spending
the main search budget on an intermediate four-blue system. The new candidate
is not identical to the earlier tuned pair: its two blue beams are now placed
in the yz plane and their angle is itself an optimization variable. Therefore,
115/600 is concept evidence, not a validated performance claim for the new
geometry.

Before the expensive search, the new yz single pass must pass a short paired
600-atom screen. A result around 20% is sufficient to establish that the
implementation behaves comparably to the earlier localized-pair concept and is
worth the full optimization budget. Failure of that screen triggers a geometry
and convention audit before any large run.

## Common metric

For both candidates, an atom is usable at the evaluation time when:

- its distance from the MOT center is at most 5 mm; and
- its total speed is at most 1 m/s.

The primary result is the conditional efficiency among 2D-MOT survivors. The
final report will also convert this fraction into the expected 3D-MOT atomic
flux using the independently estimated 2D-MOT output. Existing survivors may
be used for discovery and finalist selection; the final unbiased efficiency
claim is evaluated only on newly generated sealed ensembles.

## Parameters to optimize

The donut search is seven-dimensional:

- green s0, detuning, and waist;
- blue s0, detuning, and waist; and
- magnetic-field gradient.

The single-pass search is nine-dimensional:

- the same seven optical and magnetic parameters;
- the included angle between the two blue beams, constrained to 45-70°; and
- the z position of their crossing relative to the MOT center.

The green geometry remains fixed at the established 60/120° arrangement. Blue
s0 is capped at 1.5 for both candidates.

The detailed staged search, uncertainty calculation, independent validation,
and robust operating-box construction are specified in
[`3D_MOT_FULL_OPTIMIZATION_PLAN.md`](3D_MOT_FULL_OPTIMIZATION_PLAN.md).

## Final decision logic

The campaign does not assume that the simpler geometry will equal the donut.
It will deliver, for each candidate, recommended settings, conditional capture
with a 95% confidence interval, expected 3D-MOT atomic flux, and a supported
operating box in its optimized parameter space. The laboratory can then weigh
the measured performance and robustness against optical complexity and
alignment burden.

In short: the donut is optimized because it is the demonstrated performance
leader; the yz single pass is optimized because it is the clearest genuinely
simpler alternative and earlier localized-pair tuning showed meaningful room
for improvement.
