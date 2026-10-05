# Donut blue-beam ablation, 600 atoms, 100 ms

This directory archives the merged Zeus result and the automatically selected
representative trajectory for the causal donut ablation completed on
2026-09-13. All variants used the same 600 input atoms, seeds, green MOT,
magnetic field, and blue operating point.

| Variant | Capture eligible at least once | Fraction |
|---|---:|---:|
| full donut | 491/600 | 81.8% |
| without positive-z blue beams | 65/600 | 10.8% |
| without transverse-y blue beams | 333/600 | 55.5% |
| counterpropagating pair, full shell | 53/600 | 8.8% |
| counterpropagating pair, single pass | 5/600 | 0.8% |

The cleanest test of repeated blue access is the last pair of rows. The beam
directions and all other settings are identical; only the single-pass variant
is terminated 10 mm upstream. Continued access to the shell increased capture
by a factor of 10.6. This supports the hypothesis that one entrance encounter
is insufficient for most atoms.

Repeated access is not the whole explanation. Restoring the remaining donut
directions raises capture from 53 to 491 atoms. Removing positive-z blue beams
causes the largest ablation loss, consistent with the need to cool reversed or
oscillatory motion and balance radiation pressure. Removing the transverse-y
pair produces a smaller but still substantial loss, establishing the value of
three-dimensional blue cooling.

The representative global particle index is 382. It was selected by a fixed
rule: captured by the full donut, not captured by the single-pass control, and
maximum number of separated full-donut blue-exposure episodes among eligible
candidates. Its three exposure windows (using the configured 1% threshold)
are approximately 3.74--5.29 ms, 6.50--15.38 ms, and 24.14--30.02 ms. The
third encounter occurs well after the entrance interaction. The trajectory is
an illustration; the 600-particle paired population result is the primary
evidence.

`merged/donut_ablation_summary.json` contains the time-resolved population
curves and merged diagnostics. `representative/representative_trajectory.npz`
contains the five trajectories and the six per-beam 399-nm intensity traces.
