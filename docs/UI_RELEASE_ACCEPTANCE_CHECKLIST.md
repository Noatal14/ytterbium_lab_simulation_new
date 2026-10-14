# UI release acceptance checklist

This checklist is the release gate for the simulation control center. A checked
item records observed evidence; it is not a prediction that the flow should
work. Do not perform the Zeus section while another production campaign owns
the pinned Zeus checkout.

## A. Local release candidate

- [ ] Start from a clean checkout using `UI_QUICKSTART.md` only.
- [ ] Confirm that the workflow API and browser UI start together.
- [ ] Confirm that Home offers individual Zeeman, 2D-MOT, and 3D-MOT runs and
      2D-MOT and 3D-MOT campaigns.
- [ ] Confirm the layout at narrow laptop, full-screen laptop, and wide desktop
      widths without clipped controls or horizontal overflow.
- [ ] Confirm keyboard navigation, visible focus, help popovers, Back, browser
      reload, and recovery of an active run.

## B. Individual simulations on this computer

For every run, inspect the review before starting, verify numerical progress,
wait for completion, and open Results.

- [ ] Zeeman without retained particle states.
- [ ] Zeeman with retained particle states and a discoverable saved source.
- [ ] 2D MOT from a verified Zeeman source, without retained particle states.
- [ ] 2D MOT from a verified Zeeman source, with retained particle states.
- [ ] Angled-donut 3D MOT from a verified 2D-MOT source.
- [ ] Single-pass 3D MOT from a verified 2D-MOT source.
- [ ] Invalid values and missing sources produce useful messages beside the
      action that needs correction.
- [ ] Double-clicking, leaving the page, and refreshing never start duplicate
      work.

## C. Zeus connection and individual canaries

- [ ] First-time connection guidance clearly identifies the official Technion
      account prerequisite and explains the in-application SSH setup.
- [ ] A valid SSH-key connection returns a read-only job snapshot.
- [ ] VPN, authentication, missing-project, timeout, and stale-status failures
      produce distinct and actionable messages.
- [ ] Submit one small Zeeman job through review and explicit confirmation.
- [ ] Submit one small 2D-MOT job through review and explicit confirmation.
- [ ] Submit one small 3D-MOT job through review and explicit confirmation.
- [ ] For each job, verify queued/running/completed states, scientific output
      validation, Results, and retained-state behavior.
- [ ] An uncertain submission cannot be retried until Zeus is inspected.

## D. Campaign acceptance

Use new disposable acceptance campaigns. Never repurpose or modify a completed
scientific campaign.

- [ ] Create a 2D-MOT campaign and verify its frozen inputs and duplicate-run
      warning.
- [ ] Prepare it on Zeus and submit its first reviewed job through the UI.
- [ ] Verify the UI can represent and safely continue every later 2D stage:
      smoke, screening, refinement, confirmation, sensitivity, production, and
      finalization.
- [ ] Create a 3D-MOT campaign from a validated 2D source.
- [ ] Prepare it on Zeus and submit its first reviewed job through the UI.
- [ ] Verify the UI can represent and safely continue every later 3D stage:
      discovery, preliminary check, refinement, closure, finalist selection,
      final-input generation, final validation, and completion or extension.
- [ ] Verify a scheduler success never bypasses scientific artifact validation.
- [ ] Verify failed, incomplete, held, stale, and ambiguous stages cannot expose
      an unsafe next action.

## E. Automated gates

- [ ] `python -m pytest -q`
- [ ] `python scripts/generate_workflow_error_catalog.py --check`
- [ ] `python scripts/generate_ui_error_catalog.py --check`
- [ ] `npm run lint`
- [ ] `npm run format:check`
- [ ] `npm test`
- [ ] `npm run build`
- [ ] `npm run test:e2e`
- [ ] `git diff --check`

Record the tested commit, operating system, browser, date, Zeus campaign/run
identifiers, and any accepted limitation next to the release evidence.

## F. Release

- [ ] Zero known release-blocking or high-severity defects remain.
- [ ] Every accepted limitation is documented and does not risk duplicate work,
      invalid scientific interpretation, or loss of results.
- [ ] Merge the reviewed release candidate into `main`.
- [ ] Repeat sections A and E from the resulting `main` commit.
- [ ] Tag the submitted version and record the tag in `PROJECT_HANDOFF.md`.
- [ ] Back up the canonical 2D- and 3D-MOT results outside the working checkout.
