# Canonical 3D-MOT campaign

This is the operational guide for the corrected-input 3D-MOT campaign. The
scientific rationale remains in `3D_MOT_FULL_OPTIMIZATION_PLAN.md`.

## Scientific separation

The completed canonical 2D-MOT campaign supplies 20 frozen survivor ensembles.
They are split before any 3D optimization into 12 discovery, four refinement,
and four preliminary-check ensembles. All 20 may later be used for final
candidate selection. They are never used for the final unbiased performance
claim. After the nominal points are locked, the campaign generates 20 new
Zeeman and 2D-MOT ensembles for sealed final validation.

The reported conditional efficiency is survivor weighted: its denominator is
the number of atoms leaving the selected 2D MOT. It is distinct from atomic
flux and from oven-to-3D efficiency.

## Lifecycle

1. `create` validates the completed 2D campaign, freezes every input hash and
   writes the PBS files. It submits nothing.
2. The campaign remains at `dt_validation_required` until paired timestep
   convergence evidence approves the already frozen screening and production
   timesteps. If different timesteps are needed, update the configuration and
   create a new campaign rather than modifying an existing one.
   Run `studies.mot_3d.timestep_validation` to compare 10, 5, 2.5, 1.25 and
   0.625 microseconds with a 0.3125-microsecond reference on the same balanced
   sample from all 20 frozen ensembles. The test covers both families, three
   sentinel profiles per family and five recoil seeds. Larger timesteps are
   exploratory and are accepted only when every simultaneous paired
   equivalence interval passes.
3. `submit-discovery` runs independent Optuna workers for the donut and
   single-pass families in restart-safe cumulative rounds.
4. Repeated `advance` and `submit-stage` commands perform the preliminary
   check, focused refinement, local closure, and finalist selection.
5. After finalist selection, `advance` locks both winners before any new final
   data exist. `submit-final-inputs` generates seeds 3035–3054 and their fixed
   2D-MOT survivor ensembles. A dependent job freezes their complete registry.
6. `advance` validates those inputs and writes the sealed 3D validation jobs.
   `submit-stage` evaluates both families on identical survivors and recoil
   seeds 44001–44003.
7. The final `advance` produces `final_report.json` and marks the campaign
   `complete` only if both crossed-bootstrap 95% intervals have half-width at
   most 0.75 percentage points. Otherwise it produces only
   `final_validation_status.json`, enters `final_validation_extension_required`,
   and makes no completed-performance claim.

## Commands

```bash
python -u -m studies.mot_3d_campaign create \
  --name NAME \
  --input-dir PATH_TO_CANONICAL_2D_SURVIVORS \
  --upstream-campaign PATH_TO_COMPLETED_2D_CAMPAIGN \
  --output-dir PATH_TO_NEW_3D_CAMPAIGN

python -u -m studies.mot_3d.timestep_validation prepare \
  --campaign PATH_TO_NEW_3D_CAMPAIGN

python -u -m studies.mot_3d.timestep_validation submit \
  --campaign PATH_TO_NEW_3D_CAMPAIGN

python -u -m studies.mot_3d_campaign approve-dt \
  --campaign PATH_TO_NEW_3D_CAMPAIGN \
  --evidence PATH_TO_APPROVED_DT_EVIDENCE_JSON

python -u -m studies.mot_3d_campaign submit-discovery --campaign CAMPAIGN
python -u -m studies.mot_3d_campaign advance --campaign CAMPAIGN
python -u -m studies.mot_3d_campaign submit-stage --campaign CAMPAIGN
python -u -m studies.mot_3d_campaign submit-final-inputs --campaign CAMPAIGN
python -u -m studies.mot_3d_campaign status --campaign CAMPAIGN
```

The timestep evidence file has this minimal schema (the numerical values must
exactly match the frozen manifest, including the order of `tested_dt_s`):

```json
{
  "kind": "mot_3d_timestep_validation",
  "status": "approved",
  "screening_dt_s": 1.25e-6,
  "production_dt_s": 0.625e-6,
  "reference_dt_s": 0.3125e-6,
  "tested_dt_s": [1e-5, 5e-6, 2.5e-6, 1.25e-6, 0.625e-6],
  "capture_bias_passed": true,
  "paired_decision_passed": true
}
```

Both pass flags must be true. The evidence file is hash-pinned into the
campaign. If convergence selects different timesteps, update the configuration
and create a new campaign; never mutate the existing manifest.

Always follow the stage printed by `status`; do not skip a transition. Submission
records intentionally prevent duplicate chains. A partial submission must be
inspected rather than silently resubmitted. Do not edit a campaign manifest or
result file by hand.

## Integrity guarantees

The campaign binds the Git commit, physical-model hash, exact source arrays and
metadata, particle subsamples, parameter domains, solver, timestep, selection
files, job IDs and result archives. Stage transitions reject missing, duplicate,
foreign, stale or hash-mismatched artifacts. Result JSON is written atomically;
large outcome archives use temporary files and atomic replacement.

The existing 20 ensembles support selection only. The final validation uses
newly generated sealed ensembles, crossed recoil seeds, and a hierarchical
bootstrap over ensembles, recoil realizations and particles within ensembles.
New-ensemble variation is reported separately and does not control the stopping
rule.

## Required post-campaign validation: 2D-to-3D transferability

Before deciding that every fixed 2D-MOT `s0` (or every small laboratory
retuning of the 2D MOT) requires an independent full 3D-MOT optimization,
perform a paired transferability study. Using identical Zeeman and MOT seeds,
generate 2D-MOT survivor ensembles at the canonical operating point and at
nearby 2D-MOT settings. Compare both:

- total survivor count and the resulting atomic flux; and
- the conditional survivor phase-space distribution, including positions,
  velocities, correlations, and other diagnostics relevant to 3D capture.

Then cross-evaluate frozen 3D-MOT operating points: run the 3D optimum selected
for each 2D setting on survivor ensembles produced by the other settings. Report
both conditional 3D capture efficiency and end-to-end flux. The decision is:

- if only survivor count changes materially and conditional 3D performance is
  stable, reuse the 3D optimum and update only the flux prediction;
- if survivor distributions change but cross-evaluated 3D performance remains
  stable, a separate full 3D optimization is not required;
- if the distribution shift causes a meaningful loss of conditional 3D
  performance, require at least a local 3D refinement, and use a full separate
  optimization when the local refinement is insufficient.

This validation is a required follow-up after the current canonical 2D and 3D
campaigns; it must not use the sealed final-validation ensembles for tuning.
