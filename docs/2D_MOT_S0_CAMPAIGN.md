# Automated 2D-MOT campaign for fixed laser intensities

Use this workflow when the available 2D-MOT laser intensity changes. It accepts
one or more `s0` values and automatically finds the recommended detuning and
magnet radius for each value. The operator runs jobs and advances completed
stages; no scientific choice is required between stages.

## Fixed scientific design

- detuning domain: `-1.55` to `-0.85` linewidths;
- magnet-radius domain: `0.045` to `0.051 m`;
- hybrid stochastic solver with `dt = 6.25e-7 s`;
- provisional control resolutions: `0.01` linewidth and `1e-5 m`;
- final uncertainty target: 95% prediction half-width no larger than `0.05`
  percentage points for `10,000,000` Zeeman survivors.

Every `s0` follows the same sequence:

1. two-particle smoke test;
2. broad paired Optuna screening;
3. focused refinement around three distinguishable screening candidates;
4. confirmation of three finalists on 10 ensembles of 10,000 particles;
5. a 3-by-3 local detuning/radius sensitivity grid;
6. production on all 20 accepted Zeeman ensembles.

The winner is chosen deterministically by the largest lower endpoint of its
95% mean interval, then by mean capture. A boundary winner or an uncertainty
target failure is returned with a warning; it never causes the workflow to hide
the best tested result.

## Operator instructions

Create a campaign once, for example:

```bash
python -m studies.mot_2d_s0_campaign create \
  --name mot_2d_available_power_2026 \
  --s0 1.20 1.30 1.40 \
  --output-dir data/optimization/mot_2d/s0_campaign_2026
```

Submit the printed PBS file. After it finishes successfully, run:

```bash
python -m studies.mot_2d_s0_campaign advance \
  --campaign data/optimization/mot_2d/s0_campaign_2026
```

Submit the next PBS file printed by `advance`. Repeat that exact pair of actions
until the command prints `CAMPAIGN COMPLETE`. At any time, progress is shown by:

```bash
python -m studies.mot_2d_s0_campaign status \
  --campaign data/optimization/mot_2d/s0_campaign_2026
```

All tasks are restart-safe: an already completed evaluation is retained. The
final report is `final_report.json` in the campaign directory. Final production
also saves every captured `(N, 6)` state ensemble under
`data/particle_states/after_2d_mot/final_ensemble_s0_<value>/` for later 3D-MOT
optimization.

The historical accepted `s0=1.474497` ensemble remains in the deliberately
shorter directory `final_ensemble_s0_1.47`; the exact value is preserved in its
metadata.
