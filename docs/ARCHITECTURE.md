# Project architecture

This is the ten-minute map for a new developer, student, or AI assistant. It
explains where responsibilities live and which boundaries must remain stable.
For scientific status and results, read `PROJECT_HANDOFF.md`; for campaign
operation, use the maintained campaign guides under `docs/`.

## System map

```text
config.py + lab_setup/
        |
        v
simulations/  <----  atomsmltr/
        |
        v
studies/  -------------------->  data/ + graphs/
        |
        v
workflow_api/
        |
        v
future UI  ---- explicit approval boundary ---->  Zeus scheduler / SSH
```

- `config.py` and `lab_setup/` define the apparatus, atomic parameters, laser
  geometry, magnetic fields, and supported simulation defaults.
- `simulations/` contains the physical stage engines. It should not know about
  campaign manifests, PBS files, or user interfaces.
- `atomsmltr/` is the bundled simulation library used by those engines.
- `studies/` contains reproducible scientific workflows built on the engines.
  Its two root managers are the canonical campaign entry points.
- `workflow_api/` is the side-effect-free application boundary. It translates
  manifests into serializable summaries and safe next-action plans.
- A UI must consume `workflow_api`; it must not import simulation workers or
  submit jobs merely because a page was opened.

## Canonical entry points

The supported campaign commands are:

```bash
python -m studies.mot_2d_s0_campaign --help
python -m studies.mot_3d_campaign --help
```

Their implementation modules are grouped by domain and stage:

```text
studies/
├── mot_2d_s0_campaign.py       # canonical 2D campaign manager
├── mot_3d_campaign.py          # canonical 3D campaign manager
├── mot_2d/                     # 2D optimization, production, validation
├── mot_3d/                     # 3D discovery through final validation
├── zeeman/                     # ensemble generation and reusable checks
└── beam_source/                # thermal-source and flux calculations
```

Detailed module ownership is recorded in `studies/README.md`. Do not add a new
flat top-level script when it belongs to an existing scientific domain or
campaign stage.

## Scientific data flow

```text
thermal source
    -> Zeeman survivor ensembles
    -> optimized 2D-MOT survivor ensembles
    -> optimized 3D-MOT candidates
    -> newly generated sealed ensembles for the final unbiased claim
```

Each arrow is an explicit artifact boundary. Downstream campaigns validate and
freeze upstream paths, hashes, seeds, parameters, solver choices, timesteps, and
Git revision. Never replace a frozen input in place or combine a manifest/PBS
file with a different checkout.

Candidate-selection data and sealed validation data have different scientific
roles. Discovery, refinement, preliminary checks, and finalist selection may
choose parameters. Only newly generated sealed ensembles may support the final
unbiased performance statement.

## Sources of truth

Use this precedence and stop when two layers disagree:

1. Code and configuration define the currently supported behavior.
2. A campaign manifest freezes the exact design of one campaign run.
3. Scientific plan documents explain why that design was chosen.
4. Operator guides and prompts explain how to run it.

Do not silently choose one source when the layers conflict. Report the
discrepancy before creating or submitting work.

Current operational documents:

- `docs/2D_MOT_OPTIMIZATION_PLAN.md` — scientific 2D plan;
- `docs/2D_MOT_S0_CAMPAIGN.md` — fixed-intensity 2D operating guide;
- `docs/3D_MOT_FULL_OPTIMIZATION_PLAN.md` — scientific 3D plan;
- `docs/3D_MOT_CAMPAIGN.md` — canonical 3D operating guide; and
- `PROJECT_HANDOFF.md` — current scientific and project status.

Historical conclusions that remain useful belong in an explicitly historical
document, not in an active command path.

## Where to make a change

| Intended change | Primary location | Required follow-up |
| --- | --- | --- |
| Apparatus geometry or physical constants | `config.py`, `lab_setup/` | Physics tests, convergence impact, documentation |
| Numerical propagation or capture behavior | `simulations/`, possibly `atomsmltr/` | Focused numerical tests and provenance review |
| Optimization design or campaign lifecycle | Root campaign manager and its domain package | Manifest/version review, PBS dry run, campaign tests |
| Reusable scientific diagnostic | Relevant `studies/<domain>/validation/` area | Test and document its scientific purpose |
| UI display or workflow inspection | `workflow_api/`, then UI package | Side-effect tests and schema compatibility |
| Plot or publication figure | `graphs_scripts/` | Preserve the input/result provenance |

Changing a default is not equivalent to changing a frozen campaign. Existing
campaigns remain tied to the commit and design recorded in their manifests.

## Campaign and UI boundary

`workflow_api` may:

- list supported workflows;
- inspect 2D and 3D manifests;
- report validated progress and warnings;
- describe the next safe command; and
- return serializable artifact references.

It must not:

- run a simulation;
- call `qsub` or SSH;
- mutate a campaign;
- infer success from unvalidated filenames; or
- expose an executable plan when required artifacts are missing or untrusted.

The eventual submission path should remain explicit:

```text
UI -> inspect/plan -> show user -> user confirms -> submission adapter -> Zeus
```

Credentials must be handled by the operating system or SSH tooling, never
stored in project source, manifests, logs, or ordinary configuration files.

## Adding a campaign stage

When a new stage is genuinely required:

1. Define its scientific role and whether it performs selection or validation.
2. Add the worker under the appropriate domain/stage package.
3. Make the root campaign manager the sole lifecycle and submission authority.
4. Freeze inputs, seeds, solver, timestep, parameters, commit, and relevant-file
   hashes in the manifest or stage design.
5. Make writes atomic and restarts deterministic.
6. Add integrity tests for incomplete, stale, foreign, and duplicated outputs.
7. Extend `workflow_api` without importing the worker or adding side effects.
8. Update the scientific plan and operator guide without duplicating authority.

## Data and generated artifacts

- `data/` contains canonical inputs, campaign manifests, summaries, and selected
  generated artifacts. Its subdirectories may include historical results.
- `graphs/` contains rendered scientific outputs; `graphs_scripts/` contains
  their generators.
- Scheduler logs and transient databases are not scientific deliverables and
  are excluded by `.gitignore`.
- Large reproducible arrays should not remain in the active branch merely as a
  backup. Before removal, distinguish Git-tracked, local-only, and Zeus-only
  copies and preserve the reconstruction contract.

## Before merging a change

At minimum:

```bash
python -m pytest -q
git diff --check
```

Use a non-interactive Matplotlib backend when running the complete suite on a
machine where GUI plotting is unavailable:

```bash
MPLBACKEND=Agg python -m pytest -q
```

For campaign changes, also perform the documented no-simulation dry run and
inspect every generated PBS dependency. Never update a live Zeus checkout away
from the commit pinned by an active campaign.

## Reading order for a new contributor

1. `GETTING_STARTED.md`
2. this document
3. `README.md`
4. `PROJECT_HANDOFF.md`
5. the scientific plan and operating guide for the campaign being changed
6. `studies/README.md` and the relevant tests

This order gives a useful mental model before exposing the reader to the full
scientific history.
