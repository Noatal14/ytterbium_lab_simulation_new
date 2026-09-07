# Prompt: run the automated fixed-intensity 2D-MOT campaign

Copy everything below this line into a new AI conversation.

---

I want you to guide me through running an automated 2D-MOT optimization
campaign on the Zeus cluster.

The repository is:

```text
https://github.com/Noatal14/ytterbium_lab_simulation_new
```

Its expected location on Zeus is:

```text
~/ytterbium_lab_simulation_new
```

The Python environment is:

```text
~/venvs/atomsmltr
```

I know how to connect to Zeus, but I need you to guide me through everything
else. At every stage, provide complete, copy-ready commands. Do not give vague
instructions such as "update the file" or "run the script."

## Campaign objective

I will provide a list of laser saturation parameter values, `s0`, that may be
available in the laboratory. For every supplied value, the campaign must:

1. find the recommended detuning and magnet radius;
2. perform broad screening and focused refinement;
3. confirm the three strongest candidates;
4. measure sensitivity to small detuning and radius changes;
5. perform final production runs;
6. predict capture for `10,000,000` Zeeman survivors with a 95% interval;
7. save all captured 2D-MOT states for future 3D-MOT studies; and
8. return the best tested result even when it lies on a search boundary or
   misses the uncertainty target, with a clear warning.

## Sources of truth

Before providing commands, read the current versions of:

```text
docs/2D_MOT_S0_CAMPAIGN.md
docs/2D_MOT_OPTIMIZATION_PLAN.md
PROJECT_HANDOFF.md
data/README.md
config.py
studies/mot_2d_s0_campaign.py
studies/optimize_2d_mot_joint.py
studies/run_2d_mot_final_production.py
```

The current repository code and documentation override this prompt if they
differ. The principal operating guide is `docs/2D_MOT_S0_CAMPAIGN.md`, and the
principal program is `studies/mot_2d_s0_campaign.py`.

## Locked scientific design

Do not change these settings unless I explicitly ask:

```text
2D-MOT timestep: 0.625 microseconds
stochastic solver: RK4StHybridCustom
detuning search domain: -1.55 to -0.85 Gamma
magnet-radius search domain: 0.045 to 0.051 m
provisional detuning resolution: 0.01 Gamma
provisional magnet-radius resolution: 0.00001 m
prediction population: 10,000,000 Zeeman survivors
target 95% prediction half-width: 0.05 percentage points
```

`config.py` is the source of truth for simulation defaults. Verify that the 2D
MOT uses `RK4StHybridCustom` by default and reads its timestep from
`MOT_2D_SIM_CONFIG`. Do not alter the physics, capture criterion, search bounds,
particle counts, seed counts, or winner-selection rule during the campaign.

## How to work with me

- Guide me one stage at a time.
- Give only the commands needed now and a short explanation.
- Put commands in separate code blocks.
- Replace placeholders with actual values as soon as I provide them.
- Never infer success merely because a job disappeared from `qstat`.
- Check `Exit_status`, error logs, and expected result counts.
- Run the built-in smoke test before expensive work.
- Preserve valid results and never rerun completed tasks.
- Diagnose failures and rerun only missing tasks.
- Respect the approximately 600-core simultaneous project limit.
- Prefer a few long-lived jobs that reuse worker pools over many short jobs.
- Do not ask me to make scientific decisions between stages.

## Starting the campaign

First ask me only for the `s0` values and campaign name. After I answer, provide
copy-ready commands that enter the repository, activate the environment, check
for old matching jobs, inspect Git status, update safely, display the commit,
and run a short syntax/import check. Use:

```bash
cd ~/ytterbium_lab_simulation_new
source ~/venvs/atomsmltr/bin/activate
git status --short
git pull --ff-only origin main
git log -1 --oneline
```

Then create the campaign using actual values in this structure:

```bash
python -m studies.mot_2d_s0_campaign create \
  --name <CAMPAIGN_NAME> \
  --s0 <S0_VALUES> \
  --output-dir data/optimization/mot_2d/<CAMPAIGN_DIRECTORY>
```

Do not leave angle-bracket placeholders in the final command. The program will
print the first generated PBS file; give me its exact `qsub` command.

## Advancing and monitoring

After each job finishes successfully, use:

```bash
python -m studies.mot_2d_s0_campaign advance \
  --campaign data/optimization/mot_2d/<CAMPAIGN_DIRECTORY>
```

This validates the stage and creates the next PBS file. Display that file,
verify its array size, cores, and walltime, give me the exact `qsub` command,
and ask for the returned Job ID. The stages are:

```text
smoke
screen
refine
confirmation
sensitivity
production
complete
```

Never skip or reorder them. Show scientific progress with:

```bash
python -m studies.mot_2d_s0_campaign status \
  --campaign data/optimization/mot_2d/<CAMPAIGN_DIRECTORY>
```

Use the real Job ID I provide for scheduler checks. For example:

```bash
qstat -t -u tal.noa
qstat -f '<JOB_ID>[<ARRAY_INDEX>]' | grep -E \
  'job_state|resources_used.cpupercent|resources_used.cput|resources_used.walltime|exec_host|Resource_List.walltime'
qstat -xf '<JOB_ID>' | grep -E \
  'job_state|Exit_status|resources_used.cpupercent|resources_used.cput|resources_used.walltime|exec_host|Resource_List.walltime'
```

Adapt these to the actual Zeus Job ID syntax and remove placeholders from the
commands you give me. Locate `.out` and `.err` files using the Job ID and file
timestamps rather than guessing names.

## Failure handling

If `advance` reports missing results, preserve completed files, read the stage's
`tasks.json`, identify exact missing array indices, inspect their logs, and give
copy-ready commands to rerun only those tasks. If PBS cannot submit one index,
create a temporary non-array PBS file that explicitly sets `PBS_ARRAY_INDEX`.
For Python, import, path, or serialization errors, run a tiny local test before
resubmitting expensive work. Never delete a whole campaign because one task
failed.

## Final result

At `complete`, read `final_report.json` from the campaign directory. For each
`s0`, report:

```text
s0:
recommended detuning:
recommended magnet radius:
expected conditional capture efficiency:
expected captured atoms from 10,000,000 Zeeman survivors:
95% predicted captured-atoms range:
95% half-width in percentage points:
uncertainty target: PASS/FAIL
boundary warnings:
local sensitivity conclusions:
saved 2D-MOT survivor-state directory:
```

State clearly that efficiency is conditional on entering the 2D MOT as a
Zeeman survivor, not relative to all oven atoms.

For each `s0`, verify its directory under:

```text
data/particle_states/after_2d_mot/final_ensemble_s0_<value>/
```

For all 20 Zeeman seeds, verify an `.npy` array and adjacent `.json` metadata,
shape `(N, 6)`, finite values, and matching survivor counts.

## Git handling

Do not add SQLite databases, logs, or temporary files to Git. At the end, first
show `git status --short` and identify valid summaries, production results, and
survivor states. Only after my approval, provide exact commands for staging,
committing, pulling with rebase, and pushing. Never commit or push without my
explicit approval.

Begin now with one short question only: Which `s0` values should be tested, and
what should the campaign be called?

