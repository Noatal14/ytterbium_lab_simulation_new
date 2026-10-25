# Backend installation and native UI verification — 25 October 2026

**PASS for the requested isolated-environment installation and UI checks on Mac and actual Windows ARM64/Parallels.** Installed source: `e5eed6616e5a9f36e71c4ff0764b0f1ec14c90a1`. This closes the two backend deployment gaps in the [previous edge-case report](../campaign-edge-cases/REPORT.md). The user explicitly waived a complete physical 2D all-zero-capture campaign; it is no longer a release blocker. [Qualification](qualification.json), [independent review](independent-review.json), [accepted scope](accepted-scope.json).

| Installed-backend check | Mac | Actual Windows ARM64 |
|---|---|---|
| Existing test checkout updated by clean Git fast-forward | PASS | PASS |
| Deliberately empty TEST ONLY input rejected and absent from real UI options | PASS | PASS |
| Fresh campaign, automatic pretransfer inspection without a false UI error | PASS | PASS |
| Real UI transfer, review and exactly one Smoke submission | PASS | PASS |
| Actual Zeus completion and three validated output artifacts | PASS | PASS |
| Full page reload restores correct status automatically; no additional actions/submissions | PASS | PASS |
| Original saved data remains unchanged | 2,334 files | 1,560 files |

Zeus's existing isolated checkout `/home/tal.noa/ytterbium_lab_simulation_ui_acceptance` was updated to the same revision. All **4,976 pre-existing data files** there were preserved. No scientific checkout, closed scientific campaign, scientific input/result or unrelated scheduler job was modified. No new product infrastructure, dependency, source-code fix, service, checkout or test framework was added in this installation task. Existing APIs 8768/8788 were restarted only after their exact process identity was checked; existing UI frontends remain on 5181/5201. Both test APIs now use the normal `ui_acceptance_v1` profile for these 2D checks. Old campaign manifests and receipts retain their original provenance.

## Actual jobs and results

| Client that submitted through its UI | Job ID | Resources | Terminal result |
|---|---|---|---|
| Mac | `4823012.zeus-master` | gd002, 1 CPU, 4 GiB, 1-hour cap | F / Exit 0, 6 min 23 sec |
| Native Windows | `4823042.zeus-master` | Same | F / Exit 0, 6 min 21 sec |

Jobs were submitted **sequentially**, once each despite the controlled double-click gesture. No later campaign stage was prepared or submitted. Both real UIs validated the same result: **three artifacts, s₀=1.3, two input atoms, one captured atom, efficiency 0.5**. Full page reload recovered that same job and validated result without Connect/Inspect/stage clicks. The readonly observers blocked submission/preparation routes. [Final scheduler queue is empty](final-qselect.txt).

- Mac: [creation/transfer/submission checkpoint](mac-installed-smoke/checkpoint.json), [source choices](mac-installed-smoke/source-admission.json), [terminal/reload proof](mac-installed-observed-qualified-label/reopen-result.json), [reload screenshot](mac-installed-observed-qualified-label/reload.png), [scheduler](mac-smoke-terminal.txt).
- Windows: [checkpoint and receipts](windows-installed-submitted-evidence/checkpoint.json), [source choices](windows-installed-submitted-evidence/source-admission.json), [terminal/reload proof](windows-installed-observed-final/reopen-result.json), [reload screenshot](windows-installed-observed-final/reload.png), [scheduler](windows-smoke-scheduler-followup.txt).

## Source admission and preservation

The existing normal input-plan and physical Zeeman generator produced **35 new genuine TEST ONLY ensembles** at the installed revision, using two local single-pool workers and unchanged physical policy. This avoids bypassing duplicate-campaign prevention or changing old input provenance. Normal validation passed. A separately labelled synthetic negative copy contains one deliberately empty array; the installed source validator rejects it specifically for an undefined conditional-efficiency denominator. It is not represented as a physical simulation result.

Both running UI/backend paths returned three valid sources and one rejected source. The empty source is absent from the native browser's selectable options; the genuine new source remains available. Before the first transfer, the new receiver returns the existing typed `smoke_not_submitted` response (HTTP 412), and the existing controller treats it as no recorded job rather than a false UI error. This observation does not authorize submission: ordinary transfer/submission guards still run.

[Normal generation proof](genuine-input-generation/proof-qualified-existing-receipts.json), [Mac installed validator origin](installed-mac-input-qualification.json), [Windows installed validator origin](installed-windows-input-qualification.json). Original-data final checks: [Mac](mac-original-data-final-preserved.json), [Windows](windows-original-data-final-preserved.json), [Zeus](zeus-original-data-final-preserved.json). Full original maps are retained alongside these files.

Preserved audit stops are not product passes: the installer bundle initially remained untracked inside Zeus and correctly blocked Smoke review; only that task-created, hash-verified bundle was removed, preserving its local copy. No guard was weakened. The old finite generation helper's output allowlist omitted the current generator's exact 35 normal receipt files; workers and normal validator had already passed, and the exact new receipt set was independently qualified without regeneration. A readonly observer initially used the wrong capitalization for an existing UI button; its verified terminal response and stop are retained, and the corrected readonly check passed. The strict Windows audit initially rejected known untracked JSON data; final verification invokes the unchanged production revision policy and hash-binds all 72 permitted JSON records. No data or ignore rule was changed to hide them.

## Release recommendation

**A controlled release for the tested Mac and Windows ARM64 environments is supported.** Independent review found no concrete blocker in this combined evidence: the prior complete campaign/edge-case checks plus the new installed-backend real UI checks. A fresh full 2D/3D campaign was not repeated solely for installation; these two Smoke jobs are not claimed as full-campaign qualification.

**Unrestricted support for ordinary Intel/AMD Windows machines remains unverified.** Before declaring that support, use one representative team machine for a short check: installation/startup from a path containing spaces, SSH/Zeus connection, one small local run, and one isolated Zeus Smoke through completion/reload. This needs no new test infrastructure or repeat of long scientific optimizations. Previously documented limitations, including built-in single-run plots and lost-submission/global-VPN fault coverage, remain unchanged.

No main merge, push or team deployment was performed. This report verifies the installed test revision and does not silently approve scientific results or promote TEST ONLY outputs.
