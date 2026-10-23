# Fast campaign-flow testing

Do not run full scientific optimization campaigns to test application wiring.
Use three complementary layers:

| Layer | What runs | What it verifies | Expected scale |
| --- | --- | --- | --- |
| Browser/API contracts | Existing deterministic fixtures, all stage actions and failure states | Review/confirm, progress, resume, artifact validation, completion and duplicate prevention | Minutes |
| Real local backend | Existing Playwright real-backend integration with disposable fixture sources | Browser-to-API contracts, actual files, reviewed resource display and recovery | Minutes |
| Real scheduler acceptance | A separate, versioned miniature campaign profile under actual lifecycle qualification | Real submission, dependencies, state transfer, physical worker execution and merge | Hours for the complete physical lifecycle, plus queue time |

The existing browser suite already traverses the 3D stage controls using
mocked scheduler/results contracts. Those tests are useful but do not prove
that a complete physical campaign will finish on Zeus. The existing 2D smoke
stage is also not a miniature end-to-end campaign.

## Implemented TEST ONLY campaign profile

`npm run dev:acceptance` uses the versioned `ui_acceptance_v1` profile through
the normal 2D/3D campaign services, transfer, workers and validators. The profile
reduces particle and search budgets while retaining the ordinary stage topology,
separate search/validation populations and canonical physical policy.

Separate TEST ONLY kinds, immutable profile markers and dedicated namespaces
prevent scientific promotion. `dev:zeus-test` remains the individual-run mode.
Implementation and hermetic protocol coverage do not establish completed real
Zeus lifecycle qualification: consult the release evidence for each operating
system and stage, including outstanding blockers.

Run success plus held/failed jobs, interrupted checkpoint/resume, corrupt or
missing results, refresh/reconnection and double-confirmation cases. Keep
scientific campaigns and their budgets immutable. Test both 2D and 3D flows.

### Version 2: controlled 3D acceptance input

Maintainer-operated isolated backends can explicitly select
`--acceptance-profile ui_acceptance_v2`. The ordinary `dev:acceptance` launcher
still selects version 1. Version 2 has its own immutable specification,
`workflow_api/specifications/ui_acceptance_v2.json`, with policy SHA-256
`b7f40de6cbf9311e42408ecbc0ff3ecfa66195e2ebdab2287c317ee43c1517b7`.
It retains version 1's particle counts, stage topology, resources, separate
search/validation populations, 50-ms endpoint, 10-µs search timestep and 5-µs
validation timestep.

Version 2 accepts only the specifically pinned original O16 TEST ONLY 2D
handoff, including its campaign/report identity and all 40 survivor-state and
metadata file hashes. Original version-1 provenance is preserved. After normal
candidate selection, its explicit Single-pass candidate ordering exchanges
positions 0 and 2; Angled-donut ordering is unchanged. This controlled test
fixture exercises an interior refinement design instead of a boundary point
whose upstream perturbation duplicates the original point. Canonical scientific
selection, parameter bounds and duplicate rejection remain unchanged. This does
not guarantee that measured downstream results will pass.

All version-2 campaigns and outputs remain TEST ONLY in separate acceptance
namespaces and cannot be promoted to scientific inputs or results. A successful
bootstrap or transfer preview does not establish full lifecycle qualification;
record actual stage completion and final collection separately for each OS.

## Current regression commands

- Python: `python -m pytest -q`.
- UI unit/contracts: `npm test` in `ui`.
- Browser fixtures: `npm run test:e2e` in `ui`.
- Local real-backend integration: `node node_modules/@playwright/test/cli.js test --config=playwright.real-backend.config.ts` in `ui`, with the documented Python environment available.

Browser emulation is not Windows OS acceptance. Repeat the miniature real
workflow on actual Windows and Mac environments, using isolated Zeus targets.
The earlier 50-ms / 5-us policy update itself did not submit acceptance campaigns;
subsequent qualification jobs are recorded separately in the release evidence.

## Versioned acceptance policy foundation

`workflow_api/acceptance_profile.py` authenticates the checked-in
`workflow_api/specifications/ui_acceptance_v1.json` against its pinned canonical
SHA-256. This foundation alone does not enable submission or establish successful
full-lifecycle acceptance. Each normal campaign service, worker, renderer, and
validator must explicitly consume the authenticated manifest policy.

The acceptance kinds are `mot_2d_ui_acceptance_v1` and
`mot_3d_ui_acceptance_v1`. Their top-level `acceptance` record must exactly equal
`load_acceptance_profile().provenance()`, including the physical and numerical
policy hashes. Scientific kinds retain their existing policy: the explicit
`policy_for_manifest` helper returns `None` for them, and rejects mixed identity.
No environment variable or global override changes scientific defaults.

The first profile retains the full 35-ensemble 2D role partition, 20-ensemble 3D
handoff, both 3D families, 12/16/16/3 selection cardinalities, three optimization
workers, three recoil seeds, and the original bootstrap draw counts. It reduces
sampled particles (2D: two; 3D: one), 2D screen trials to one per worker and
refinement checkpoints to 1/2/3/4, and 3D discovery to four trials per worker.
Physics, simulation endpoints, classification, and control neighborhoods remain
canonical. Smoke uses one CPU/pool and 4 GiB. The 2D production stage uses
24 CPUs/pools and 16 GiB; other 2D stages use ten CPUs/pools and 8 GiB. Fresh
2D input-generation jobs use ten CPUs/pools and 8 GiB. 3D finalist selection and final validation use 100 CPUs/pools and 64 GiB,
with each family array limited to one running task (at most 200 CPUs across
both families). Other 3D stages retain four CPUs/pools and 4 GiB; merges retain
one CPU and 4 GiB. Every job keeps its
one-hour cap and explicit `gd002` placement.
The 32-initial-particle Zeeman generation budget is a bounded test workload,
not a guarantee of survivors: insufficient survivors must fail validation, and
controlled acceptance input provenance must be explicit.

The retained 3D topology requires 314 physical simulation calls, excluding fresh
Zeeman and 2D input generation and negative/recovery scenarios. Runtime must be
measured before making a compute-budget claim. Timestep convergence is not
established by these tests; narrow confidence intervals are not a completion
requirement for the acceptance workflow.

Only dedicated descendants of `data/acceptance`,
`data/optimization/mot_2d/ui_acceptance`,
`data/optimization/mot_3d/ui_acceptance`, and the equivalent
`data/particle_states/after_zeeman/ui_acceptance` and
`data/particle_states/after_mot_2d/ui_acceptance` roots are permitted. The helper
resolves symlinks before containment checks. Use an isolated checkout and Zeus
target as well. Every artifact and handoff must carry acceptance identity;
`assert_scientific_source` rejects nested acceptance provenance at promotion
boundaries. UI and reports must show **TEST ONLY** and must never describe these
outputs as scientific winners or validated efficiency.


### Physical initial input setup

Initial inputs use a separate `zeeman_ui_acceptance_input_generation_v1` plan
under `data/acceptance`; this is not a fabricated campaign or stage result.
Create the plan only after committing the reviewed code, then invoke the normal
Zeeman generator with `--acceptance-profile ui_acceptance_v1` and
`--input-generation-plan <plan>`. The plan freezes all 35 seeds, current clean
commit and physical code hashes, exact profile, destination, and resource policy.
The generator authenticates either this plan or an actual campaign manifest,
never both. Resumption verifies the full NPY array, metadata and completion
receipt; partial or changed outputs fail rather than being silently reused.

The positive input recipe uses 32 independent near-axis initial states per seed,
starting 0.5 mm upstream of the ordinary Zeeman cutoff, with bounded position
and velocity jitter and 42 ± 0.2 m/s inward speed. These are controlled initial
conditions rather than a thermal sample. The ordinary physical Zeeman solver
propagates every atom; all forces, zones, timesteps, horizons, and survivor
classification stay unchanged. Metadata records the exact recipe, initial-state
SHA-256, and permanent `acceptance_only` provenance. Fresh final-validation
seeds 3035–3054 use the same recipe with independent seeded jitter.

A local four-atom viability probe passed 4/4 through the actual Zeeman solver
and 1/4 through the actual 2D solver using its default fine timestep and horizon.
Three losses occurred at the physical differential-pumping aperture. This
measures viability, not seed coverage or an efficiency estimate. All required
initial ensembles and subsequent sealed inputs must pass their ordinary
physical validation. No stage result or survivor may be filled in to make a
failed ensemble pass. Full physical input generation and campaign runtime must
be measured on Zeus before claiming successful lifecycle acceptance.

### Campaign publication on Zeus filesystems

The shared transfer receiver first attempts an atomic no-replace directory
rename. Some Zeus filesystems reject that operation. For known unsupported
capability errors only, the receiver exclusively reserves a new directory,
copies verified files into exclusively created destinations without replacement,
and copies `campaign.json` last. This fallback does not promise atomic manifest
visibility: interrupted copies can remain visible, and consumers reject them.
Readiness and submission require the complete exact manifest, job and input
hashes; success is returned only after those bytes and directories are synced.
The implementation is shared by ordinary and acceptance campaigns; no physical
validation is relaxed.

An interrupted reservation remains blocked and must be reconciled explicitly.
The receiver retains its private `.zeus-campaign-*` staging directory
and all its original files after using this fallback, including on success,
to avoid pathname cleanup races. Published copies have separate inodes and a
single hardlink, preserving the strict readers’ file checks.
These directories are not campaign records and must not be submitted or used
as inputs. Preserve them as evidence until the acceptance report is complete;
never delete a directory just because its name resembles a test artifact.


### Measured compute-only resource revision

The successful real two-particle smoke job `4808390` used 389 wall seconds
and 371 CPU seconds at the frozen working timestep of 1.25 µs. Each Production
array task processes **one** sealed ensemble, containing at most 32 actual input
atoms, at the frozen 0.625 µs final timestep. The 20 ensembles are 20 separate
array tasks, rather than one combined 640-atom task. Production reserves 24
CPUs/pools and 16 GiB per task. The existing four-task array throttle permits
96 CPUs and 64 GiB per campaign, or 192 CPUs and 128 GiB for two operating
systems running this stage together. The solver distributes individual atom
trajectories through `Pool.imap` with its default chunk size of one; 32 atoms
need at most two trajectory waves across 24 workers. A 6–10 minute per-task
estimate is provisional; the one-hour limit and ordinary validation remain
binding. Ten-worker stages reserve 8 GiB for worker and coordinator overhead.

This revision changes compute resources only. Every force, canonical physical-policy hash,
timestep, horizon, role seed, ensemble population, particle budget, candidate
count, trial count, and validation criterion remains identical. The full
non-resource policy SHA-256 is
`700293772dc54b4419d6776873b4c44326d720585a61fc256e4a527a76a17746`.
The new content identity is
`f4f666548ada90aab2938878822dfe5173a140496cadbd7baba68144ad873148`.
The profile/content and code-closure hashes change to record this operational
revision; the canonical laboratory and numerical identities do not change.
Earlier evidence remains tied to its original profile hash. New campaigns
require newly generated, honestly marked inputs under the new hash; old
metadata must not be relabeled or edited to match it.

The 3D all-available workload includes up to 640 actual particles. Finalist
selection evaluates all three recoil seeds sequentially per task; the measured
117-second search trajectory estimates about 38 minutes per task with 100 pools.
Final validation uses one recoil seed per task at the finer unchanged timestep,
about 25 minutes at the same upper bound. These estimates do not guarantee
completion; the one-hour limit and ordinary validation still apply. Family
arrays retain all three tasks and run one task at a time.

### Actual task units and concurrency

These are allocation bounds for one campaign with one fixed 2D `s0` value.
Repeated trials and recoil seeds run sequentially inside their task. Every
physical solver receives the original frozen timestep and endpoint.

| Stage | One array task | Tasks and concurrency | CPUs per task / maximum per campaign |
| --- | --- | --- | --- |
| 2D smoke | One trial, one ensemble, two atoms | One task | 1 / 1 |
| 2D screen | One trial, five ensembles × two atoms, flattened | Three workers, throttle 3 | 10 / 30 |
| 2D refinement | Up to four cumulative trials, each five × two atoms | Three workers per checkpoint, throttle 3 | 10 / 30 |
| 2D confirmation | One candidate, five × two atoms | Five tasks, throttle 3 | 10 / 30 |
| 2D sensitivity | One control point, five × two atoms | Up to 17 tasks per s₀, throttle 3 | 10 / 30 |
| 2D production | One sealed ensemble, at most 32 atoms | 20 tasks, throttle 4 | 24 / 96 |
| 3D discovery | One worker, four cumulative trials of 12 atoms | Three workers per family; dependent rounds | 4 / 24 across two families |
| 3D preliminary | Up to four candidates × three recoil seeds; four atoms per call | Three workers per family | 4 / 24 across two families |
| 3D refinement / closure | Up to six candidates × three recoil seeds; four atoms per call | Three workers per family | 4 / 24 across two families |
| 3D finalist selection | One candidate, up to 640 flattened atoms, three recoil calls | Three tasks per family, throttle 1 per family | 100 / 200 across two families |
| Fresh Zeeman generation | One seed, 32 initial atoms | 20 tasks, no array throttle | 1 / 20 |
| Fresh 2D generation | One seed, at most 32 atoms | 20 tasks, no array throttle | 10 / 200 |
| Fresh input freeze | Validate and seal the 20 ensembles | One scalar job | 1 / 1 |
| 3D final validation | One recoil seed, up to 640 flattened atoms | Three tasks per family, throttle 1 per family | 100 / 200 across two families |

Selection merges reserve one CPU and 4 GiB per family. The acceptance run
schedule serializes **entire 3D campaigns** between operating systems, including
fresh input generation, to keep the combined physical-worker allocation within
200 CPUs. This is an operator scheduling requirement; the scheduler does not
provide a cross-campaign global cap. Independent unrelated jobs are outside
these per-campaign bounds.

The 2D sensitivity candidate count 17 is the maximum canonical neighborhood,
not a promise of 17 distinct tasks. The existing scientific generator clamps
points to the frozen search bounds and removes duplicates; a boundary winner
can therefore produce fewer tasks (observed 16). Submission review, scheduler
accounting and output validation must use the exact rendered/frozen task
registry. This does not change the profile, search bounds or neighborhood
policy.

Checkpointed 2D optimization restores the original seeded TPE stream through
verified public Optuna trial replay. Checkpoints must produce exactly the same
parameter sequence as an uninterrupted run, including after TPE startup and
for queued points. Replay does not evaluate trajectories or rewrite historical
trials. Incompatible legacy or incomplete histories stop with an explicit
error; preserve their databases and inspect them using their pinned version.
The profile, seeds and trial budgets are unchanged.

Campaign workers pass frozen magnet radii through `--magnet-radius-m` to
preserve their exact SI value. The manual `--magnet-radius-mm` interface remains
available with its previous conversion behavior; the two options are mutually
exclusive. This avoids changing a frozen value during an m→mm→m round trip.

### Local worker publication and interruption checks

Creating another run while a local simulation is computing must not invalidate
its output. At the worker/publication boundary, the coordinator reattests the
original canonical directory identities, strict run-directory freshness and all
four original records before obtaining a fresh strict publication lease.
Publication and recovery still reject replacement, symlinks and directory
changes during their own guarded operations. A completely restored ancestor
rename during computation is not detected retrospectively; inputs have already
been hash-checked and copied into owned memory, and output is published only
through the reattested canonical directory handles.

An unexpected background failure clears live progress, retains a bounded
process-local diagnostic and blocks repeating that submission. Durable outputs
are never described as verified until publication succeeds. After a restart,
a saved running record with no live telemetry is shown as requiring inspection,
not as proof of an active worker. The UI does not offer local resume or retry
for this uncertain outcome. Inspect the original record and any saved artifacts;
explicit maintainer reconciliation must not rerun the physical calculation.

While the backend remains running, an accepted local run waiting for a worker
exposes a process-owned scheduling observation. Refreshing its page restores
monitoring and keeps polling the same run; it must not offer another Start.
This observation is cleared on completion, cancellation or enqueue failure.
It is not a durable queue state and does not imply that a worker survived a
backend restart. Progress bars require actual worker telemetry.
