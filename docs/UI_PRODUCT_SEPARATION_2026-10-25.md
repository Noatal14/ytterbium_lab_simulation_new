# Product separation candidate — 2026-10-25

This focused candidate is based on `05c508b7087653139a737b39eec4218665c805d9`
on `codex/ui-product-separation-20261025`. It preserves the preceding product
fixes and their regressions. It does not change main, submit jobs, update remote
runtime checkouts, or modify scientific inputs/results. No push is authorized.

## Maintained code and historical evidence

- Keep the shared workflow and the explicit, isolated TEST ONLY v1 profile.
  Scientific settings, population separation and admission checks are unchanged.
- Retire executable v2: remove its pinned O16 cross-profile authorization and
  Single-pass candidate permutation, including their special stage validators.
  V1 and scientific discovery now use the same canonical selector.
- Preserve the original v2 policy and its original test sources byte-for-byte in
  `tests/fixtures/historical_acceptance_v2/`. They describe historical runs,
  not features enabled by the current backend. Old results require their recorded
  producer revision; do not migrate or rewrite their receipts to this candidate.
- Preserve all `acceptance-evidence/` files in Git. Exclude that operator evidence
  directory from distributable Git source archives using `export-ignore`.
- Move the unchanged replay sampler into `utils/optuna_replay.py`; 2D and 3D
  retain their existing domain-specific history validation and restoration.
  Include the shared module in executable provenance closures.

## Unresolved refinement limitation — release decision required

Canonical Single-pass selection can choose a legal boundary parameter. A clipped
refinement perturbation can then duplicate a point. The existing
`DuplicateRefinementPointError` / `refinement_design_duplicate` rejection remains
in force, before publication. No refinement algorithm, clipping policy, ranking,
physical bounds or numerical policy was changed by this cleanup.

The historical v2 permutation exercised an interior point; its successful runs
DO NOT establish that the canonical boundary path works. This candidate cannot
justify unrestricted autonomous campaign use by the team. Resolving or explicitly
restricting that path requires a separate decision and qualification.

## Candidate qualification

Run the regression suites against the final committed candidate, not merely the
old acceptance checkout. Record the exact Git commit, commands, operating system,
results and independent review outcomes in the review handoff. Hermetic receiver
checks do not count as new real Zeus runs. No new remote campaign is needed to
claim source separation; prior lifecycle evidence remains historical evidence.
Windows ARM is distinct from untested Windows Intel/AMD.

This document is not publication approval. Hand off the exact candidate for
independent review before merge or publication.
