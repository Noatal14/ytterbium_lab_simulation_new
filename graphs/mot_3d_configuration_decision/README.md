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

The five-beam local-grid source data are stored in
`data/validation/mot_3d/five_beam_decision/local_grid_600/merged/five_beam_decision_summary.json`.
The best provisional five-beam point retained 194/600 atoms at 100 ms; its
lower-green `s0=2` lies on the tested boundary and therefore still requires a
small boundary check before full optimization.
