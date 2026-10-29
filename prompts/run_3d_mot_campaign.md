# Prompt: run the existing 3D-MOT optimization campaign

Copy everything below the separator into an AI coding assistant with access to
this repository and the Zeus terminal. Connect using `connect_to_zeus.md` first
if the Zeus environment is not ready.

---

Help me run the **existing, implemented 3D-MOT optimization workflow** on the
Technion Zeus cluster. Do not design a new optimization, replace the campaign
manager with your own scripts, or improvise a different sequence of stages.
Use `studies/mot_3d_campaign.py` and the current repository documentation.

Repository:

```text
https://github.com/YoavLaboratory/ytterbium_lab_simulation_new
```

Expected Zeus checkout and environment:

```bash
cd ~/ytterbium_lab_simulation_new
source ~/venvs/atomsmltr/bin/activate
```

These are historical CLI defaults. Read
`workflow_api/specifications/deployments_v1.json` and
`workflow_api/campaign_deployment.py` before selecting the execution target.
The current team checkout/environment are `~/ytterbium_lab_simulation_ui` and
`~/venvs/atomsmltr-ui`. The 3D manager inherits an explicit `execution_checkout`
from the completed upstream 2D campaign; an unbound campaign uses the
historical defaults. Ensure the selected checkout, generated jobs, and active
environment agree. Do not invent a `--execution-checkout` CLI option or edit a
manifest to retarget it. Verify the actual paths before using them. If I am not
connected or the environment is missing, use the repository's `prompts/connect_to_zeus.md` guide
first. Never ask me to paste credentials into the conversation.

## Task and sources of truth

Operate the maintained workflow for both configurations:

- Core MOT: internal family `angled_donut`;
- Cross MOT: internal family `single_pass`.

The source is the frozen survivor population from a completed canonical
2D-MOT campaign. This is not an arbitrary particle-state file or the sealed
final-validation population from a previous 3D-MOT study.

Before creating, advancing, or submitting anything, read:

```text
PROJECT_HANDOFF.md
docs/CONFIGURATION_OWNERSHIP.md
docs/3D_MOT_CAMPAIGN.md
docs/3D_MOT_FULL_OPTIMIZATION_PLAN.md
docs/3D_MOT_FINAL_RESULTS.md
data/README.md
studies/README.md
studies/mot_3d_campaign.py
workflow_api/mot_3d_stage_topology.py
workflow_api/mot_3d_workload.py
workflow_api/campaign_deployment.py
workflow_api/specifications/deployments_v1.json
docs/HISTORICAL_ZEEMAN_SOURCE_EVIDENCE.md
lab_setup/mot_3d_timestep_policy.py
lab_setup/specifications/mot_3d_timestep_policy_v2.json
```

Check the manager's current `--help` and relevant subcommand help. Follow the
current operational guide, executable validation, and versioned specifications;
the scientific plan also contains historical settings. If they disagree in a
way that affects this run, identify the discrepancy before submission rather
than silently choosing a protocol or bypassing a check.

## Initial information and checks

Determine whether I want to start a new campaign or resume an existing one.
For a new campaign, obtain:

1. a campaign name;
2. the completed upstream 2D-MOT campaign directory;
3. its corresponding survivor-state directory.

If I do not know the paths, inspect the existing records and identify eligible
sources instead of inventing paths or requiring me to reconstruct the data
layout. For resumption, obtain the existing campaign directory and inspect its
manifest, submission records, job status, and pinned runtime first.

Show the checkout's Git status and revision, verify the Python environment,
and inspect my existing Zeus jobs. Preserve local changes. Do not switch
branches, pull updates into a running campaign, or discard changes to make a
provenance check pass. A campaign's frozen revision must match its execution
checkout. Do not replace the source arrays or metadata with another sample. The current source validator may admit
the explicitly attested original corrected 19-ring bank. Preserve its historical
identity and use the implemented attestation; do not fabricate missing later
laboratory-specification metadata.

The upstream campaign must pass the manager's canonical completion and
provenance checks. The normal source contains 20 final 2D-MOT ensembles with
Zeeman seeds 3015-3034 and their registered 2D recoil seeds. The manager splits
these into 12 discovery, four refinement, and four preliminary-check ensembles.
All 20 are later available for finalist selection. Let the code validate the
seed pairs, settings, counts, and hashes; do not rename or edit files to fit.

## Preserve the implemented scientific design

Use the current versioned new-campaign policy. At the time this prompt was
written, policy v2 specifies:

```text
solver: RK4StHybridCustom
3D-MOT search/selection timestep: 10 microseconds
sealed final-validation timestep: 5 microseconds
3D-MOT endpoint throughout the campaign: 50 milliseconds
capture criterion: final distance <= 5 mm and total speed <= 1 m/s
final precision target: 95% interval half-width <= 0.75 percentage points
```

Read the actual specifications and capture configuration to verify these
values. Do not substitute the older 100-ms / 0.625-microsecond plan. The
legacy `approve-dt` command is not a normal step for a new policy-v2 campaign.
Do not reinterpret or migrate a historical campaign with the current runtime.

Preserve the implemented bounds, trial counts, ensemble roles, recoil seeds,
selection rules, aperture constraints, and parameter corrections. In particular,
use the implemented Cross MOT detuning-anchor correction rather than treating
the anchor as the applied detuning. Do not tune settings on final-validation
inputs or outcomes. Request a separate scientific decision only if the user
actually wants a different design; do not ask for a new optimization strategy
between routine stages.

## Create and smoke-test a new campaign

Use a new, empty canonical directory whose basename matches the campaign name:

```bash
python -u -m studies.mot_3d_campaign create \
  --name <CAMPAIGN_NAME> \
  --input-dir <MATCHING_2D_SURVIVOR_DIRECTORY> \
  --upstream-campaign <COMPLETED_2D_CAMPAIGN_DIRECTORY> \
  --output-dir data/optimization/mot_3d/<CAMPAIGN_NAME>
```

Replace placeholders with verified values in the commands you give me. The
manager's `--campaign` arguments below take the campaign **directory**, not the
`campaign.json` filename. Use repository-relative canonical paths for the
campaign root so that later transitions can validate it.

`create` freezes the inputs and writes the job bundle; it submits no jobs.
Read `campaign.json`, locate the two generated smoke PBS files in `jobs.smoke`,
and run those small checks on Zeus before starting discovery. Check their
scheduler exit status, logs, and trial outputs for both families. Do not count
smoke trials as completed discovery trials.

## Run the existing stage sequence

Follow `status` and the manager's validated transitions. The sequence is:

```text
discovery
preliminary_check
refinement
closure
finalist_selection
final_validation_input_generation
final_validation
complete OR final_validation_extension_required
```

Use the manager commands as follows, substituting the real directory:

| Current stage / action | Existing command |
| --- | --- |
| Inspect the current stage | `python -u -m studies.mot_3d_campaign status --campaign <CAMPAIGN_DIRECTORY>` |
| Submit discovery after the smoke checks | `python -u -m studies.mot_3d_campaign submit-discovery --campaign <CAMPAIGN_DIRECTORY>` |
| Validate completed work and prepare the next stage | `python -u -m studies.mot_3d_campaign advance --campaign <CAMPAIGN_DIRECTORY>` |
| Submit preliminary check, refinement, closure, finalist selection, or final validation | `python -u -m studies.mot_3d_campaign submit-stage --campaign <CAMPAIGN_DIRECTORY>` |
| Generate fresh final-validation inputs after the winners are locked | `python -u -m studies.mot_3d_campaign submit-final-inputs --campaign <CAMPAIGN_DIRECTORY>` |

`submit-discovery`, `submit-stage`, and `submit-final-inputs` actually call
`qsub`; they are not previews. Inspect the generated jobs and resource requests
before invoking them. Do not separately submit the same generated worker and
merge PBS files by hand: the manager owns dependencies and submission records.

Wait for each submitted chain, including its dependent merge or freeze jobs,
to finish successfully before calling `advance`. Inspect the resulting stage
with `status` before its next submission. Do not skip preliminary checks,
local sensitivity/closure, or finalist selection. Discovery has cumulative
restart-safe rounds; use its submission command rather than launching all
rounds independently. `freeze-final-inputs` is already invoked by the dependent
input-freezing job; do not run it prematurely by hand.

The finalist-selection transition locks one configuration per family before
new validation data are generated. The manager then generates and freezes 20
new input ensembles (Zeeman seeds 3035-3054, 2D recoil seeds 43035-43054).
Final 3D-MOT validation uses these same new incoming atoms for both families
with 3D recoil seeds 44001-44003. This repeats recoil realizations; it does not
create three independent incoming populations.

## Resources, monitoring, and recovery

- Guide me one stage at a time with complete commands and a short explanation.
  If you have terminal access and I authorized campaign execution, use the
  existing manager and report the actual command results. Otherwise, have me
  run the commands and return their output before dependent steps.
- Verify the laboratory's current Zeus CPU allocation and include already
  running jobs when checking concurrent resource use. Inspect CPU, memory,
  walltime, array size, and dependencies. Do not assume `0-2:1` is a concurrency
  limit: `:1` is the array stride. If the generated chains can exceed the
  allocation, resolve scheduling with the lab's supported procedure before
  submitting; do not silently alter the scientific design or rewrite frozen
  jobs. In particular, do not assume the two families run sequentially.
- Record the exact job IDs returned by the manager, including PBS array syntax.
  Use `qstat`, historical `qstat -xf` when available, stdout/stderr, and expected
  artifact counts. Disappearance from the active queue does not prove success.
- Respect the frozen Git revision and physical-model/input hashes throughout.
  Never edit campaign manifests, result JSON, selection files, or submission
  records by hand to force a stage transition.
- On a partial submission or a `partial_failure` record, inspect recorded job
  IDs and existing jobs first. Do not delete the record and blindly resubmit
  the entire chain. Use an existing documented recovery route; if none covers
  the failure, report the exact problem for a targeted repair.
- Preserve valid trial databases and completed results. For missing or failed
  tasks, identify the exact affected work and use the documented recovery
  procedure. Do not delete a campaign or restart all completed simulations.

## Completion and results

Run the last `advance` only after all final-validation workers and merges have
completed and their expected artifacts are present. Read both the resulting
stage and the emitted report:

- `complete`: verify `final_report.json` and both geometries' summaries;
- `final_validation_extension_required`: read
  `final_validation_status.json`, report the achieved intervals and unmet
  precision target, and stop ordinary advancement. The standard manager has
  no automatic extension transition. Do not invent an extension, change the
  target, or mark the campaign complete yourself.

The closed 2026-10-20 campaign has a separately documented owner-approved
execution/precision exception. It is historical evidence, not authorization to
reuse its directory, rerun `advance` on it, or waive checks for a new campaign.

Return a concise summary for each geometry:

```text
configuration and internal family name:
locked candidate ID and parameter-file path:
556 nm saturation, detuning, and waist:
399 nm saturation, applied detuning, and waist:
Cross MOT detuning anchor, separately from applied detuning:
weak-axis magnetic gradient and configuration-specific geometry:
number of validation ensembles and unique incoming atoms:
number of 3D recoil realizations:
conditional capture efficiency and 95% confidence interval:
precision-target status and actual campaign stage:
local sensitivity findings, separate from final validation:
locations of saved inputs, outputs, and frozen code/protocol records:
```

State that capture is conditional on surviving the 2D MOT, not on all oven
atoms. Do not present a search-stage result as the final held-out result.
Do not commit or push files unless I explicitly ask.

Begin by asking which completed 2D-MOT campaign and survivor population to use,
and what the new 3D-MOT campaign should be called; if I supplied an existing
3D campaign instead, inspect its state for resumption rather than creating one.
