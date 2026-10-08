# Automated 2D-MOT campaign for fixed laser intensities

## Campaign input contract

Each campaign uses an explicitly selected, versioned ensemble directory under
`data/particle_states/after_zeeman/<source-name>/`. Runtime inputs are generated
or imported and are not included in a fresh checkout. The campaign pins the selected
profile, Git revision, and a
physical-model hash. Seed roles are non-overlapping: discovery `3000-3004`,
refinement `3005-3009`, held-out confirmation/tuning `3010-3014`, and sealed
final validation `3015-3034`. All 35 ensembles must exist and pass provenance
validation before `create`; sealed ensembles may never be used for tuning.

Screening uses 2,000 particles per ensemble; refinement uses five ensembles of
10,000; confirmation/sensitivity use five held-out ensembles of 10,000; sealed
production uses every survivor in 20 new ensembles. Confirmation is selection,
not unbiased validation. Local sensitivity, a robust operating region, and
epsilon-near-optimality are separate claims. Control-resolution points use the
provisional `0.01 Gamma`/`0.01 mm`; a distinct stress test uses `0.02
Gamma`/`0.1 mm`. Do not present provisional values as apparatus capabilities.

PBS arrays are throttled to three 200-core or four 150-core tasks. Resume runs
only missing trials from an immutable total target. If this guide, the plan,
configuration, implementation, or prompt disagree, stop before submission,
report the discrepancy, and do not silently choose one source.

The framework accepts one or more explicitly supplied positive finite `s0`
values. Each remains fixed within its own detuning/radius optimization, and the
supplied list is frozen in the manifest. The current canonical run supplies
only `s0=1.3`; another requested value should use a clearly named campaign.

## Fixed scientific design

- detuning domain: `-1.55` to `-0.85` linewidths;
- magnet-radius domain: `0.045` to `0.051 m`;
- hybrid stochastic solver with `dt = 1.25e-6 s` for screening/refinement;
- hybrid stochastic solver with `dt = 6.25e-7 s` for confirmation,
  sensitivity, and final production;
- provisional control resolutions: `0.01` linewidth and `1e-5 m`;
- final uncertainty target: 95% prediction half-width no larger than `0.05`
  percentage points for `10,000,000` Zeeman survivors.

Every `s0` follows the same sequence:

1. two-particle smoke test;
2. broad paired Optuna screening;
3. focused refinement around three distinguishable screening candidates;
4. confirmation of five finalists on five held-out ensembles of 10,000 particles;
5. the deduplicated union of a provisional control-resolution grid
   (`+/-0.01 Gamma`, `+/-0.01 mm`) and a separate stress grid
   (`+/-0.02 Gamma`, `+/-0.1 mm`), normally 17 points;
6. production on all 20 accepted Zeeman ensembles.

Measured pilot throughput makes refinement much longer than the old 14-hour
allocation. Screening requests 24 hours. Refinement is submitted as four
restart-safe dependent rounds with cumulative targets `3`, `6`, `9`, and `10`
completed trials per worker, each with a 20-hour walltime. Every round uses the
same database, study name, immutable design ID, bounds, and sampler seed; resume
logic computes only the trials still needed for its cumulative target.

The winner is chosen deterministically by the largest lower endpoint of its
95% mean interval, then by mean capture. A boundary winner or an uncertainty
target failure is returned with a warning; it never causes the workflow to hide
the best tested result.

The local sensitivity grid is also part of winner selection. If a neighboring
point has a paired 95% confidence interval entirely above the confirmed center,
that neighbor is promoted to final production. Otherwise the confirmed center
is retained and statistically equivalent neighbors are reported as its stable
operating region.

## Operator instructions

Create a campaign once, for example:

```bash
python -m studies.mot_2d_s0_campaign create \
  --name mot_2d_available_power_2026 \
  --s0 1.30 \
  --ensemble-dir data/particle_states/after_zeeman/<SOURCE_DIRECTORY> \
  --zeeman-profile <PROFILE_RECORDED_IN_SOURCE_METADATA> \
  --output-dir data/optimization/mot_2d/s0_campaign_2026
```

Submit the printed PBS file. After it finishes successfully, run:

```bash
python -m studies.mot_2d_s0_campaign advance \
  --campaign data/optimization/mot_2d/s0_campaign_2026
```

Submit the next PBS file printed by `advance`. For refinement, run the printed
submission script once; it submits four rounds using Zeus's verified `afterok`
dependency on the preceding whole-array job ID returned by `qsub`. Then wait for
the whole chain before advancing. Repeat until the command prints
`CAMPAIGN COMPLETE`. At any time, progress is shown by:

```bash
python -m studies.mot_2d_s0_campaign status \
  --campaign data/optimization/mot_2d/s0_campaign_2026
```

All tasks are restart-safe: an already completed evaluation is retained. The
final report is `final_report.json` in the campaign directory. Final production
also saves every captured `(N, 6)` state ensemble under
`data/particle_states/after_2d_mot/final_ensemble_s0_<value>/` for later 3D-MOT
optimization.

Campaign outputs are runtime artifacts. Archive accepted sealed ensembles and
their metadata in the approved scientific-data store; do not rely on them being
present in Git.
