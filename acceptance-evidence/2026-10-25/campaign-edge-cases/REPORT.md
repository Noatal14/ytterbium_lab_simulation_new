# Campaign edge-case acceptance — 25 October 2026

The bounded **failed-job, missing-result, corrupt-result and read-only disconnect/recovery checks passed for 2D and 3D on Mac and actual Windows ARM64/Parallels**. Four narrow defects were fixed using existing controllers, validators and shared UI actions. No scientific campaign, input, result, physical policy or active scientific job was modified; no main merge or push occurred. No new test service or product infrastructure was added. [Machine-readable qualification](qualification.json), [independent review](independent-review.json).

## Results and scope

| Case | Mac 2D | Native Windows ARM 2D | Mac 3D | Native Windows ARM 3D |
|---|---|---|---|---|
| Failed actual UI-submitted TEST ONLY job/chain | PASS | PASS | PASS | PASS |
| Actual remote result JSON temporarily missing | PASS | PASS | PASS | PASS |
| Actual remote result JSON temporarily corrupt | PASS | PASS | PASS | PASS |
| Read-only request interrupted, then recovered | PASS | PASS | PASS | PASS |
| Results after full page reload/reopening | PASS, automatic 2D restoration | PASS, automatic 2D restoration | PASS, explicit reconnect/check | PASS, explicit reconnect/check |
| Valid physical zero capture | Contract/component + normal zero-Smoke validator PASS; whole all-zero physical campaign not run | Same tests executed in real Windows; whole all-zero physical campaign not run | PASS, genuine prior Single-pass zero result | PASS, genuine prior Single-pass zero result |
| N=0 Zeeman input bank admission | PASS, catalogue + creation regressions | PASS, native Python regressions | Not a 3D input-bank test | Not a 3D input-bank test |

A valid zero capture and zero validated artifacts are different. Positive-input zero capture remains valid; an empty input ensemble is rejected because its conditional efficiency has no defined denominator. The 3D clients inspect the **same genuine Windows69 physical campaign**, not two new physical runs. Its Single-pass efficiency/interval are zero with 14 verified result artifacts. The overall outcome remains **extension required**, not a precision success or a scientific winner.

Disconnect means one controlled pre-dispatch read-only request abort, followed by normal UI refresh and reopening. It does not qualify a global VPN outage or loss of a submission acknowledgment. Fault tests never confirm another submission or advance a later stage; their browser contexts block such routes.

## Actual evidence and jobs

- 2D Mac: [failed job](mac-failed-smoke-observed/reopen-result.json), [missing/corrupt/restored](mac-result-fault-observed-guard-qualified-retry-sealed-412-actual-wire/reopen-result.json), [disconnect](../2d-automatic-recovery/mac-disconnect-edge-bounded-retry/reopen-result.json).
- 2D Windows: [failed job](windows-failed-smoke-observed-collected/reopen-result.json), [missing/corrupt/restored](windows-result-fault-observed-guard-qualified-retry-sealed-412-actual-wire-collected/reopen-result.json), [disconnect](../2d-automatic-recovery/windows-disconnect-edge-collected/reopen-result.json).
- 3D Mac: [failed chain](mac-3d-failed-observed/failed-result.json), [missing/corrupt/restored](mac-3d-result-fault/3d-result-fault-result.json), [disconnect](mac-3d-disconnect-fixed-v2-profile/3d-disconnect-result.json).
- 3D Windows: [failed chain](windows-3d-failed-observed-collected/failed-result.json), [missing/corrupt/restored](windows-3d-result-fault-collected/3d-result-fault-result.json), [disconnect](windows-3d-disconnect-fixed-v2-profile-collected/3d-disconnect-result.json).

Each directory includes raw responses, visible text and screenshots.

| New failure test | Exact scheduler IDs | Frozen resource scope |
|---|---|---|
| Mac 2D Smoke | `4822734.zeus-master` | 1 CPU, 4 GiB, 1 h, gd002 |
| Windows 2D Smoke | `4822739.zeus-master` | Same |
| Mac 3D Discovery | `4822830[]`–`4822834[].zeus-master` | Five dependency-array parents, three tasks each; 4 CPU/4 GiB/1 h per task, gd002 |
| Windows 3D Discovery | `4822839[]`–`4822843[].zeus-master` | Same |

Controlled cancellation targeted only exact new IDs from actual UI 201 receipts, after fresh owner, isolated working-directory and resource checks. Dependent jobs already terminated by PBS were not resubmitted. The normal adapters report failed states, and UI reopening preserves those exact chains without submission/advancement. [Mac 3D scheduler proof](mac-3d-failure-terminal-qstat.txt), [Windows 3D scheduler proof](windows-3d-failure-terminal-qstat.txt), [final account idle](account-idle-final.txt).

Only completed isolated TEST ONLY result JSONs were faulted. Existing reviewed FD-based Tree/Lease/protocol primitives were reused, with a 300-second restoration deadline and EOF/finally restoration. The original 224-file 2D closures per campaign and shared **895-file 3D closure** were verified after restoration: bytes, original inode, mode, link count, size and mtime. Rename/link operations change ctime, explicitly recorded in audit logs. [3D original normal-validator/full-closure qualification](3d-remote-normal-qualification-v2.ndjson), [3D lease/restoration audit](3d-actual-result-lease.ndjson).

Actual sealed-result corruption/missing files yield **HTTP 412 `remote_response_invalid`**, visible uncertainty, hidden final results and no completion confirmation. Restoring originals returns HTTP 200 with exact prior results. These real faults do not establish the separate typed-200-invalid branch; regression tests cover that branch.

## Fixes and verification

1. Fresh untransferred 2D recovery wrongly reported invalid preparation. The existing remote receiver now returns `smoke_not_submitted` only for an exact absent leaf after clean pinned checkout and anchored no-follow parent checks. Existing invalid paths and preparation errors remain errors. Actual new-receiver SSH inspection passed from [Mac](mac-absent-remote-receiver-integration.json) and [Windows](windows-absent-remote-receiver-integration.json).
2. Terminal 2D production states could leave a blank panel or retain stale successful results. The existing Failure UI now explains invalid/held/failed/unknown outcomes and offers its existing read-only status refresh. Unverified results are hidden.
3. Empty Zeeman input ensembles could enter a 2D campaign with an undefined efficiency denominator. Catalogue and creation reject them using the existing source-validation path. Positive-input zero capture remains valid.
4. A 3D final-completion communication error lacked the refresh action described by its message. The existing shared guarded-action component gains an opt-in read-only refresh mode; other stage defaults and confirmation authority remain unchanged. Actual Windows reproduced the old missing control; both updated clients recovered successfully.

Final focused Mac UI: **58 passed**, then the expanded zero-capture file **6 passed**. Final backend subset: **85 passed**; earlier wider receiver integration subset: **94 passed**. Native Windows: **41 3D UI + 17 production UI passed**, then expanded zero-capture file **6 passed**; empty-input/zero-Smoke subset **5 passed**. Native receiver-source subset: **41 passed, 53 POSIX-only cases skipped**; those skips are not claimed as Windows successes. TypeScript, changed-file ESLint and `git diff --check` passed. Logs are alongside this report.

Independent `release_safety_audit` review approved the four fixes, new zero-capture test, guarded artifact faults and settled native proofs. `windows_audit` authored fixes and supplied a further source review; its self-review is not counted as independent signoff.

Preserved failed test attempts are not passes: initial 3D calls used a v1 backend for a v2 campaign; correct profile selection resolved authorization rejection without weakening guards. A 3D duplicate-gesture helper stopped before dispatch; its pending checkpoint was never cleared or replayed. A separate single-click campaign supplied the genuine failed-chain test. Earlier 2D fixture binding/transport expectation failures restored originals before retry. No receipt or scientific guard was bypassed.

## Deployment boundary, remaining gaps and release recommendation

The tested frontends contain the reviewed product overlays. Existing saved-campaign backends remain clean producer69; the new source-admission and receiver fixes were qualified through native Python and actual pinned SSH source packets, **not silently installed into those historical pinned backends**. The isolated 3D test backends are currently configured for `ui_acceptance_v2`; the normal v1 launcher is unchanged. No installation or main merge is implied by this report.

Remaining: physical Intel/AMD Windows; a complete physical 2D all-zero-capture campaign (modeled contract/component plus native validator coverage exists); lost submission acknowledgment/global VPN interruption; repetition at every intermediate campaign stage. Built-in single-run plots remain the previously accepted documented gap, outside this campaign pass.

**Do not claim unrestricted team-release qualification yet.** This round supports the tested Mac/Windows ARM campaign edge-case scope. A release containing these backend fixes still needs installation qualification, and ordinary Intel/AMD Windows remains unverified. All remaining physical and fault-scope limitations above must accompany any narrower release claim.
