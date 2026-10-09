# UI maintainability refactor

## Decision record

- Baseline: `4807b7c3f78ba082239983b4cfb8a0beddbce6fd`
- Scope: the local UI, its `workflow_api` backend, and their tests and CI.
- Goal: make stage development safer and easier without changing scientific
  behavior, Zeus behavior, or existing public API contracts by accident.
- Status: completed through P9. The implementation was delivered as small,
  independently reviewed commits; this file is the final closure record.
- Phase 0 (`92c9d5c`) changed documentation only. No scientific campaign or Zeus
  operation was run by any refactor phase.

## Verified findings

The audit was rechecked against the baseline commit. The findings below describe
that baseline, not the current tree. Their resolution is recorded in the phase
outcome table.

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

## Phase outcomes

| Phase | Commits | Verified outcome |
| --- | --- | --- |
| P1 — Frontend CI | `790a197` | Added frozen frontend install, unit/launcher, production build, and Chromium viewport/accessibility jobs while preserving the Python job. |
| P2 — App state correctness | `0d153e4` | Separated list/detail failures, refreshed after creation, and protected navigation and overlapping requests from stale results. |
| P3 — Versioned contracts | `2f70108` | Enforced strict v1 success envelopes, preserved intentionally unversioned v1 errors, and added backend-generated success/error contract snapshots consumed by frontend tests. |
| P4 — Scoped API clients | `3c40e2f` | Split HTTP, schema, campaign, and stage clients; moved CSRF acquisition and review contexts into isolated application-client instances. The browser-scoped HTTP-only session cookie remains shared by same-origin tabs. |
| P5 — Stage-focused UI | `2003486` | Split campaign detail into stage features and shared accessible status/review/error components without a visual or scientific redesign. |
| P6 — Public backend services | `09ee67c`, `a2dab3c`, `821bff0`, `3ea69bf` | Added public artifact-planning, repository-revision, refinement-inspection, and chain-plan seams and removed the audited cross-coordinator private coupling. |
| P7 — Declarative routing | `e2da84c` | Replaced manual dispatch with a typed route registry while preserving exact routes, methods, CSRF, statuses, headers, and error behavior. |
| P8 — Versioned specifications and errors | `f1efe0c`, `7b3141a`, `dab6411`–`26de5ff` | Added the shared 2D-MOT specification, deterministic TypeScript view, exhaustive domain-qualified backend error catalog, catalog-backed handlers, and message-free frontend error semantics. Unknown or wrong-domain confirmation failures remain fail-closed. |
| P9 — Shared infrastructure | `dc20d50`–`d0d37db`, `237d0c0`–`2269f4a`, `fd1b758` | Migrated Zeus coordinators and CreationService to the shared local preview registry, and every local pinned transport to a closed receiver/operation runner, one workflow at a time, with policy-equivalence and adversarial tests. Workflow-specific pending DTOs, locks, expiry/capacity rules, receivers, receipts, response validation, and ambiguity policies remain independent. |

Every phase received independent review. Applicable gates included the complete
Python suite, frontend unit and launcher tests, TypeScript production build,
Chromium responsive/accessibility tests, focused security and ambiguity suites,
contract or byte-equivalence checks, and `git diff --check`. No phase contacted
Zeus or changed a scientific model, campaign manifest, generated PBS contract,
or active campaign.

## Deferred work

The following remain deliberately deferred:

- A broad directory move or repository-wide architecture rewrite.
- Deduplicating remote receivers through normal imports. Any future solution
  must still emit a self-contained, auditable, allowlisted remote program and
  prove byte or behavioral equivalence.
- Repository-wide auto-formatting of dense security-sensitive remote scripts.
- A wholesale migration to Pydantic or another DTO framework.
- A generic SSH command runner or generic scheduler abstraction.
- Coverage targets chosen only to raise a global percentage.
- Unifying workflow-specific pending DTOs, confirmation locks, expiry/capacity
  rules, or error policies. Those differences remain explicit by design.
- Unifying pinned transport response parsing or hardening the legacy transport
  policies. P9 preserved each audited argv, environment, timeout, output, and
  ambiguity policy exactly; any convergence is a separate behavior change.
- Replacing protocol- or security-specific module constants merely to reduce
  their count.

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
| Version successful v1 envelopes but preserve unversioned v1 errors. | This closes success-schema drift without silently breaking the established error contract. |
| Generate frontend error semantics without server messages. | The server remains the message authority; the UI consumes only domain-qualified safe-interaction metadata. |
| Treat unknown or wrong-domain confirmation failures as manual verification. | A client must never turn an unfamiliar mutation outcome into a retry path. |
| Keep application clients instance-scoped. | CSRF acquisition and review-token contexts do not leak between client instances or tests. The browser-scoped HTTP-only session cookie remains intentionally shared by same-origin tabs. |
| Share only closed local Zeus infrastructure. | Preview storage and SSH execution are reusable, but callers still cannot select a command, receiver, host, or operation outside fixed enums. |
| Keep remote receivers self-contained. | Zeus cannot be assumed to have importable local packages, and each transmitted program remains independently auditable. |
