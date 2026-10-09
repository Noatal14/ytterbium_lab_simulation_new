import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const campaign = {
  id: "mot_2d-safe", family: "mot_2d", kind: "mot_2d_s0_campaign", name: "<sample campaign>",
  path: "data/optimization/mot_2d/sample", stage: "confirmation", stage_semantics: "prepared-workflow-stage",
  scheduler_status: "unchecked", trust: "trusted-current", scientific_role: "candidate-selection",
  progress: [{ stage: "screen", completed: 51, expected: 51, status: "complete" }, { stage: "confirmation", completed: 2, expected: 5, status: "in-progress" }],
  warnings: [{ severity: "info", message: "Scheduler state is not checked." }],
  next_plan: { label: "Review command", command: ["qsub", "data/job.pbs"], display_command: "qsub data/job.pbs", mode: "copy-only", scheduler_status: "unchecked", operation_scope: "remote-submission", executes_automatically: false },
  s0_values: [1.3], families: [], git_commit: "abc",
  remote_preparation: { status: "ready", reason_code: null },
};

test("campaign inspection stays read-only, accessible, and responsive", async ({ page }) => {
  await page.route("**/api/v1/campaigns", (route) => route.fulfill({ json: { api_version: 1, data: { campaigns: [campaign], invalid_count: 0, total: 1 } } }));
  await page.route("**/api/v1/campaigns/mot_2d-safe", (route) => route.fulfill({ json: { api_version: 1, data: campaign } }));
  await page.goto("/");
  await page.getByRole("button", { name: "Open campaign" }).click();
  await expect(page.getByRole("heading", { name: "<sample campaign>" })).toBeVisible();
  await expect(page.getByText(/does not mean a Zeus job is running/i)).toBeVisible();
  await expect(page.getByRole("button", { name: "Copy command" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)).toBe(false);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.getByRole("button", { name: /Back to campaigns/ }).click();
  await expect(page.getByRole("button", { name: "Open campaign" })).toBeFocused();
});

test("legacy campaigns remain inspectable but expose no Zeus command", async ({ page }) => {
  const legacyCampaign = {
    ...campaign,
    id: "mot_2d-legacy",
    name: "Legacy sample campaign",
    trust: "legacy-incomplete",
    scientific_role: "historical-evidence",
    next_plan: null,
    remote_preparation: { status: "legacy-local-only", reason_code: "absolute-input-paths" },
  };
  await page.route("**/api/v1/campaigns", (route) => route.fulfill({ json: { api_version: 1, data: { campaigns: [legacyCampaign], invalid_count: 0, total: 1 } } }));
  await page.route("**/api/v1/campaigns/mot_2d-legacy", (route) => route.fulfill({ json: { api_version: 1, data: legacyCampaign } }));
  await page.goto("/");
  await expect(page.getByText("Local-only campaign")).toBeVisible();
  await page.getByRole("button", { name: "Open campaign" }).click();
  await expect(page.getByRole("heading", { name: "Recreate this campaign before using Zeus" })).toBeVisible();
  await expect(page.getByText(/created with file locations tied to another computer/i)).toBeVisible();
  await expect(page.getByRole("heading", { name: "Campaign timeline" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Copy command" })).toHaveCount(0);
  await expect(page.getByText("qsub data/job.pbs")).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)).toBe(false);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.getByRole("button", { name: /Back to campaigns/ }).click();
  await expect(page.getByRole("button", { name: "Open campaign" })).toBeFocused();
});

test("operator reviews and confirms missing-only Zeus preparation", async ({ page }) => {
  const smoke = { ...campaign, stage: "smoke", git_commit: "b".repeat(40), next_plan: null };
  await page.route("**/api/v1/campaigns", (route) => route.fulfill({ json: { data: { campaigns: [smoke], invalid_count: 0, total: 1 } } }));
  await page.route("**/api/v1/campaigns/mot_2d-safe", (route) => route.fulfill({ json: { data: smoke } }));
  await page.route("**/api/v1/session", (route) => route.fulfill({ json: { data: { csrf_token: "csrf" } } }));
  await page.route("**/api/v1/zeus/snapshot", (route) => route.fulfill({ json: { data: {
    connection_status: "connected",
    profile: { host: "zeus.technion.ac.il", username: "tal.noa", project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", authentication: "ssh-key-or-agent" },
    remote: { project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", git_commit: "b".repeat(40), branch: "main", dirty: false },
    scheduler: { status: "available", queried_at: new Date().toISOString(), jobs: [] },
  } } }));
  await page.route("**/api/v1/zeus/transfers/preview", (route) => route.fulfill({ json: { data: {
    preview_token: "transfer-token", expires_in_seconds: 300,
    campaign: { id: smoke.id, name: smoke.name, path: smoke.path, git_commit: "b".repeat(40) },
    destination: { host: "zeus.technion.ac.il", project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", campaign_directory: "/home/tal.noa/ytterbium_lab_simulation_new/data/optimization/mot_2d/sample" },
    artifacts: { ensemble_count: 35, total_count: 72, missing_count: 12, identical_count: 60, total_bytes: 52_000_000, missing_bytes: 9_000_000 },
    effects: { copy_missing_only: true, overwrite_existing: false, submit_jobs: false, run_simulation: false },
  } } }));
  await page.route("**/api/v1/zeus/transfers/confirm", (route) => route.fulfill({ json: { data: {
    status: "prepared", campaign_id: smoke.id, destination: "/home/tal.noa/ytterbium_lab_simulation_new/data/optimization/mot_2d/sample", transferred_count: 12, reused_identical_count: 60, bytes_transferred: 9_000_000, submitted_to_zeus: false, simulation_started: false,
  } } }));
  await page.route("**/api/v1/zeus/submissions/smoke/preview", (route) => route.fulfill({ json: { data: {
    preview_token: "submission-token", expires_in_seconds: 300,
    campaign: { id: smoke.id, name: smoke.name, path: smoke.path, git_commit: "b".repeat(40), s0_values: [1.3] },
    stage: { id: "smoke", label: "Smoke check", purpose: "Validate the campaign setup with two-particle test runs" },
    job: { file: "jobs/01_smoke.pbs", kind: "job", task_count: 1, queue: "zeus_combined_q", cores_per_task: 1, memory_per_task_bytes: 68719476736, walltime_seconds: 1200 },
    remote: { host: "zeus.technion.ac.il", project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", commit: "b".repeat(40), branch: "main", dirty: false },
    inputs: { verified_count: 72, status: "ready" },
    effects: { submit_smoke: true, submit_later_stages: false, modify_files: false }, later_stages_locked: true,
  } } }));
  await page.route("**/api/v1/zeus/submissions/smoke/confirm", (route) => route.fulfill({ json: { data: {
    status: "submitted", campaign_id: smoke.id, stage: "smoke", job_id: "4759999.zeus-master", submitted_at: "2026-10-08T12:00:00Z", later_stages_locked: true,
  } } }));
  let statusChecks = 0;
  await page.route("**/api/v1/zeus/smoke/status", (route) => {
    statusChecks += 1;
    const running = statusChecks === 1;
    const prepared = statusChecks >= 3;
    return route.fulfill({ json: { data: { source: "zeus", queried_at: new Date().toISOString(), campaign: { id: smoke.id, name: smoke.name, stage: prepared ? "screen" : "smoke" }, submission: { job_id: "4759999.zeus-master" }, scheduler: { state: running ? "running" : "completed_success", raw_state: running ? "R" : "F", exit_status: running ? null : 0 }, validation: running ? { status: "not_ready", points: [], artifact_count: 0 } : { status: "valid", points: [{ s0: 1.3, captured: 0, input: 2, efficiency: 0 }], artifact_count: 3 }, lifecycle: running ? "running" : prepared ? "screen_prepared" : "ready_to_prepare_screen", next_action: running ? "wait" : prepared ? "none" : "review_screening_preparation" } } });
  });
  await page.route("**/api/v1/zeus/screening/preview", (route) => route.fulfill({ json: { data: { preview_token: "screen-token", expires_in_seconds: 300, campaign: { id: smoke.id, name: smoke.name, git_commit: "b".repeat(40) }, from_stage: "smoke", to_stage: "screen", smoke: { job_id: "4759999.zeus-master", points: [{ s0: 1.3, captured: 0, input: 2, efficiency: 0 }], artifact_count: 3 }, artifacts: { create: ["screen/tasks.json", "jobs/02_screen.pbs"], update: ["campaign.json"] }, effects: { prepare_screening: true, submit_screening: false, start_simulation: false, overwrite_existing: false }, local_sync: { status: "not_synchronized" } } } }));
  await page.route("**/api/v1/zeus/screening/confirm", (route) => route.fulfill({ json: { data: { status: "screening_prepared", campaign_id: smoke.id, stage: "screen", artifacts: { created: 2, updated: 1 }, submitted_to_zeus: false, simulation_started: false, local_sync: { status: "not_synchronized" } } } }));
  await page.route("**/api/v1/zeus/submissions/screening/preview", (route) => route.fulfill({ json: { data: { preview_token: "screen-submit-token", expires_in_seconds: 300, campaign: { id: smoke.id, name: smoke.name, git_commit: "b".repeat(40), s0_values: [1.3] }, stage: { id: "screen", label: "Screening", purpose: "Search broadly for promising settings." }, job: { file: "jobs/02_screen.pbs", kind: "array", task_count: 3, array_throttle: 3, queue: "zeus_combined_q", cores_per_task: 200, memory_per_task_bytes: 68719476736, walltime_seconds: 86400 }, remote: { host: "zeus.technion.ac.il", project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", commit: "b".repeat(40), branch: "main", dirty: false }, inputs: { verified_count: 72, status: "ready" }, smoke: { status: "validated", job_id: "4759999.zeus-master", point_count: 1 }, effects: { submit_screening: true, submit_later_stages: false, modify_files: false }, later_stages_locked: true } } }));
  await page.route("**/api/v1/zeus/submissions/screening/confirm", (route) => route.fulfill({ json: { data: { status: "submitted", campaign_id: smoke.id, stage: "screen", job_id: "4760000[].zeus-master", submitted_at: new Date().toISOString(), later_stages_locked: true } } }));
  const candidates = [1, 2, 3].map((rank, worker) => ({ s0: 1.3, rank, detuning_gamma: -0.9 - rank / 100, magnet_radius_m: 0.046 + rank / 100000, mean_conditional_efficiency: 0.02 + rank / 1000, source: `screen/s0_1p300000/worker${worker}/trials/trial_000${rank}.json` }));
  await page.route("**/api/v1/zeus/screen/status", (route) => route.fulfill({ json: { data: { source: "zeus", queried_at: new Date().toISOString(), campaign: { id: smoke.id, name: smoke.name, stage: "screen" }, submission: { job_id: "4760000[].zeus-master" }, scheduler: { state: "completed_success", raw_state: "F", exit_status: 0, task_count: 3, counts: { queued: 0, running: 0, held: 0, succeeded: 3, failed: 0 } }, validation: { status: "valid", completed_trials: 51, expected_trials: 51, candidate_count: 3 }, lifecycle: "ready_to_prepare_refinement", next_action: "review_refinement_preparation" } } }));
  await page.route("**/api/v1/zeus/refinement/preview", (route) => route.fulfill({ json: { data: { preview_token: "refine-token", expires_in_seconds: 300, campaign: { id: smoke.id, name: smoke.name, git_commit: "b".repeat(40), s0_values: [1.3] }, from_stage: "screen", to_stage: "refine", bounds: { detuning_gamma: { low: -3, high: -0.1 }, magnet_radius_m: { low: 0.03, high: 0.06 } }, screening: { job_id: "4760000[].zeus-master", completed_trials: 51, expected_trials: 51, candidates }, artifacts: { create: ["screening_candidates.json", "refine/tasks.json", "jobs/03_refine_round_01.pbs", "jobs/03_refine_round_02.pbs", "jobs/03_refine_round_03.pbs", "jobs/03_refine_round_04.pbs", "jobs/03_submit_refinement_chain.sh"], update: ["campaign.json"] }, effects: { prepare_refinement: true, submit_refinement: false, start_simulation: false, overwrite_existing: false }, local_sync: { status: "not_synchronized" } } } }));
  await page.route("**/api/v1/zeus/refinement/confirm", (route) => route.fulfill({ status: 201, json: { data: { status: "refinement_prepared", campaign_id: smoke.id, stage: "refine", artifacts: { created: 7, updated: 1 }, submitted_to_zeus: false, simulation_started: false, local_sync: { status: "not_synchronized" } } } }));
  const refineIds = ["4770001[].zeus-master", "4770002[].zeus-master", "4770003[].zeus-master", "4770004[].zeus-master"];
  await page.route("**/api/v1/zeus/submissions/refinement/status", (route) => route.fulfill({ json: { data: { source: "zeus", queried_at: new Date().toISOString(), campaign: { id: smoke.id, name: smoke.name, stage: "refine" }, chain: { status: "not_submitted", dependency: "afterok", rounds: [1, 2, 3, 4].map((round) => ({ round, state: "not_submitted", job_id: null, depends_on_job_id: null })) }, next_action: "review_submission", local_sync: { status: "not_synchronized" } } } }));
  await page.route("**/api/v1/zeus/submissions/refinement/preview", (route) => route.fulfill({ json: { data: { preview_token: "chain-token", expires_in_seconds: 300, campaign: { id: smoke.id, name: smoke.name, git_commit: "b".repeat(40), s0_values: [1.3] }, stage: { id: "refine", label: "Refinement" }, chain: { dependency: "afterok", rounds: [3, 6, 9, 10].map((target, index) => ({ round: index + 1, file: `jobs/03_refine_round_0${index + 1}.pbs`, cumulative_target: target, kind: "array", task_count: 3, array_throttle: 3, queue: "zeus_combined_q", cores_per_task: 200, memory_per_task_bytes: 68719476736, walltime_seconds: 72000, depends_on: index === 0 ? null : index })) }, remote: { host: "zeus.technion.ac.il", project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", commit: "b".repeat(40), branch: "main", dirty: false }, effects: { submit_refinement_chain: true, start_simulation: true, submit_later_stages: false, modify_files: false }, local_sync: { status: "not_synchronized" } } } }));
  await page.route("**/api/v1/zeus/submissions/refinement/confirm", (route) => route.fulfill({ json: { data: { status: "submitted", campaign_id: smoke.id, stage: "refine", chain: { status: "submitted", rounds: refineIds.map((job_id, index) => ({ round: index + 1, job_id, depends_on_job_id: index === 0 ? null : refineIds[index - 1] })) }, submitted_at: new Date().toISOString(), local_sync: { status: "not_synchronized" } } } }));
  const refineCandidates = [1, 2, 3, 4, 5].map((rank) => ({ s0: 1.3, rank, detuning_gamma: -0.9 - rank / 100, magnet_radius_m: 0.046 + rank / 100000, mean_conditional_efficiency: 0.02 + rank / 1000, source: `refine/s0_1p300000/worker${(rank - 1) % 3}/trials/trial_000${rank}.json` }));
  await page.route("**/api/v1/zeus/refinement-chain/status", (route) => route.fulfill({ json: { data: { source: "zeus", queried_at: new Date().toISOString(), campaign: { id: smoke.id, name: smoke.name, stage: "refine" }, chain: { status: "ready_to_prepare_confirmation", rounds: refineIds.map((job_id, index) => ({ round: index + 1, job_id, depends_on_job_id: index === 0 ? null : refineIds[index - 1], scheduler: { state: "completed_success", task_count: 3, counts: { queued: 0, running: 0, held: 0, succeeded: 3, failed: 0 } } })) }, validation: { status: "valid", completed_trials: 30, expected_trials: 30, candidate_count: 5 }, next_action: "review_confirmation_preparation", local_sync: { status: "not_synchronized" } } } }));
  await page.route("**/api/v1/zeus/confirmation/preview", (route) => route.fulfill({ json: { data: { preview_token: "confirmation-token", expires_in_seconds: 300, campaign: { id: smoke.id, name: smoke.name, git_commit: "b".repeat(40), s0_values: [1.3] }, from_stage: "refine", to_stage: "confirmation", bounds: { detuning_gamma: { low: -3, high: -0.1 }, magnet_radius_m: { low: 0.03, high: 0.06 } }, refinement: { round_job_ids: refineIds, completed_trials: 30, expected_trials: 30, candidates: refineCandidates }, artifacts: { create: ["refined_candidates.json", "confirmation/tasks.json", "jobs/04_confirmation.pbs"], update: ["campaign.json"] }, job: { file: "jobs/04_confirmation.pbs", kind: "array", task_count: 5, array_throttle: 3, queue: "zeus_combined_q", cores_per_task: 200, memory_per_task_bytes: 68719476736, walltime_seconds: 36000 }, effects: { prepare_confirmation: true, submit_confirmation: false, start_simulation: false, overwrite_existing: false }, local_sync: { status: "not_synchronized" } } } }));
  await page.route("**/api/v1/zeus/confirmation/confirm", (route) => route.fulfill({ status: 201, json: { data: { status: "confirmation_prepared", campaign_id: smoke.id, stage: "confirmation", artifacts: { created: 3, updated: 1 }, submitted_to_zeus: false, simulation_started: false, local_sync: { status: "not_synchronized" } } } }));
  await page.goto("/");
  await page.getByRole("link", { name: "Zeus jobs" }).click();
  await page.getByLabel("Technion username").fill("tal.noa");
  await page.getByRole("button", { name: "Connect and check status" }).click();
  await expect(page.getByText("Connected — read-only snapshot received")).toBeVisible();
  await page.getByRole("button", { name: "Inspect campaign" }).click();
  await page.getByRole("button", { name: "Review Zeus preparation" }).click();
  await expect(page.getByText("12 · 9 MB")).toBeVisible();
  await expect(page.getByText("No Zeus job will be submitted.")).toBeVisible();
  await page.getByRole("button", { name: "Prepare campaign on Zeus" }).click();
  await expect(page.getByText("Campaign prepared on Zeus")).toBeVisible();
  await expect(page.getByText("No simulation was started and no Zeus job was submitted.")).toBeVisible();
  await page.getByRole("button", { name: "Review smoke submission" }).click();
  await expect(page.getByRole("heading", { name: "Submit smoke check to Zeus" })).toBeFocused();
  await expect(page.getByText("1 CPU core · 64 GB memory")).toBeVisible();
  await page.getByRole("button", { name: "Submit smoke check to Zeus" }).click();
  await expect(page.getByRole("heading", { name: "No action needed" })).toBeVisible();
  await expect(page.getByText("Smoke check submitted", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "View in Zeus jobs" })).toBeVisible();
  await page.getByRole("button", { name: "Check smoke status" }).click();
  await expect(page.getByRole("heading", { name: "No action needed" })).toBeVisible();
  await expect(page.getByText(/safely close this application/i)).toBeVisible();
  await page.getByRole("button", { name: "Refresh smoke status" }).click();
  await expect(page.getByRole("heading", { name: "Action required" })).toBeVisible();
  await expect(page.getByText(/zero-capture smoke point is valid/i)).toBeVisible();
  await page.getByRole("button", { name: "Review screening preparation" }).click();
  await expect(page.getByRole("heading", { name: "Prepare Screening on Zeus" })).toBeFocused();
  await page.getByRole("button", { name: "Prepare Screening on Zeus" }).click();
  await expect(page.getByText("Screening prepared on Zeus")).toBeVisible();
  await expect(page.getByText(/No Screening job was submitted/)).toBeVisible();
  await page.getByRole("button", { name: "Refresh Zeus status" }).click();
  await page.getByRole("button", { name: "Review Screening submission" }).click();
  await expect(page.getByRole("heading", { name: "Submit Screening to Zeus" })).toBeFocused();
  await expect(page.getByText("At most 3 tasks at once")).toBeVisible();
  await expect(page.getByText(/exactly one/)).toBeVisible();
  await page.getByRole("button", { name: "Submit Screening to Zeus" }).click();
  await expect(page.getByText("4760000[].zeus-master").first()).toBeVisible();
  await expect(page.getByText(/safe to close this application/i)).toBeVisible();
  await page.getByRole("button", { name: "Check Screening status" }).click();
  await expect(page.getByRole("heading", { name: "Action required" })).toBeVisible();
  await expect(page.getByText(/3 candidates were selected/)).toBeVisible();
  await page.getByRole("button", { name: "Review Refinement preparation" }).click();
  await expect(page.getByRole("heading", { name: "Prepare Refinement on Zeus" })).toBeFocused();
  await expect(page.getByText(/Screening estimates, not final performance/)).toBeVisible();
  await expect(page.getByText("jobs/03_submit_refinement_chain.sh")).toBeVisible();
  await page.getByRole("button", { name: "Prepare Refinement on Zeus" }).click();
  await expect(page.getByText("Refinement prepared on Zeus")).toBeVisible();
  await expect(page.getByText(/No Refinement job was submitted/)).toBeVisible();
  await page.getByRole("button", { name: "Check chain status" }).click();
  await page.getByRole("button", { name: "Review Refinement submission" }).click();
  await expect(page.getByRole("heading", { name: "Submit four-round Refinement chain" })).toBeFocused();
  await expect(page.getByText(/exactly four/)).toBeVisible();
  await expect(page.getByText(/cumulative target 10/)).toBeVisible();
  await page.getByRole("button", { name: "Submit four Refinement rounds" }).click();
  for (const id of refineIds) await expect(page.getByText(id).first()).toBeVisible();
  await expect(page.getByText(/safe to close this application/i)).toBeVisible();
  await page.getByRole("button", { name: "Check Refinement status" }).click();
  await expect(page.getByText(/5 candidates are ready/)).toBeVisible();
  await page.getByRole("button", { name: "Review Confirmation preparation" }).click();
  await expect(page.getByRole("heading", { name: "Prepare Confirmation on Zeus" })).toBeFocused();
  await expect(page.getByText(/selection estimates, not final sealed performance/)).toBeVisible();
  await expect(page.getByText("jobs/04_confirmation.pbs").first()).toBeVisible();
  await page.getByRole("button", { name: "Prepare Confirmation on Zeus" }).click();
  await expect(page.getByText("Confirmation prepared on Zeus")).toBeVisible();
  await expect(page.getByText(/No Confirmation job was submitted/)).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)).toBe(false);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});
