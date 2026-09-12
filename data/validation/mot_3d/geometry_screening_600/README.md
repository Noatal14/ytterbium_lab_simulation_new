# Archived 3D-MOT geometry screening

This directory preserves the compact merged results of the 600-particle
screening run completed on Zeus on 2026-09-10. The seven experimental
crossed-blue candidates were subsequently removed from `config.py`; this is an
evidence archive, not an active configuration source and not an optimization.

The positive-control `angled_donut` captured 452/600 atoms (75.3%). The best
crossed-beam candidate, `vertical_cross_mid_wide`, captured 20/600 (3.3%);
the other candidates captured 0--8 atoms. All candidates passed the same
static checks: the green force was restoring on both sides of the equilibrium
along every lab axis, the blue intensity at the MOT center was exactly zero,
and a +z-moving on-axis atom experienced a net negative-z blue force with
cancelling paired transverse components. Thus the poor capture signal cannot
be attributed to a reversed polarization or blue leakage at the center.

## Tested geometries

Atoms propagate along lab +z and gravity acts along -x. Every crossed-blue
beam was 30 degrees from z and propagated upstream. A yz pair used normalized
directions `(0, +0.5, -sqrt(3)/2)` and `(0, -0.5, -sqrt(3)/2)`; an xz pair used
`(+0.5, 0, -sqrt(3)/2)` and `(-0.5, 0, -sqrt(3)/2)`.

- `horizontal_cross_near`: two yz blue beams, 5-mm waist, crossing 10 mm
  upstream, hard cutoff 5 mm upstream.
- `horizontal_cross_mid`: two yz blue beams, 10-mm waist, crossing 20 mm
  upstream, hard cutoff 10 mm upstream.
- `horizontal_cross_far_wide`: two yz blue beams, 15-mm waist, crossing 30 mm
  upstream, hard cutoff 10 mm upstream.
- `horizontal_cross_at_gate`: two yz blue beams, 10-mm waist, crossing on the
  cutoff plane 10 mm upstream.
- `vertical_cross_mid_wide`: two xz blue beams, 10-mm waist, crossing 20 mm
  upstream, hard cutoff 10 mm upstream.
- `vertical_cross_far_wide`: two xz blue beams, 15-mm waist, crossing 30 mm
  upstream, hard cutoff 10 mm upstream.
- `dual_plane_four_blue`: both the xz and yz pairs, 10-mm waists, crossing
  20 mm upstream, cutoff 10 mm upstream. Per-beam blue s0 was halved so the
  nominal total intensity remained comparable to a two-beam candidate.

All seven candidates reused the six-beam green MOT with quadrupole strong axis
y. Green xz beams used right circular polarization and green +/-y beams used
left circular polarization; all candidate blue beams used right circular
polarization in the simulation convention. The force checks, rather than the
polarization names alone, establish the physical sign: displacement to either
side of the gravity-shifted equilibrium gives a green force toward equilibrium
on x, y, and z. For an atom moving along +z, the paired blue force points along
-z on the symmetry axis and its x/y components cancel.

`results.csv` contains the preserved best-anchor metrics printed from the
merged report. The historical screening verdict `promising_for_confirmation`
meant only that restoring force, darkness, overlap, and slowing preconditions
passed; it did not mean that capture performance was competitive. The measured
capture counts show that none of the seven candidates approached the donut.
