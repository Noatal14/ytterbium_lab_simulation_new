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

Current new-campaign policy is v2: every 3D evaluation ends at 50 ms, search
uses 10 us and sealed final validation uses 5 us. v1 specifications and
historical campaign files are retained unchanged. Old campaigns must use
their pinned code/runtime for execution; current code must not reinterpret
their 100-ms / 0.625-us results as v2 results or silently migrate them.

Completed individual-run results remain readable through their frozen records.
Previously configured but unstarted runs may need a fresh preview/configuration
after upgrading: submission deliberately rejects stale numerical-policy hashes.
In-flight Zeus runs still require their original pinned checkout revision.

1. `create` validates the completed 2D campaign, freezes every input hash and
   writes the PBS files. It submits nothing.
2. A new campaign starts at Discovery under the versioned pragmatic timestep
   policy: `10 us` for Discovery, preliminary check, refinement, closure and
   finalist selection; `5 us` for sealed final validation. Every evaluation
   uses a `50 ms` endpoint under policy v2. The
   2026-10-10 one-off study was inconclusive because its sentinel evidence was
   degenerate. These values are an explicit runtime tradeoff, not a convergence
   claim. The old provisional campaign remains unchanged; this policy always
   requires a newly created campaign.
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

python -u -m studies.mot_3d_campaign submit-discovery --campaign CAMPAIGN
python -u -m studies.mot_3d_campaign advance --campaign CAMPAIGN
python -u -m studies.mot_3d_campaign submit-stage --campaign CAMPAIGN
python -u -m studies.mot_3d_campaign submit-final-inputs --campaign CAMPAIGN
python -u -m studies.mot_3d_campaign status --campaign CAMPAIGN
```

`lab_setup/specifications/mot_3d_timestep_policy_v2.json` is the strict,
hash-pinned authority. It records the inconclusive study status, whether its
artifact hashes are locally available, the absence of a convergence claim and
the user-approved rationale. The one-off timestep code remains available for
historical reconstruction, but it is not a normal campaign stage.

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

## Completed canonical campaign (2026-10-20)

`mot_3d_s0_1p3_search10us_20261012_v1` is scientifically closed under an
explicit user-approved execution amendment: final validation used **5 us and
50 ms**, not the original 0.625-us / 100-ms plan. No timestep-convergence claim
is made. See [final results and closure](3D_MOT_FINAL_RESULTS.md).

The immutable evidence, paired 30/50-ms diagnostic, checkpoints, exact runtime
and publication-only repair are archived under
`data/validation/mot_3d/final_campaign_20261020/`. One-off runtime/submission and
time-comparison tools were retired from active source after this backup.
The subsequent v2 policy adopts 5-us / 50-ms final validation for new campaigns.
This does not relabel any historical run or rewrite its frozen protocol.

The original hashed remote `campaign.json` still records `final_validation`.
`campaign_closure_20261020.json` records the accepted final amended execution;
do not run ordinary `advance` on it or rewrite its provenance to make a UI
status appear complete. Software release acceptance remains a separate gate.

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
