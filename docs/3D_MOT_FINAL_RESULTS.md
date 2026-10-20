# Final 3D-MOT campaign — closed 2026-10-20

Campaign: `mot_3d_s0_1p3_search10us_20261012_v1`.
The project owner accepted the reported Single-pass uncertainty and authorized
closure without additional sampling.

## Final held-out results

The fixed operating points were evaluated on 20 sealed ensembles (16,675
2D-MOT survivors), with recoil seeds 44001, 44002 and 44003 for each geometry:
100,050 atom integrations, not 100,050 independent incoming atoms.

| Geometry | Locked candidate | Capture at 50 ms | Bootstrap 95% confidence interval |
| --- | --- | --- | --- |
| Blue shell | `angled_donut_finalist_03` | 99.766% | 99.674%–99.855% |
| Single pass | `single_pass_finalist_01` | 27.496% | 26.620%–28.386% |

These are capture fractions **conditional on surviving the 2D MOT**, not
oven-to-trap efficiencies. Capture means distance from the 3D-MOT center no
greater than 5 mm and total speed no greater than 1 m/s at the endpoint.
The original source code in the archived runtime defines the exact comparisons.
The selected physical parameters are in the archived
`selection/locked_nominals.json`; they were not retuned on validation outcomes.

The approved final execution used `dt = 5 us`, duration `50 ms`, gravity and
the pinned hybrid stochastic solver. This superseded the planned 0.625-us /
100-ms evaluation; it is not a demonstrated timestep-convergence result.
Intervals use 20,000 crossed ensemble/recoil bootstrap draws with
within-ensemble particle resampling (seed 92001).

The original target was a confidence-interval half-width of 0.75 percentage
points. Blue shell met it (0.0905 pp); Single pass did not (0.8830 pp). The
owner explicitly accepted the latter interval. The numerical flag remains
`precision_target_met: false`; accepting uncertainty is not meeting the target.

## 30-ms comparison

| Geometry | Capture at 30 ms | Capture at 50 ms | Change (percentage points) |
| --- | --- | --- | --- |
| Blue shell | 99.482% | 99.766% | +0.284 |
| Single pass | 27.474% | 27.496% | +0.022 |

Across the three seeds, Blue shell lost 19 previously eligible trajectories
and gained 161 between the endpoints; Single pass lost none and gained 11.
Blue shell failed the recorded 0.25-pp equivalence checks; Single pass passed
for its tested locked profile. This does not establish equivalence for arbitrary
search configurations. The endpoint is **not globally shortened to 30 ms**.

## Evidence, recovery and closure

All paths below are relative to `data/validation/mot_3d/final_campaign_20261020/`:

- `closure.json`: authoritative closure, owner-accepted exception, exact design
  and SHA-256 inventory. The historical hashed campaign manifest is untouched.
- `final_validation_5us_50ms/`: all six JSON/NPZ results and both summaries.
- `diagnostics/`: paired endpoint results and publication recovery receipts.
- `evidence.tar.gz`: complete frozen output evidence, including all 504 checkpoints.
- `sealed_inputs.tar.gz`: all 16,675 frozen 3D input states, their metadata and
  2D replicate records. The original upstream Zeeman arrays remain on Zeus and
  are identified by the retained input manifest; they are not bundled here.
- `runtime_audit.tar.gz`: exact execution overlay, hashes, scheduler scripts
  and publication repair; the clean base commit is identified in the receipt.

A memory-allocation failure was recovered from saved checkpoints. The final
publication failed because a diagnostic key still named 100 ms. A separately
recorded publication-only repair validated the saved arrays and recreated the
JSON records without reintegrating atoms. Final merge job
`4806783.zeus-master` exited successfully. The runtime archive preserves the
original code and the repair rather than rewriting execution history.

The remote campaign directory is
`/home/tal.noa/ytterbium_lab_simulation_new/data/optimization/mot_3d/mot_3d_s0_1p3_search10us_20261012_v1`.
Its new `campaign_closure_20261020.json` supersedes the original pending stage
for this amended execution. Do **not** use ordinary `advance` to finalize these
exceptional outputs. Standard future campaigns retain their existing protocol.

The scientific campaign is finished. This does not certify every UI workflow
on Mac, Windows and Zeus: the separate release gate is
[UI_RELEASE_ACCEPTANCE_CHECKLIST.md](UI_RELEASE_ACCEPTANCE_CHECKLIST.md).
No unfinished manual acceptance check is marked as passed by this closure.
