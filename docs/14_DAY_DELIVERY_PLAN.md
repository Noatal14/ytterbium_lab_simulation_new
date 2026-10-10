# 14-Day Project Delivery Plan

## Deadline and required outcomes

This plan covers the final 14 project days. The required deliverables are:

1. Scientifically defensible 3D-MOT optimization results for the angled-donut
   and single-pass configurations.
2. A non-technical UI that can create, run, monitor, advance, and inspect the
   canonical 2D- and 3D-MOT optimization campaigns after laboratory changes.
3. UI workflows for individual Zeeman, 2D-MOT, and 3D-MOT simulations, with
   validated configuration, local or Zeus execution, and an explicit choice
   about retaining particle-state outputs.
4. Versioned, validated configuration and data layouts that are maintainable,
   reproducible, and safe for future operators.

Scientific results and canonical campaign operation have priority over optional
polish. No scientific default may change without explicit approval.

## Workstream A — 3D-MOT scientific results

1. Complete paired timestep convergence validation on the new sealed 2D-MOT
   survivors. Compare 10, 5, 2.5, 1.25, and 0.625 microseconds against the
   0.3125-microsecond reference for both families.
2. Approve screening and final timesteps only from the registered convergence
   evidence.
3. Run smoke checks, discovery, focused refinement, independent confirmation,
   sensitivity analysis, and sealed final validation.
4. Preserve separate input roles and paired uncertainty calculations.
5. Produce a final comparison report with parameters, efficiencies, confidence
   intervals, boundary hits, sensitivity, timestep evidence, limitations, and
   the physical interpretation of single-pass instability.

Acceptance requires complete provenance, no mixed tuning/final ensembles, and
no robustness or near-optimality claim unsupported by evidence.

## Workstream B — close the UI maintainability review

1. Repair the Playwright CI browser installation and run the intended Chromium
   and WebKit projects.
2. Correct stale documentation and remaining production literals that duplicate
   the canonical generated specification.
3. Add table-driven lifecycle tests for waiting, review, submission, running,
   held, failed, unknown, complete, expired-preview, stale-response, profile
   replacement, backend-loss, reset, and navigation cases.
4. Extract one controller hook per remote flow: transfer, smoke, screening,
   refinement, and confirmation. Keep cross-stage orchestration in
   `CampaignDetail`.
5. Split large stage components by user-visible responsibility while preserving
   DOM order, focus behavior, live regions, heading structure, and responsive
   behavior.
6. Add one thin Browser → real workflow API → fake Zeus integration test. It
   must never use real SSH, network access, or `qsub`.
7. Add pinned ESLint and Prettier check-only gates, then format incrementally.

Each extraction is a separate reviewable change with focused tests before the
next flow moves.

## Workstream C — versioned configuration architecture

Configuration is separated by ownership rather than placed in one giant file:

- immutable atomic and physical constants remain typed Python definitions;
- laboratory-controlled apparatus settings live in versioned validated data
  specifications;
- campaign search domains, budgets, seed roles, and stopping rules live in
  versioned campaign specifications;
- numerical solver and timestep policies live in versioned numerical
  specifications;
- `config.py` temporarily remains a compatibility facade while consumers are
  migrated.

The active code exposes one canonical 19-ring Zeeman configuration. Incorrect
profiles are removed from active configuration and remain recoverable only
through Git history. Immutable manifests from already completed or running
campaigns retain their recorded provenance, but no compatibility alias for the
incorrect profile is added to production configuration.

Every specification has an explicit schema version, SI-unit field names,
finite/range/cross-field validation, deterministic serialization, and SHA-256.
Every campaign or individual run freezes its complete resolved configuration.

## Workstream D — canonical run and data model

New UI-created individual runs use:

```text
data/runs/<zeeman|mot_2d|mot_3d>/<run_id>/
  run.json
  configuration.json
  inputs.json
  status.json
  results/
    summary.json
    states.npy          # only when durable state retention was requested
  logs/
```

The run manifest records schema version, execution mode, timestamps, status,
Git revision, configuration hash, input provenance, particle count, seed,
solver, timestep, retention policy, and the exact output registry.

Choosing not to save results means large particle-state arrays are not retained.
A small provenance receipt and scheduler/log evidence remain for safety and
reproducibility. Existing campaign layouts are supported through adapters; the
deadline does not require a risky bulk migration of historical data.

## Workstream E — individual simulation workflows

All three families use the same safe sequence:

```text
Configure → Validate → Review → Run → Monitor → Results
```

Execution modes:

- **Local:** bounded particle count and worker count, background execution,
  live status, no SSH.
- **Zeus:** exact input preview, explicit confirmation, allowlisted PBS
  generation/submission, scheduler monitoring, and controlled result retrieval.

The Zeeman workflow supports validated apparatus/laser/source configuration and
optional survivor-state retention. Saved, sufficiently large, fully provenanced
outputs may be offered to 2D-MOT workflows.

The 2D- and 3D-MOT workflows support validated physical parameters, approved
solver/timestep choices, explicit seeds, and optional state retention. The UI
distinguishes data suitable only for an individual run from data sufficient for
smoke, discovery, or sealed campaign validation.

## Workstream F — campaign UI completion

The 2D workflow covers creation, transfer, smoke, screening, refinement,
confirmation, sensitivity, production, and final reporting.

The 3D workflow covers selection of a completed canonical 2D campaign,
timestep validation, smoke, discovery, refinement, independent checks,
sensitivity, final validation, and reporting.

Every screen states the current stage, current status, what is happening,
whether user action is required, the next permitted action, relevant Zeus jobs,
warnings, and durable results. Unsafe or scientifically invalid transitions are
blocked rather than merely warned about.

## Calendar

### Days 1–2

- Close the external UI review findings and test the repaired CI gates.
- Monitor and merge 3D timestep validation; submit discovery immediately after
  evidence approval.

### Days 3–4

- Finish controller extraction, focused component splitting, real-backend
  integration coverage, and check-only lint/format gates.
- Characterize current configuration behavior and introduce validated versioned
  specifications without changing scientific defaults.

### Days 5–6

- Establish the canonical Zeeman configuration, compatibility facade, run data
  schema, configuration snapshots, and run registry.
- Implement the Zeeman individual-run backend.

### Days 7–8

- Implement the Zeeman UI, local execution, Zeus preview/submit/status, and
  retention behavior.
- Continue the 3D campaign stages as results become available.

### Days 9–10

- Implement individual 2D-MOT runs and complete the canonical 2D campaign UI.

### Days 11–12

- Implement individual 3D-MOT runs, complete the 3D campaign UI, and generate
  the scientific result views and report inputs.

### Day 13

- Run full Python, frontend, contract, build, browser, security, and data
  integrity gates. Complete operator documentation and project handoff.

### Day 14

- Reserved buffer for delayed jobs, defects, demonstration preparation, final
  report/PDF preparation, release tagging, and backup.

## Scope controls

The deadline explicitly excludes a generic arbitrary-parameter editor, user
accounts, cloud deployment, a server database, full historical-data migration,
an arbitrary workflow builder, shell access through the UI, and automatic
destructive cleanup.

If schedule pressure occurs, priority is:

1. 3D-MOT scientific results.
2. Complete and safe 2D/3D campaign operation in the UI.
3. Validated configuration and data foundations.
4. Individual Zeeman runs.
5. Individual 2D/3D runs.
6. Local execution and additional polish.

## Change and approval policy

The team may commit and push after the relevant independent review and all
applicable tests pass. Escalation is required only for a scientific change, a
real Zeus action, a material UX decision, destructive data handling, or a team
disagreement that cannot be resolved from existing requirements and evidence.
