# Simulation control center: product plan

## Product goal

The application is a self-service tool for any researcher who needs to run or
inspect the simulation campaigns. It must not assume that the
operator knows the repository, campaign lifecycle, Zeus, or the history of the
current project. Within five seconds, the application should explain:

- what has completed;
- what is currently running;
- whether anything failed or needs attention;
- what scientific evidence is available; and
- what the next safe action is.

The interface is for operating reproducible 2D- and 3D-MOT campaigns without
requiring routine terminal work. It should expose technical detail when useful,
but its default language must be clear to a researcher who does not maintain
the code.

## Safety principles

- The UI consumes `workflow_api`; it does not import simulation workers.
- Opening or refreshing a page must never run a simulation or submit a job.
- Every state-changing action is previewed and explicitly confirmed.
- An action is unavailable when required inputs or artifacts are missing,
  untrusted, incomplete, or inconsistent.
- Candidate-selection results and sealed final-validation results are always
  labeled distinctly.
- Credentials are never stored in source, manifests, ordinary configuration,
  or logs. Future Zeus access will use SSH or operating-system facilities.
- The active repository path, branch, commit, campaign commit, and remote host
  must remain visible and distinguishable.

## Proposed information architecture

### Home dashboard

The home page should show:

- local project connection, branch, commit, and compatibility status;
- Zeus connection and scheduler status;
- one large 2D-MOT campaign card;
- one large 3D-MOT campaign card;
- active or queued Zeus jobs;
- warnings and decisions requiring attention; and
- a prominent **Current priority** panel.

Each campaign card should include its name, current stage, progress, most useful
current result, warning count, and an `Open campaign` action. If the 3D campaign
cannot yet exist, the card should explain which upstream 2D requirement is
missing instead of offering an invalid action.

When no campaign is active, the home page becomes an onboarding page rather
than an empty dashboard. It should:

- explain that a campaign has several ordered stages and that the application
  guides the operator through them;
- show the current Git branch and whether it is up to date, plus whether Zeus
  access is configured;
- offer `Start 2D-MOT campaign` as the normal first step;
- show `Start 3D-MOT campaign` as unavailable until a completed canonical 2D
  campaign is selected;
- allow the operator to open an existing campaign directory; and
- explain the four-part lifecycle: configure, review, run on Zeus, inspect.

The interface language is English. Scientific symbols and established code
terms should remain unchanged rather than translated or paraphrased.

### Campaign detail

The campaign page should present the lifecycle as a stage timeline. Suggested
visual states are:

- gray: not started;
- blue: ready;
- yellow: running;
- green: complete and validated;
- red: blocked or failed; and
- purple: awaiting a scientific decision.

A selected stage should explain its scientific purpose, expected and completed
tasks, particle/ensemble/seed design, numerical method, timing, artifacts,
success criteria, and allowed next transition.

### Current priority and next safe action

The central panel changes meaning with campaign state:

- while work is running, it says **No action needed**, names the running stage,
  and tells the operator that the application is waiting for validated outputs;
- when a safe transition is ready, it says **Ready for next step** and presents
  the next action;
- when input or a scientific decision is required, it says **Action required**;
  and
- when continuation is unsafe, it says **Blocked** and gives the recovery path.

This avoids presenting monitoring as an action. When an action is available,
the panel should explain:

- what is ready;
- why the action is allowed;
- what will change;
- the exact underlying command;
- which files or jobs will be created;
- whether the action is local or remote; and
- whether it can be reversed.

The first UI version will be read-only and offer `Copy command`. Execution and
Zeus submission will be added only behind a separate confirmation boundary.

### Results

Results should include leading candidates, intervals, sensitivity, boundary
flags, geometry comparison, graphs, and artifact links. Every result must carry
one of these scientific roles:

- candidate selection;
- sealed final validation; or
- historical evidence.

The UI must not visually promote a selection result into a final unbiased
performance claim.

### Zeus

Zeus jobs belong on a dedicated page rather than the home dashboard. The first
Zeus view will be read-only and show connection state, job IDs,
dependency chains, queue states, runtime, and log locations. Scheduler codes
such as `H`, `Q`, `R`, `F`, and `X` should have plain-language explanations.

Later versions may support secure connection, submission after confirmation,
refresh, completion detection, summary retrieval, and transition back to the
next-action panel.

### Campaign creation

Campaign creation should use a short wizard rather than one large form.

For 2D MOT:

1. choose a validated Zeeman ensemble source;
2. enter one or more fixed `s0` values;
3. inspect the frozen scientific design;
4. validate files, hashes, seeds, and provenance; and
5. create without automatically submitting.

For 3D MOT:

1. choose a completed canonical 2D campaign;
2. choose its survivor-state directory;
3. validate the handoff;
4. inspect both geometries and their bounds;
5. inspect timestep-validation status; and
6. create without automatically submitting.

Before allowing a duplicate run, the UI should detect campaigns using the same
Zeeman ensemble source and fixed `s0` value, then direct the operator to inspect
the existing campaign. The product must treat the currently valid Zeeman array
as the normal source of truth; historical invalid arrays and the fact that they
were corrected are not part of the normal user-facing workflow.

After successful creation, show an explicit local-success state. It should
confirm that the campaign record and workspace were created and validated,
state clearly that no Zeus work has been submitted, provide access to the
campaign directory and record, and identify Zeus connection as the next step
when no connection is configured. The newly created campaign must remain safe
to close and resume later.

Before the first run, guide the operator through a reusable Zeus connection
profile. Prefer an existing SSH key or SSH agent, never store a Zeus password,
and store only non-secret host, username, and path settings when requested. A
connection test must verify SSH access, the remote project directory, the
Python environment, and the expected code version without submitting jobs.
Only a successful test unlocks the run-review screen.

Explain the difference between key/agent and password authentication through
on-demand help. Derive the normal remote project path from the Technion
username automatically, while keeping that path editable for non-standard
checkouts.

Every Zeus submission requires a final run-review screen. It must name the
single stage being submitted, explain its purpose, show the requested jobs,
cores, memory, walltime, queue, and remote code status, and state
whether later stages remain locked. A confirmation for a smoke check submits
only that smoke check; successful completion should return the operator to the
campaign page where the next safe stage can be reviewed separately.

After submission, the campaign page becomes the primary status surface. When a
job is queued or running, lead with `No action needed`, show the current stage
and a compact scheduler summary, and keep full job details on the separate Zeus
jobs page. The page should make it safe to close the application and should not
offer the next stage until the current output has been validated.

## Warning language

Use only three user-facing severities:

- **Info**: useful context;
- **Attention**: a check or decision is required; and
- **Blocked**: continuing is unsafe or impossible.

Every warning should say what was found, why it matters, what the user should do,
and whether the UI can help. Tracebacks and raw scheduler output belong behind a
`Show technical details` control.

Keep review screens concise by placing long scientific explanations behind
clearly labeled help controls. Help must work with hover, keyboard focus, and
touch. In particular, explain solver behavior, the purpose of each timestep,
input freezing, recorded code and physics provenance, and sealed evaluation
without requiring those paragraphs to remain permanently visible.

## Initial technical direction

Start as a local web application:

- it opens in a browser;
- it runs only on the researcher's computer;
- it reads the local repository and campaign artifacts;
- it uses the side-effect-free `workflow_api`; and
- a later local backend may connect to Zeus.

The approved implementation direction is a React and TypeScript application
built with Vite. A small local Python service exposes versioned, serializable
responses from `workflow_api`; it does not import simulation workers or submit
jobs. UI dependencies remain isolated from the scientific Python runtime.

The approved campaign-creation, Zeus-connection, run-review, and running-state
screens describe the intended product. Their approval does not move them into
the first implementation milestone or authorize remote execution.

## Delivery sequence

1. Build the application shell and approved no-active-campaign home using
   representative fixtures. This milestone is read-only and local.
2. Connect campaign discovery and inspection to the side-effect-free
   `workflow_api`, then validate against real 2D and 3D manifests.
3. Add the approved campaign-creation workflow behind a separate local
   mutation boundary. Creation must still never submit work automatically.
4. Add secure Zeus connection testing and a read-only jobs page.
5. Add explicitly confirmed stage submission only after a dedicated safety and
   scientific review.

Each phase requires its own tests and review. Approval of a later screen is a
product decision, not permission for an earlier implementation milestone to
perform that action.

## Milestone 1 implementation scope

Include:

- the English application shell and navigation;
- the approved no-active-campaign onboarding home;
- responsive layouts for desktop, split-screen, tablet, and mobile;
- accessible semantic structure and status messaging;
- representative fixture data; and
- a minimal local API bridge that reads only from `workflow_api`.

Do not yet include:

- campaign discovery or inspection from arbitrary local paths;
- Zeus credentials, SSH, scheduler queries, or submission;
- parameter editing;
- campaign creation;
- complex scientific plotting;
- background monitoring; or
- mutation of campaign files.

## Milestone 2 implementation scope

Milestone 2 discovers campaign records only from the repository's fixed
`data/optimization/mot_2d` and `data/optimization/mot_3d` roots. The service
issues opaque campaign identifiers; the browser never supplies an arbitrary
filesystem path. Campaign detail shows validated local-output progress, the
prepared workflow stage, scientific evidence role, trust warnings, and—only
when the record passes conservative checks—a command that can be copied for
manual review.

The prepared stage is not scheduler state. This milestone must always describe
Zeus status as unchecked and must not call a scheduler, infer that a job is
running, or execute a displayed command. Legacy, incomplete, malformed, or
inconsistent records fail closed and never receive a continuation action.
Candidate-selection evidence is kept distinct from sealed final validation.

Campaign creation and the already approved creation screens remain Milestone 3.
This milestone adds no write endpoint, subprocess, SSH, Zeus connection, job
submission, arbitrary directory picker, or background monitoring.

## Approval log

- Product goal, safety direction, proposed screens, and delivery sequence were
  approved for detailed home-dashboard design on 2026-10-08.
- The no-active-campaign home, 2D creation wizard designs, Zeus connection
  design, run review, and running campaign design were approved as product
  direction on 2026-10-08. Milestone 1 remains fixture-only and read-only.
- Milestone 2 is read-only discovery and inspection. Approved creation and
  execution designs remain later phases and do not authorize mutation.
