# Reliability audit — 2026-10-13

Verified at branch `codex/ui-review-fixes`. This document records engineering
decisions; it does not change scientific parameters.

## Why this audit exists

The active 3D-MOT Discovery campaign failed when an Optuna design containing
Python tuples was compared with the same design after JSON persistence had
converted those tuples to lists. A first recovery then failed because it ran
new code against a campaign whose commit and physical-model digest were
intentionally frozen. Both failures exposed missing lifecycle tests rather than
a Zeus or physics failure.

The active campaign is:

`data/optimization/mot_3d/mot_3d_s0_1p3_search10us_20261012_v1`

Recovery must preserve its original commit, physical-model digest, input
registry, Optuna databases, and completed trials. It must never be redirected
to the older `mot_3d_s0_1p3_20261010_v1` campaign.

The approved isolated recovery submissions are `4791526[]` for the remaining
angled-donut Discovery work and `4791527[]` followed by dependent `4791529[]`
for the remaining single-pass work. These identifiers are operational evidence,
not a replacement for the campaign manifest or durable submission receipts.

## Release blockers found

1. Campaign compatibility and resume
   - Historical campaign JSON did not pass through one versioned decoder.
   - Resume was coupled to the current repository HEAD without a supported
     immutable historical runner.
   - Provenance closures are duplicated and mix physics, orchestration, and
     transport concerns.
   - Mutable workflow state and immutable scientific design share one
     unversioned manifest.
2. Remaining 3D lifecycle
   - Later submission receipts and transitions are less crash-recoverable than
     Discovery, Preliminary Check, and Refinement.
   - Finalist and final-validation artifacts needed stricter archive, schema,
     numeric, and provenance validation.
   - The UI currently stops after preparing Closure; it cannot yet complete the
     canonical 3D workflow.
3. UI reliability
   - Individual runs cannot yet be reopened after navigation or reload.
   - Several request flows lacked complete stale-response, retry, or
     double-action protection.
   - Source catalog truncation/invalid-entry information is not visible.
4. Test coverage
   - Unit coverage was broad, but there was no golden test for resuming a
     campaign created by an older compatible checkout.
   - There was no complete persisted-stage matrix from 3D Discovery through a
     sealed final report.
   - Browser coverage did not include reload/resume, ambiguous remote outcomes,
     or the late 3D stages.

## Required gates before unattended use

- Every public campaign command reads manifests through one bounded,
  version-dispatched codec.
- Existing version identifiers remain immutable; new shapes receive new
  versions and explicit decoders.
- A campaign can be inspected from a newer checkout and resumed only through a
  verified compatible runner or its immutable frozen runner.
- Every state-changing remote action has preview, explicit confirmation,
  durable intent, exact receipt validation, idempotent recovery, and an
  ambiguous-outcome state that never retries automatically.
- Every transition renders a closed artifact registry, publishes without
  overwrite, and commits the manifest/state last.
- Final scientific claims are recomputed from sealed artifacts rather than
  trusted from editable summaries.
- Individual and campaign runs can be reopened after reload using persisted
  identity, not component-local memory.
- The complete Python suite, UI unit suite, typecheck, lint, production build,
  accessibility checks, and browser lifecycle matrix pass.

## Remediation order

1. Stabilize and monitor the active 3D Discovery recovery.
2. Freeze V1 fixtures and centralize campaign decoding without rewriting old
   manifests.
3. Harden late-stage 3D archives, receipts, transitions, and final reports.
4. Replace late-stage one-shot submission records with the durable submission
   engine used by the hardened stages.
5. Implement Closure through final-report UI/API lifecycle.
6. Add persistent run recovery and the full browser state matrix.
7. Split provenance into versioned component digests and introduce explicit,
   source-preserving migrations for future schema changes.

No UI or campaign workflow is considered ready for unattended laboratory use
until all applicable gates above are demonstrated by tests and an end-to-end
dry run.
