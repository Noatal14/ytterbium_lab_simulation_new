# Prompt: run the existing fixed-intensity 2D-MOT campaign

Copy everything below the separator into an AI coding assistant with access to
this repository and, when available, the Zeus terminal. Use
`connect_to_zeus.md` first if the connection is not ready.

---

Help me operate the **existing fixed-intensity 2D-MOT optimization workflow**
on Zeus. Use `studies/mot_2d_s0_campaign.py`; do not design a replacement search,
write a new optimizer, or change its scientific decisions between stages.

Repository:

```text
https://github.com/YoavLaboratory/ytterbium_lab_simulation_new
```

For each positive finite `s0` value I supply, keep that value fixed while the
implemented workflow optimizes laser detuning and magnet radius. The current
reference intensity is `s0=1.3`, not a value to assume without my instruction.

## Read the current implementation first

Read these sources before proposing execution commands:

```text
PROJECT_HANDOFF.md
docs/2D_MOT_S0_CAMPAIGN.md
docs/2D_MOT_OPTIMIZATION_PLAN.md
docs/CONFIGURATION_OWNERSHIP.md
docs/HISTORICAL_ZEEMAN_SOURCE_EVIDENCE.md
data/README.md
studies/mot_2d_s0_campaign.py
studies/mot_2d/optimization.py
studies/mot_2d/production.py
workflow_api/mot_2d_spec.py
workflow_api/mot_2d_plan.py
workflow_api/mot_2d_late_stage.py
workflow_api/mot_2d_validation.py
workflow_api/campaign_deployment.py
workflow_api/specifications/deployments_v1.json
```

Inspect `python -m studies.mot_2d_s0_campaign --help` and subcommand help.
Use the executable rules and versioned specifications, including the approved
historical-source route. Some prose documentation predates the deployment and
statistical-validation changes. If a discrepancy affecting this run remains
unresolved by the explicit implementation and evidence, report it before
submission; do not bypass a check or edit a manifest to make it pass.

## Choose a new campaign or resume an existing one

For a new campaign, obtain:

- the fixed `s0` value or values and campaign name;
- the versioned Zeeman-survivor source directory;
- the Zeus checkout/environment in which the campaign will execute.

If I do not know the source path, inspect the available source records and
identify eligible banks. For resumption, inspect the existing campaign instead
of creating a second one. Give commands for the actual paths and username,
not unresolved placeholders or another researcher's account.

Show Git status, the revision, the active Python environment, and current jobs.
Do not automatically run `git pull`, rebase, or switch revisions in a checkout
used by active/pinned jobs. If a new campaign needs an update, first establish
that the checkout is suitable and preserve existing work; use a fast-forward
update only where safe. Never discard changes to satisfy provenance checks.

## Match the campaign to its execution checkout

Read the deployment specification rather than assuming all jobs use the same
folder. The current historical CLI defaults are:

```bash
cd ~/ytterbium_lab_simulation_new
source ~/venvs/atomsmltr/bin/activate
```

The team deployment is `~/ytterbium_lab_simulation_ui` with environment
`~/venvs/atomsmltr-ui`; test and acceptance deployments are separate.
The directory name does not require using the graphical interface.

A manifest with an explicit `execution_checkout` must execute in that bound
checkout with its corresponding environment. An unbound historical manifest
uses the historical defaults. In the current CLI, `create` has **no**
`--execution-checkout` argument and does not set this binding. Do not invent
such a flag or assume that invoking `create` inside the team folder binds its
jobs there. For the direct CLI route, use the verified historical target. If a
team-bound campaign is required, use an existing supported creation route that
records that binding, or explain the missing route before submission. Never
retarget a campaign by hand-editing JSON or PBS files.

## Validate the atomic inputs without rewriting them

All 35 Zeeman ensembles, seeds 3000-3034, must exist and pass the implemented
array, metadata, profile, hash, and scientific-source checks. Runtime inputs
are not supplied by an ordinary code checkout. The non-overlapping roles are:

| Role | Zeeman seeds | Use |
| --- | --- | --- |
| Discovery | 3000-3004 | Broad screening |
| Refinement | 3005-3009 | Focused search |
| Held-out confirmation | 3010-3014 | Candidate selection and sensitivity |
| Sealed validation | 3015-3034 | Final production only |

The manager records the corresponding MOT recoil seeds; currently they are
`40000 + zeeman_seed`. Use the manifest's actual registry. Parameter settings
must share the same input subsets and matched recoil realizations.

The original corrected 19-ring bank is explicitly supported through
`lab_setup/historical_zeeman_source.py` and its evidence document. It may lack
later laboratory-specification metadata. Admit it only when the current reader
and exact historical-bank attestation pass; unknown or modified legacy banks
are not authorized. Do not reject the approved original bank solely because
it lacks later metadata, and do not add fabricated laboratory identity fields
or rewrite its original arrays/metadata to make it look newly generated.
Keep the historical input identity separate from the executing code identity.

## Preserve the scientific design

Verify these values against `mot_2d_spec.FIXED_DESIGN` and the numerical policy:

```text
solver: RK4StHybridCustom
screen/refine timestep: 1.25 microseconds
confirmation/sensitivity/production timestep: 0.625 microseconds
detuning domain: -1.55 to -0.85 Gamma
magnet-radius domain: 0.045 to 0.051 m
provisional control shifts: +/-0.01 Gamma and +/-0.00001 m
stress-test shifts: +/-0.02 Gamma and +/-0.0001 m
reporting population: 10,000,000 incoming Zeeman survivors
95% prediction half-width target: 0.05 percentage points
```

The reporting population is a reference count, not a measured laboratory flux.
Do not substitute a mean-efficiency confidence interval for the prediction
interval used by the implemented stopping flag. Do not change the bounds,
solver, timesteps, sample sizes, seed roles, or selection rules unless I
explicitly request a separate scientific change. Use a normal scientific
campaign, not a miniature TEST ONLY/acceptance profile as a shortcut.

## Create once, then operate the existing stages

Use a new empty directory under `data/optimization/mot_2d/`. With verified
values, the creation command is:

```bash
python -m studies.mot_2d_s0_campaign create \
  --name <CAMPAIGN_NAME> \
  --s0 <EXPLICIT_S0_VALUES> \
  --ensemble-dir data/particle_states/after_zeeman/<SOURCE_DIRECTORY> \
  --zeeman-profile <PROFILE_VALIDATED_FROM_SOURCE> \
  --output-dir data/optimization/mot_2d/<CAMPAIGN_DIRECTORY>
```

`create` freezes the design and inputs and prints the first job; it submits
nothing. `--campaign` below takes the campaign directory, not its JSON file.
Follow the unchanged sequence:

```text
smoke -> screen -> refine -> confirmation -> sensitivity -> production -> complete
```

| Stage | Implemented work for each s0 |
| --- | --- |
| Smoke | Two-particle check, using the generated smoke job |
| Screen | Three Optuna workers, 17 completed trials each; five discovery ensembles of 2,000 atoms per setting |
| Refine | Three distinguishable centers; five refinement ensembles of 10,000 atoms; four cumulative rounds with targets 3, 6, 9, 10 completed trials per worker |
| Confirmation | Five candidates on five held-out groups of 10,000 atoms |
| Sensitivity | Deduplicated control-resolution and stress grids around the confirmed center, normally 17 settings; the same five held-out groups |
| Production | Every available survivor in the 20 sealed ensembles, at the selected production settings |

Run the first generated smoke PBS job and verify it before advancing. After
**all** jobs for a stage have completed successfully, invoke:

```bash
python -m studies.mot_2d_s0_campaign advance \
  --campaign data/optimization/mot_2d/<CAMPAIGN_DIRECTORY>
```

The manager validates that stage and writes the next stage's tasks and job
files. Submit the generated artifact it identifies, rather than manually
constructing the trials. Refinement uses the generated
`jobs/03_submit_refinement_chain.sh` **once**, not four independent submissions.
It preserves each worker's database, study, bounds, seed, and cumulative targets
with whole-array `afterok` dependencies. Wait for the entire chain before
advancing; never interpret each cumulative target as that many extra trials.
Do not invent 3D-manager commands such as `submit-stage` for this 2D CLI.

Inspect progress at any stage with:

```bash
python -m studies.mot_2d_s0_campaign status \
  --campaign data/optimization/mot_2d/<CAMPAIGN_DIRECTORY>
```

## Selection and the meaning of sensitivity results

The confirmed center is selected by the highest lower endpoint of its 95%
mean-efficiency interval, then higher mean efficiency, with the implemented
candidate-index tie-break. The sensitivity stage can change the production
point: use `select_production_point` and the generated `production_selection`,
not a manual choice based on the largest observed mean.

The current neighbor-promotion rule uses **Bonferroni simultaneous paired
intervals**, with per-comparison confidence `1 - 0.05 / (number_of_points - 1)`.
A neighbor is promoted only when its corrected difference interval lies wholly
above zero. If several qualify, the code ranks by the lower difference bound
and then the mean. Otherwise retain the confirmed center.

An interval containing zero is not evidence of equivalence. The fixed grid
does not establish a stable/robust region or epsilon-near-optimality. Preserve
and report the actual `robustness_status`, `near_optimality_status`, and
selection flags. Do not turn unresolved differences into claims of stability.

## Submission, monitoring, and recovery

- Give complete commands for the current step and explain their purpose. If
  you have terminal access and I authorized execution, operate the existing
  workflow directly. Otherwise, wait for my command output before dependent
  steps. Do not request a new optimization strategy between routine stages.
- Check generated PBS paths, loaded modules, the activated environment, pinned
  revision, CPUs, memory, walltime, and concurrency before submission. Screen
  currently requests 24 hours; refinement has four 20-hour rounds. Canonical
  heavy arrays allow three 200-core or four 150-core tasks. Account for other
  running campaigns and verify the laboratory's current total allocation.
- Record exact IDs returned by `qsub`, including array syntax. Use active and
  historical scheduler status, stdout/stderr, expected outputs, and exit codes.
  Disappearance from `qstat` does not establish success.
- Preserve completed tasks and valid databases. If work is missing, identify
  exact failed indices and use the documented recovery route. Do not delete
  the campaign, reset its databases, or resubmit successful tasks wholesale.
  Do not bypass receipt/hash checks by inventing replacement PBS files or
  manually editing frozen manifests and result records.

## Final results and the 3D-MOT handoff

At `complete`, read the actual `final_report.json`. A boundary winner or a
missed prediction-precision target is still returned with warnings; it does
not authorize changing the target, automatically expanding the search, or
hiding the best tested result.

For every s0, report:

```text
fixed s0 and recommended detuning / magnet radius:
production-selection reason, including any promoted sensitivity neighbor:
sealed sample size and number of ensembles:
conditional mean transfer efficiency and its confidence interval:
prediction for the reference population and its prediction interval:
implemented prediction-precision target: PASS/FAIL
boundary, robustness, and near-optimality flags:
survivor_states_directory from the final report:
completed campaign directory and frozen revision:
```

Efficiency is conditional on incoming Zeeman survivors, not on all oven atoms.
The reference-population prediction is not atoms per second. Do not conflate
pooled efficiency, equal-ensemble mean, confidence intervals, and prediction
intervals; use the exact quantities supplied by the saved summary.

Resolve survivor outputs from the final report or
`mot_2d_spec.survivor_states_directory`, not a guessed hardcoded folder. Current
team-bound campaigns use
`data/particle_states/after_2d_mot/campaigns/<CAMPAIGN_SLUG>/s0_<VALUE>/`;
unbound historical CLI campaigns retain
`data/particle_states/after_2d_mot/final_ensemble_s0_<VALUE>/`.
Check for pre-existing outputs **before** starting a new campaign. In particular,
legacy campaigns with the same s0 share the latter path: do not overwrite
another campaign's survivors. Use an existing supported namespace/deployment
route or resolve the conflict before running; do not manually redirect frozen
jobs. Verify all 20 state arrays and adjacent metadata, `(N, 6)` layout, finite
values, hashes, counts, and the exact registered source/recoil seed pairs.

Use that completed campaign and its matching survivor directory as the 3D-MOT
source, following `prompts/run_3d_mot_campaign.md`. Do not assume a new full 3D
optimization is scientifically necessary for every 2D retuning; the documented
transferability study is a separate follow-up, not part of this campaign.

Do not commit, push, or add runtime artifacts to Git unless I explicitly ask.
For data retention, follow the scientific-data archive policy. Never add
SQLite databases, credentials, logs, or temporary files.

Begin by asking for my fixed s0 value(s), campaign name, and the intended input
source and execution checkout. If I instead supply an existing campaign,
inspect it for resumption rather than creating another one.
