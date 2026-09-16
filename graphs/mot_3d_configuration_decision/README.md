# 3D-MOT configuration-decision figures

This directory is the curated figure package accompanying
`docs/3D_MOT_OPTIMIZATION_CANDIDATE_RATIONALE.md`. The files are copies of
results retained in their original study directories; the source figures are
not moved or deleted.

| Figure | Purpose |
|---|---|
| `01_angled_donut_geometry.png` | Full six-green/six-blue donut geometry |
| `02_five_beam_geometry.png` | Gravity-assisted five-beam geometry |
| `03_historical_retention_comparison.png` | Donut through 400 ms and historical five-beam trace through 100 ms; the five-beam point predates the current optimization |
| `04_donut_blue_beam_ablation.png` | Paired population comparison after removing or relocating blue-beam groups |
| `05_representative_donut_trajectory.png` | One atom illustrating separated blue-exposure episodes and direction reversal |
| `06_capture_probability_by_entrance_condition.png` | Capture probability across initial phase-space bins |
| `07_shared_input_phase_space.png` | Initial phase-space distribution shared by the ablation variants |
| `08_full_donut_longitudinal_velocity.png` | All-atom longitudinal-velocity histories for the full donut |
| `09_without_positive_z_blue_velocity.png` | Velocity histories after removing the positive-z-component blue pair |
| `10_without_transverse_y_blue_velocity.png` | Velocity histories after removing the transverse-y blue pair |
| `11_single_pair_shell_velocity.png` | Velocity histories for one blue pair with continuous shell access |
| `12_single_pass_pair_velocity.png` | Velocity histories for the same pair restricted to one upstream pass |
| `13_five_beam_local_grid_ranking.png` | Ranked five-beam local-grid points with the paired donut control |
| `14_five_beam_local_grid_heatmap.png` | Final usable count versus gradient and unpaired lower-green intensity |
| `15_five_beam_boundary_grid_ranking.png` | Ranked boundary-grid points and paired donut control |
| `16_five_beam_boundary_grid_heatmap.png` | Boundary check around the selected gradient and unpaired green intensity |
| `17_finalist_repeatability.png` | Mean usable fraction and sample standard deviation across five recoil seeds for the donut and selected five-beam point |

The five-beam local-grid source data are stored in
`data/validation/mot_3d/five_beam_decision/local_grid_600/merged/five_beam_decision_summary.json`.
The boundary check selected gradient 1.4 G/cm and lower-green `s0=2.5`, with
202/600 atoms usable at 100 ms. Across five recoil seeds, this point gave
31.23% ± 1.70 percentage points, compared with 83.40% ± 1.37 percentage points
for the paired full donut. The uncertainty is the sample standard deviation
across recoil seeds, not experimental uncertainty.
