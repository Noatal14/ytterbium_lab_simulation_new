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
