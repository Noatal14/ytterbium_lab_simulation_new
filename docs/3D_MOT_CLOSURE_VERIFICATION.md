# Scientific closure verification — 2026-10-20

Scope: the closure commit accompanying this record, based on `62fc101` on
`codex/ui-review-fixes`. Existing unrelated graph/animation edits were not
included. Host: macOS, Python 3.12.10, Node 24.19.0.

## Review and automated gates

- Independent read-only subagent review: no blocking findings. Reviewed the
  staged source fix, scientific closure, provenance archives and evidence tests.
- Full Python suite: **2,278 passed, 7 skipped**, 10 warnings; 694.25 seconds.
  Command: `python3 -m pytest -q`, with `MPLBACKEND=Agg`, writable
  `MPLCONFIGDIR`, and BLAS/OMP thread counts set to 1. Warnings include
  intentional malformed-archive fixtures and existing vendored-library tests.
- Final evidence/reference tests rerun after backup hardening: **9 passed**.
  They validate artifact hashes, every receipt-listed runtime source, all six
  canonical outputs against checkpoints, and sealed input arrays against both
  the input manifest and checkpoint fingerprints.
- UI unit/component suite: **708 passed** across 47 files.
- Node startup/shutdown tests: **3 passed**.
- Playwright browser suite: **120 passed** across desktop, split-screen,
  tablet, mobile and WebKit projects (42 seconds).
- ESLint, configured Prettier check, TypeScript checks and Vite build: passed.
  Vite retains its non-blocking warning for a bundle larger than 500 kB.
- Workflow/UI error-catalog checks and `git diff --cached --check`: passed.

The bundled Node executable ran the repository's CLI entry points directly
because `npm` was absent from this shell. No package versions were changed.
An initial sandboxed Python/browser attempt could not bind localhost; it was
not treated as a pass. The complete successful reruns allowed local servers.

## Boundaries

No final atom was reintegrated during closure. No forces, physical parameters,
locked winners, RNG seeds or original hashed campaign manifests were changed.
The only retained executable change fixes exact production basenames relative
to their declared input directory; existing strict path/hash checks remain.
Temporary runtime/comparison tools were removed from active source and retained
in the exact execution audit archive for reproducibility.

These automated browser tests do not establish real Windows/Zeus end-to-end
acceptance, and this task did not recertify the separate UI chat's work. The
scientific campaign is closed; software delivery remains subject to the
[release checklist](UI_RELEASE_ACCEPTANCE_CHECKLIST.md). Do not check off
unperformed manual tests or imply this commit is a tested `main` release.
