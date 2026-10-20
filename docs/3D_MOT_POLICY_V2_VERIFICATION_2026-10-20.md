# 3D MOT policy v2 verification — 2026-10-20

New campaigns use a 50 ms endpoint, 10 us search steps and 5 us sealed
final-validation steps. Historical v1 policy files and campaign results are
preserved. Individual 3D runs retain their separate 10 us / 100 ms protocol;
2D and Zeeman numerical settings are unchanged.

## Verification

- Complete Python suite: **2319 passed, 7 skipped**, 699.45 seconds.
  Ten warnings originate from deliberately malformed ZIP fixtures and existing
  vendored simulator tests.
- UI unit/contract tests: **731 passed**.
- Node development lifecycle tests: **6 passed**.
- Playwright fixture browser tests: **120 passed**.
- Playwright real Python-backend integration tests: **5 passed**.
- ESLint, application/node TypeScript checks and production Vite build passed.
  The existing large-bundle advisory remains non-blocking.
- Generated catalog checks, configured Prettier checks and staged diff
  whitespace checks passed.
- An independent subagent reviewed the policy propagation, archive bounds,
  compatibility and regression tests; no blocking findings remained. Its
  independent targeted run passed **42 tests**.

Regression coverage includes all campaign-stage endpoint defaults and rendered
PBS arguments, rejection of mixed legacy protocols, unchanged 2D physics, and
merging the retained 16,675-atom final-validation outcomes without rerunning
atoms. A scoped archive-size correction permits those final-validation arrays
while preserving the stricter preliminary-stage default bound.

Previously configured but unstarted runs may require a fresh configuration
after upgrading. Historical completed results remain readable through frozen
records. In-flight remote jobs must retain their pinned checkout, as before.

No scientific Zeus jobs or full miniature acceptance campaign were submitted.
Actual Windows OS acceptance was not performed by these browser tests.
The proposed fast full-flow acceptance profile is described in
`UI_FAST_CAMPAIGN_TESTING.md`; implementation remains separate work.
