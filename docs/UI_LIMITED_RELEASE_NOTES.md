# UI release scope — 2026-10-28

The official application is the single `main` checkout. On this Mac use
`/Users/noatal/Ytterbium UI` and the desktop **Open Ytterbium UI.command**.
The Windows entry is **Open Ytterbium UI (Windows).cmd** and uses `C:\Users\noatal\work\Ytterbium UI`, a native Windows checkout. Historical copies and unique changes are archives, not launch
locations. Do not remove them without checking their inventory.

## Capacity policy and synchronized deployment

`workflow_api/individual_limits.py` owns individual particle capacity:
1–1,000 locally and 1–50,000 on Zeus, subject to available input particles.
`python -m scripts.generate_individual_limits` regenerates the JSON/TypeScript
projections; `--check` verifies them without writes. Byte-size and metadata
bounds are separate safeguards, not alternate particle limits. Scientific
configuration defaults and campaign policies remain separate and unchanged.

The ordinary product UI defaults to the dedicated team deployment
`/home/YOUR_USERNAME/ytterbium_lab_simulation_ui` in each member's own Zeus
account, with `~/venvs/atomsmltr-ui`. It requires no ignored local environment
file. The deployment registry is shared by backend, frontend and job rendering.
The historical scientific checkout is not an update target. Use
[UI quickstart](../UI_QUICKSTART.md) and [Team deployment](TEAM_DEPLOYMENT.md)
for installation. Desktop shortcuts are local conveniences, not portable
repository dependencies. The older isolated target used in the historical
qualification below is not the default team destination.

## Historical verification and fixed collection defects (2026-10-27)

Job **4830031.zeus-master**, run **mot2d-e0e70cc1a91c95fb8b20a53e**:
5,000 selected Zeeman survivors, seeds 42/42, 200 cores, 64 GiB, 24-hour cap,
completed on gd002 with Exit 0 in 00:24:38. Results: **129 survivors (2.580%)**.
Submission, running state, collection, refresh recovery and reopening were
verified through the real Mac UI. Only one job was submitted. Particle states
were intentionally not retained; the verified summary and nonretention receipt
are saved. No extra scientific source population was generated.

The computation used main `9e72647`; collector fix `55419bb` retrieved that exact
original product without rewriting it or resubmitting. Do not describe this as
execution of the new collector commit on the compute node. The fix shares
receipt/artifact validation with local publication. It also corrects the 3D
retained-state count to residence-qualified captures, distinct from usable-at-end
particles. Regression coverage includes actual worker serialization for 2D/3D,
retained/nonretained results, corrupt receipts, and strict new-submission commit
guards. Known historical commits are admitted only for read-only job retrieval.

Windows ARM/Parallels was synchronized and its real native Edge UI established a
read-only Zeus connection to the matching isolated checkout. No additional
Windows job was submitted in this round. Existing campaign evidence is
historical and must not be relabeled as newly executed qualification.

## Release restrictions

- **Local publication on Windows:** one qualification run produced valid saved
  result files but did not finish publishing its completed status. Its cause is
  unresolved; later native runs passing does not establish a fix. If the UI
  reports that local execution needs inspection, keep the run and its files,
  stop, and contact the maintainer. Do not resubmit to recover that run. Filtered
  error IDs now help diagnose a recurrence without exposing private paths or
  exception text. This issue remains a release qualification limitation.
- **3D refinement:** a legal boundary candidate can stop with
  `refinement_design_duplicate`. Keep the results and stop; no automatic fallback
  or resubmission is supported. The algorithm is unchanged by explicit decision.
  Do not promise autonomous completion for every valid campaign.
- **Windows Intel/AMD remains untested.** Native ARM tests do not qualify it.
- **Windows paths:** install in a short, writable local folder. Native collection
  tests passed with generated paths up to 199 characters. An earlier test at
  265 characters published the exact expected bytes but failed the existing
  validator's ordinary path lookup at the Win32 path-length limit. Those failures
  remain recorded; arbitrary long paths are not supported or qualified.
- Individual result pages provide verified summaries and retained data when
  requested; built-in individual result plots remain a documented gap accepted
  for this release scope.
- The 50,000-particle bound is a validated admission/serialization capacity, not
  a claim that every such physical job completes within its resource limit.
- This round physically qualifies the 5,000-particle 2D path above. It does not
  repeat all historical campaign and individual physical runs on this commit.

Recommend a limited team release only with these restrictions disclosed, not an
unrestricted claim that all campaigns finish autonomously on every Windows PC.
The final test log, per-platform evidence, consolidation inventory and current
revision manifest are retained outside the application in
`Ytterbium UI Archive/2026-10-27/unified-release`.
