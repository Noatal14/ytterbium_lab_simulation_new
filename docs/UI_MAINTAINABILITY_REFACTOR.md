# UI maintainability refactor

## Decision record

- Baseline: `4807b7c3f78ba082239983b4cfb8a0beddbce6fd`
- Scope: the local UI, its `workflow_api` backend, and their tests and CI.
- Goal: make stage development safer and easier without changing scientific
  behavior, Zeus behavior, or existing public API contracts by accident.
- Phase 0 changes documentation only. No production behavior is changed.

## Verified findings

The audit was rechecked against the baseline commit. The main findings are:

1. CI runs the Python suite but does not exercise the frontend unit tests,
   TypeScript build, browser tests, or accessibility checks.
2. `CampaignExplorer.tsx` owns too many independent stage lifecycles and
   repeated async states in one component.
3. `ui/src/api/campaigns.ts` combines HTTP, schemas, parsers, DTOs, session
   state, and every campaign operation.
4. Scientific and scheduler facts are repeated across Python, TypeScript,
   tests, and UI copy. Strict client validation remains valuable, but the facts
   it validates should come from versioned contracts or API responses.
5. Campaign creation does not invalidate and reload the campaign list.
6. `App.tsx` shares one error state between list and detail operations.
7. `workflow_api/server.py` uses a large manual dispatcher, and the
   `ReadOnlyWorkflowHandler` name no longer describes its guarded mutations.
8. Zeus coordinators repeat preview-token, session, SSH, receipt, and locking
   machinery and also depend on private methods of other coordinators.
9. Self-contained remote receivers repeat dense security helpers. This is a
   real maintenance risk, but ordinary local imports cannot be assumed on the
   remote host.
10. Python and TypeScript contracts are maintained separately; mocked browser
    tests do not prove compatibility with the real backend.
11. The current UI suite covers several important failures, including expiry,
    ambiguity, holds, failed work, and reload recovery. Remaining gaps include
    navigation during requests, repeated clicks, multiple tabs or campaigns,
    backend disappearance, and smaller stage-specific component matrices.
12. There is no coverage reporting or focused threshold for sensitive parsers
    and lifecycle code.
13. Frontend preview/session contexts are module-global and cannot safely model
    concurrent campaign flows or multiple tabs.
14. `api_version`, stages, statuses, and public error codes are not enforced
    from one versioned contract and error catalog.
15. Python formatting, linting, complexity checks, and public DTO typing are
    not yet applied consistently.

The audit's remaining observations were also confirmed: `home.ts` is product
content rather than a test fixture, the long browser happy path should remain
as one smoke test but gain smaller stage tests, and directory organization can
improve after responsibilities have first been separated safely.

## Invariants

Every phase must preserve these rules unless a separately approved change says
otherwise:

- No scientific model, solver, timestep, seed role, ensemble role, selection
  rule, particle budget, optimization bound, or confidence calculation changes.
- Campaign manifests, generated PBS files, remote receiver scripts, and result
  selection remain byte-identical unless the phase explicitly owns that output
  and proves canonical equivalence.
- Existing HTTP routes, response fields, stable error codes, status semantics,
  and preview/confirmation behavior remain compatible. An intentional contract
  change requires an API-version change and coordinated client migration.
- Strict validation, exact-key checks, path and symlink defenses, bounded reads,
  pinned SSH identity, explicit allowlists, durable receipts, idempotency, and
  fail-closed ambiguous outcomes are not weakened.
- No generic remote-command or scheduler-command interface is introduced.
- No phase contacts Zeus, submits work, changes a running campaign, or mirrors
  files to or from Zeus as part of development or tests.
- Existing campaigns remain inspectable and resumable.
- File moves use compatibility imports where an external or generated reference
  may still depend on the old path.

## Phased order

### P1 — Frontend CI

Add an isolated frontend CI job for frozen dependency installation, unit and
launcher tests, TypeScript/production build, and a Chromium browser/accessibility
smoke. Wider browser and viewport coverage may run separately if CI time is high.

### P2 — App state correctness

Reload the campaign list after creation and separate list, detail, and mutation
errors. Add regressions for successful refresh, failed detail loading, retry,
and navigation that clears only the relevant error.

### P3 — Versioned contracts and real integration

Centralize HTTP envelope parsing and enforce `api_version` before payload
parsing. Add backend-generated contract fixtures and a thin integration test
that runs the real local server with fake Zeus transports. Do not move API
modules in the same change. Roll version enforcement out compatibly: successful
responses already carry the versioned envelope, while several current error
responses are intentionally unversioned. Snapshot both families first; do not
silently reject or reshape existing errors while centralizing success parsing.

### P4 — Frontend API modules and scoped clients

Split HTTP, errors, common schemas, campaign endpoints, and Zeus stage endpoints.
Replace module-global preview/session contexts with per-client or per-flow state.
Preserve exact wire contracts and parser strictness.

### P5 — Stage-focused UI

Split campaign detail by stage and introduce small shared review, status, facts,
and error components plus a tested lifecycle reducer or hook. Preserve wording,
DOM accessibility, focus behavior, responsive behavior, and visible effects.

### P6 — Public backend services

Replace cross-module calls to private methods and `object()` placeholder
construction with narrow public services for repository revisions, artifact
planning, and stage evidence. The verified seams are four external uses of
`_campaign_files`, the refinement flow's use of `_revision`, the
refinement-submission flow's use of refinement `_inspect`, and the confirmation
flow's use of refinement-submission `_plan`. Introduce frozen public plan and
evidence DTOs plus compatibility wrappers before removing any private entry
point. Preserve output bytes, validation order, exception behavior, and call
sites that may still use the old wrapper during migration.

### P7 — Declarative HTTP routing

Rename or alias the misleading handler, then introduce a typed route registry in
a separate step. Preserve exact methods, routes, service requirements, HTTP
statuses, CSRF rules, payload limits, and error responses. Contract snapshots
must include the current, sometimes unusual behavior: POST CSRF handling,
method/route `405` behavior, the exact service-unavailable error family, session
method call style, typed exception translation, and the present `201` success
status for routes whose path ends in `/confirm`. Add a stable error catalog only
after this route equivalence is proven.

### P8 — Central capability and lifecycle specifications

Move stages, statuses, public errors, and displayable scheduler/scientific facts
to versioned specifications or backend responses. Generate or validate the
Python and TypeScript views from the same source without weakening runtime
validation.

### P9 — Shared Zeus infrastructure

Extract preview stores, pinned SSH transport, response protocol, and receipt
helpers one coordinator at a time. Each migration requires adversarial replay,
concurrency, timeout, and ambiguity tests plus behavior equivalence.
Every remote invocation must still select a fixed audited receiver and a closed
operation enum, validate an operation-specific exact request and response
schema, and retain explicit allowlists. No abstraction may accept a caller-
provided executable, shell fragment, generic command, or arbitrary receiver.

## Deferred work

The following are deliberately deferred until P1–P9 establish stable contracts
and smaller modules:

- A broad directory move or repository-wide architecture rewrite.
- Deduplicating remote receivers through normal imports. Any future solution
  must still emit a self-contained, auditable, allowlisted remote program and
  prove byte or behavioral equivalence.
- Repository-wide auto-formatting of dense security-sensitive remote scripts.
- A wholesale migration to Pydantic or another DTO framework.
- A generic SSH command runner or generic scheduler abstraction.
- Coverage targets chosen only to raise a global percentage.

Ruff may be introduced earlier in check-only mode for touched, non-remote files.
Formatting, typing, and complexity enforcement should expand gradually with no
large mechanical rewrite mixed into behavioral changes.

## Acceptance gates

Every phase requires independent review and, as applicable:

- `git diff --check` and validation of changed CI/configuration files.
- The complete Python suite, with any stochastic retry reported explicitly.
- Frontend unit and launcher tests.
- TypeScript checks and a production build.
- Chromium browser and accessibility tests; full responsive/browser coverage
  before changes that affect layout or interaction are merged.
- Focused security suites for any backend, transport, receipt, route, or remote
  receiver change.
- Contract snapshots or byte-equivalence tests for generated artifacts.
- A clean worktree assessment that distinguishes the phase from unrelated user
  data or active campaign outputs.

No phase is committed until its implementation owner and an independent reviewer
agree that these gates pass. Each phase is committed separately so regressions
can be attributed and reverted without mixing concerns.

## Decision log

| Decision | Rationale |
| --- | --- |
| Start with CI and two concrete App bugs. | Highest confidence gain and user-visible correctness for low risk. |
| Establish versioned contracts before moving API code. | File moves are safer once backend/client drift is detectable. |
| Separate API modularization from UI component decomposition. | Keeps failures attributable to data flow or rendering, not both. |
| Replace private backend coupling before shared coordinator bases. | Creates explicit seams without prematurely generalizing security code. |
| Move remote-helper deduplication to the end. | Remote receivers are standalone security boundaries and require stronger equivalence evidence. |
| Keep strict frontend validation. | Defense in depth is intentional; single source of truth does not mean trusting unvalidated responses. |
| Avoid a mega-refactor. | Small reviewed commits protect active campaigns and scientific reproducibility. |
