# Fast campaign-flow testing

Do not run full scientific optimization campaigns to test application wiring.
Use three complementary layers:

| Layer | What runs | What it verifies | Expected scale |
| --- | --- | --- | --- |
| Browser/API contracts | Existing deterministic fixtures, all stage actions and failure states | Review/confirm, progress, resume, artifact validation, completion and duplicate prevention | Minutes |
| Real local backend | Existing Playwright real-backend integration with disposable fixture sources | Browser-to-API contracts, actual files, reviewed resource display and recovery | Minutes |
| Real scheduler acceptance | A separate, versioned miniature campaign profile, not yet implemented for the full lifecycle | Real submission, dependencies, state transfer, physical worker execution and merge | Target tens of compute minutes, plus queue time |

The existing browser suite already traverses the 3D stage controls using
mocked scheduler/results contracts. Those tests are useful but do not prove
that a complete physical campaign will finish on Zeus. The existing 2D smoke
stage is also not a miniature end-to-end campaign.

## Proposed miniature profile

Implement this as a reviewed **acceptance profile of the same workflow**, not
a copied backend or scripts that bypass the normal validation. Start with a
handful of particles per ensemble and one or two candidate configurations;
reduce recoil repetitions and bootstrap draws only where the versioned test
profile and its validators explicitly permit it. Preserve the required stage
topology and ensemble-role structure. Include controlled test inputs that can
produce survivors so downstream success paths can be exercised; separately
test zero-survivor and failed-job paths.

Use separate campaign kinds/provenance, a conspicuous TEST ONLY banner and
dedicated directories/checkouts. Never admit an acceptance output as a
scientific source, winner or validated efficiency. Test mode must fail closed
on production paths. The present `dev:zeus-test` mode supports individual runs
only; it must not be represented as full campaign acceptance support.

Run success plus held/failed jobs, interrupted checkpoint/resume, corrupt or
missing results, refresh/reconnection and double-confirmation cases. Keep
scientific campaigns and their budgets immutable. Test both 2D and 3D flows.

## Current regression commands

- Python: `python -m pytest -q`.
- UI unit/contracts: `npm test` in `ui`.
- Browser fixtures: `npm run test:e2e` in `ui`.
- Local real-backend integration: `node node_modules/@playwright/test/cli.js test --config=playwright.real-backend.config.ts` in `ui`, with the documented Python environment available.

Browser emulation is not Windows OS acceptance. Repeat the miniature real
workflow on actual Windows and Mac environments, using isolated Zeus targets.
No acceptance campaign was submitted as part of the 50-ms / 5-us policy update.

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
canonical. The smoke stage uses one CPU/pool; other 2D stages use ten and 3D
stages use four. Merge jobs use one CPU. Each job requests 4 GiB and one hour;
the acceptance scheduler placement is explicitly pinned to `gd002`.
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
