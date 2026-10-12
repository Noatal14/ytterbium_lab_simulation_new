import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const id = "mot_3d-safe";
const campaign = {
  id, family: "mot_3d", kind: "mot_3d_campaign_v2", name: "Canonical 3D campaign",
  path: "data/optimization/mot_3d/canonical", stage: "discovery", stage_semantics: "prepared-workflow-stage",
  scheduler_status: "unchecked", trust: "trusted-current", scientific_role: "candidate-selection",
  progress: [{ stage: "discovery", completed: 950, expected: 950, status: "complete" }], warnings: [], next_plan: null,
  s0_values: [], families: ["angled_donut", "single_pass"], git_commit: "a".repeat(40),
  remote_preparation: { status: "ready", reason_code: null },
};
const profile = { host: "zeus.technion.ac.il", username: "tal.noa", project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", authentication: "ssh-key-or-agent" };
const chain = { angled_donut: ["100[].zeus-master", "101[].zeus-master"], single_pass: ["200[].zeus-master", "201[].zeus-master", "202[].zeus-master"] };

test("verified Discovery synchronization is explicit, accessible, and responsive", async ({ page }) => {
  await page.route("**/api/v1/campaigns", (route) => route.fulfill({ json: { api_version: 1, data: { campaigns: [campaign], invalid_count: 0, total: 1 } } }));
  await page.route(`**/api/v1/campaigns/${id}`, (route) => route.fulfill({ json: { api_version: 1, data: campaign } }));
  await page.route("**/api/v1/session", (route) => route.fulfill({ json: { api_version: 1, data: { csrf_token: "csrf" } } }));
  await page.route("**/api/v1/zeus/snapshot", (route) => route.fulfill({
    json: { api_version: 1, data: {
      connection_status: "connected", profile,
      remote: { project_directory: profile.project_directory, git_commit: "a".repeat(40), branch: "main", dirty: false },
      scheduler: { status: "available", queried_at: "2026-10-12T10:00:00Z", jobs: [] },
    } },
  }));
  await page.route("**/api/v1/zeus/submissions/mot-3d-discovery/status", (route) => route.fulfill({ json: { api_version: 1, data: { source: "zeus", queried_at: "2026-10-12T10:00:00Z", campaign: { id, name: campaign.name, stage: "discovery" }, submission: { status: "completed_success", chain }, next_action: "validate_outputs", local_sync: { status: "not_synchronized" } } } }));
  await page.route("**/api/v1/zeus/mot-3d/discovery-transition/status", (route) => route.fulfill({ json: { api_version: 1, data: { source: "zeus", queried_at: "2026-10-12T10:00:00Z", campaign: { id, name: campaign.name, stage: "discovery" }, discovery: { status: "ready_to_advance", chain }, validation: { status: "valid", completed_trials: 950, expected_trials: 950 }, next_action: "review_transition", local_sync: { status: "not_synchronized", receipt_sha256: null } } } }));
  await page.route("**/api/v1/zeus/mot-3d/discovery-transition/preview", (route) => route.fulfill({ json: { api_version: 1, data: { preview_token: "token", expires_in_seconds: 300, campaign: { id, name: campaign.name, git_commit: "a".repeat(40) }, from_stage: "discovery", to_stage: "preliminary_check", discovery: { completed_trials: 950, expected_trials: 950, families: ["angled_donut", "single_pass"], evidence_sha256: "b".repeat(64) }, artifacts: { synchronize: { trial_registries: 950, merged_files: 4 }, create: { selection_files: 2, job_files: 4 }, update: ["campaign.json"] }, effects: { synchronize_discovery: true, prepare_preliminary_check: true, submit_preliminary_check: false, start_simulation: false, overwrite_existing: false } } } }));
  await page.route("**/api/v1/zeus/mot-3d/discovery-transition/confirm", (route) => route.fulfill({ status: 201, json: { api_version: 1, data: { status: "preliminary_check_prepared", campaign_id: id, stage: "preliminary_check", artifacts: { synchronized: 954, created: 6, updated: 1, bundle_sha256: "c".repeat(64) }, submitted_to_zeus: false, simulation_started: false, local_sync: { status: "synchronized", receipt_sha256: "d".repeat(64) } } } }));

  await page.goto("/");
  await page.getByRole("link", { name: "Zeus jobs" }).click();
  await page.getByLabel("Technion username").fill("tal.noa");
  await page.getByRole("button", { name: "Connect and check status" }).click();
  await page.getByRole("button", { name: "Inspect campaign" }).click();
  await page.getByRole("button", { name: "Check Zeus status" }).click();
  await page.getByRole("button", { name: "Verify Discovery results" }).click();
  await expect(page.getByRole("heading", { name: "Action required" })).toBeVisible();
  await page.getByRole("button", { name: "Review synchronization" }).click();
  await expect(page.getByRole("heading", { name: "Synchronize verified Discovery evidence" })).toBeFocused();
  await expect(page.getByText(/does not submit a Zeus job or start a simulation/i)).toBeVisible();
  await page.getByRole("button", { name: "Synchronize and prepare" }).click();
  await expect(page.getByText("Preliminary check is prepared").first()).toBeVisible();
  await expect(page.getByText(/No preliminary-check job has been submitted or started/i)).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)).toBe(false);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});

test("preliminary-check submission is explicit and scheduler completion stays unvalidated", async ({ page }) => {
  const preliminaryCampaign = { ...campaign, stage: "preliminary_check", progress: [{ stage: "discovery", completed: 950, expected: 950, status: "complete" }, { stage: "preliminary_check", completed: 0, expected: 72, status: "not-started" }] };
  const empty = { dependency: "afterok within each family", families: [{ id: "angled_donut", array_job_id: null, merge_job_id: null }, { id: "single_pass", array_job_id: null, merge_job_id: null }] };
  const submitted = { dependency: "afterok within each family", families: [{ id: "angled_donut", array_job_id: "300[].zeus-master", merge_job_id: "301.zeus-master" }, { id: "single_pass", array_job_id: "400[].zeus-master", merge_job_id: "401.zeus-master" }] };
  await page.route("**/api/v1/campaigns", (route) => route.fulfill({ json: { api_version: 1, data: { campaigns: [preliminaryCampaign], invalid_count: 0, total: 1 } } }));
  await page.route(`**/api/v1/campaigns/${id}`, (route) => route.fulfill({ json: { api_version: 1, data: preliminaryCampaign } }));
  await page.route("**/api/v1/session", (route) => route.fulfill({ json: { api_version: 1, data: { csrf_token: "csrf" } } }));
  await page.route("**/api/v1/zeus/snapshot", (route) => route.fulfill({
    json: { api_version: 1, data: {
      connection_status: "connected", profile,
      remote: { project_directory: profile.project_directory, git_commit: "a".repeat(40), branch: "main", dirty: false },
      scheduler: { status: "available", queried_at: "2026-10-12T10:00:00Z", jobs: [] },
    } },
  }));
  await page.route("**/api/v1/zeus/submissions/mot-3d-preliminary-check/status", (route) => route.fulfill({ json: { api_version: 1, data: { source: "zeus", queried_at: "2026-10-12T10:00:00Z", campaign: { id, name: campaign.name, stage: "preliminary_check" }, submission: { status: "not_submitted", chain: empty }, scheduler: { expected_array_tasks: 6, expected_merge_jobs: 2, completed_array_tasks: 0, completed_merge_jobs: 0 }, validation: { status: "not_started", expected_candidates_per_family: 12, expected_recoil_seeds_per_candidate: 3 }, next_action: "review_submission", local_sync: { status: "not_synchronized" } } } }));
  await page.route("**/api/v1/zeus/submissions/mot-3d-preliminary-check/preview", (route) => route.fulfill({ json: { api_version: 1, data: { preview_token: "preliminary-token", expires_in_seconds: 300, campaign: { id, name: campaign.name, git_commit: "a".repeat(40) }, stage: { id: "preliminary_check", label: "Preliminary check" }, chain: { families: [{ id: "angled_donut", array_tasks: 3, merge_jobs: 1 }, { id: "single_pass", array_tasks: 3, merge_jobs: 1 }], qsub_calls: 4, dependency: "afterok within each family" }, resources: { array: { ncpus_per_task: 200, memory_gb_per_task: 64, walltime: "24:00:00" }, merge: { ncpus: 1, memory_gb: 4, walltime: "01:00:00" } }, science: { classification: "candidate_selection_not_final_validation", candidates_per_family: 12, input_ensembles: 4, particles_per_ensemble: 150, total_particles: 600, recoil_seeds: [41001, 41002, 41003], dt_s: 1e-5, t_max_s: 0.1, solver: "RK4StHybridCustom", selection_seed: 51001, bootstrap_replicates: 10000, bootstrap_seed: 52001 }, remote: { host: profile.host, project_directory: profile.project_directory, commit: "a".repeat(40), branch: "main", dirty: false }, effects: { submit_preliminary_check: true, start_simulation: true, submit_later_stages: false, modify_campaign_files: false, record_submission_receipt: true } } } }));
  await page.route("**/api/v1/zeus/submissions/mot-3d-preliminary-check/confirm", (route) => route.fulfill({ status: 201, json: { api_version: 1, data: { status: "submitted", campaign_id: id, stage: "preliminary_check", chain: submitted, submitted_at: "2026-10-12T10:01:00Z", local_sync: { status: "not_synchronized" } } } }));
  await page.goto("/"); await page.getByRole("link", { name: "Zeus jobs" }).click(); await page.getByLabel("Technion username").fill("tal.noa"); await page.getByRole("button", { name: "Connect and check status" }).click(); await page.getByRole("button", { name: "Inspect campaign" }).click();
  await page.getByRole("button", { name: "Check Zeus status" }).click(); await page.getByRole("button", { name: "Review preliminary-check jobs" }).click();
  await expect(page.getByRole("heading", { name: "Submit the preliminary check" })).toBeFocused(); await expect(page.getByText("4 jobs total")).toBeVisible(); await page.getByRole("button", { name: "Submit preliminary check to Zeus" }).click(); await expect(page.getByText("Preliminary check is running on Zeus")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)).toBe(false); expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});

test("scientific validation and Refinement preparation remain explicit and submit no job", async ({ page }) => {
  const preliminaryCampaign = { ...campaign, stage: "preliminary_check", progress: [{ stage: "discovery", completed: 950, expected: 950, status: "complete" }, { stage: "preliminary_check", completed: 72, expected: 72, status: "complete" }] };
  const submitted = { dependency: "afterok within each family", families: [{ id: "angled_donut", array_job_id: "300[].zeus-master", merge_job_id: "301.zeus-master" }, { id: "single_pass", array_job_id: "400[].zeus-master", merge_job_id: "401.zeus-master" }] };
  await page.route("**/api/v1/campaigns", (route) => route.fulfill({ json: { api_version: 1, data: { campaigns: [preliminaryCampaign], invalid_count: 0, total: 1 } } }));
  await page.route(`**/api/v1/campaigns/${id}`, (route) => route.fulfill({ json: { api_version: 1, data: preliminaryCampaign } }));
  await page.route("**/api/v1/session", (route) => route.fulfill({ json: { api_version: 1, data: { csrf_token: "csrf" } } }));
  await page.route("**/api/v1/zeus/snapshot", (route) => route.fulfill({ json: { api_version: 1, data: { connection_status: "connected", profile, remote: { project_directory: profile.project_directory, git_commit: "a".repeat(40), branch: "main", dirty: false }, scheduler: { status: "available", queried_at: "2026-10-12T10:00:00Z", jobs: [] } } } }));
  await page.route("**/api/v1/zeus/submissions/mot-3d-preliminary-check/status", (route) => route.fulfill({ json: { api_version: 1, data: { source: "zeus", queried_at: "2026-10-12T10:00:00Z", campaign: { id, name: campaign.name, stage: "preliminary_check" }, submission: { status: "completed_success_unvalidated", chain: submitted }, scheduler: { expected_array_tasks: 6, expected_merge_jobs: 2, completed_array_tasks: 6, completed_merge_jobs: 2 }, validation: { status: "not_started", expected_candidates_per_family: 12, expected_recoil_seeds_per_candidate: 3 }, next_action: "validate_outputs", local_sync: { status: "not_synchronized" } } } }));
  await page.route("**/api/v1/zeus/mot-3d/preliminary-transition/status", (route) => route.fulfill({ json: { api_version: 1, data: { source: "zeus", queried_at: "2026-10-12T10:02:00Z", campaign: { id, name: campaign.name, stage: "preliminary_check" }, preliminary: { status: "ready_to_advance", chain: submitted }, scheduler: { expected_array_tasks: 6, expected_merge_jobs: 2, completed_array_tasks: 6, completed_merge_jobs: 2 }, validation: { status: "valid", result_artifacts: 152, expected_result_artifacts: 152, reason_code: null }, transition: { status: "not_prepared" }, next_action: "review_transition", local_sync: { status: "not_synchronized", receipt_sha256: null } } } }));
  await page.route("**/api/v1/zeus/mot-3d/preliminary-transition/preview", (route) => route.fulfill({ json: { api_version: 1, data: { preview_token: "transition-token", expires_in_seconds: 300, campaign: { id, name: campaign.name, git_commit: "a".repeat(40) }, from_stage: "preliminary_check", to_stage: "refinement", preliminary: { result_artifacts: 152, expected_result_artifacts: 152, families: ["angled_donut", "single_pass"], evidence_sha256: "b".repeat(64) }, artifacts: { synchronize: { result_files: 152, submission_receipts: 1 }, create: { selection_files: 2, job_files: 4 }, update: ["campaign.json"], transfer_files: 160 }, effects: { synchronize_preliminary_check: true, prepare_refinement: true, submit_refinement: false, start_simulation: false, overwrite_existing: false } } } }));
  await page.route("**/api/v1/zeus/mot-3d/preliminary-transition/confirm", (route) => route.fulfill({ status: 201, json: { api_version: 1, data: { status: "refinement_prepared", campaign_id: id, stage: "refinement", artifacts: { synchronized: 153, created: 6, updated: 1, bundle_sha256: "c".repeat(64) }, submitted_to_zeus: false, simulation_started: false, local_sync: { status: "synchronized", receipt_sha256: "d".repeat(64) } } } }));
  await page.goto("/"); await page.getByRole("link", { name: "Zeus jobs" }).click(); await page.getByLabel("Technion username").fill("tal.noa"); await page.getByRole("button", { name: "Connect and check status" }).click(); await page.getByRole("button", { name: "Inspect campaign" }).click();
  await page.getByRole("button", { name: "Check Zeus status" }).click(); await page.getByRole("button", { name: "Verify preliminary-check results" }).click(); await page.getByRole("button", { name: "Review synchronization" }).click();
  await expect(page.getByRole("heading", { name: "Synchronize results and prepare Refinement" })).toBeFocused(); await expect(page.getByText(/does not submit a job or start a simulation/i)).toBeVisible(); await page.getByRole("button", { name: "Synchronize and prepare Refinement" }).click(); await expect(page.getByRole("heading", { name: "Refinement is prepared" })).toBeVisible(); await expect(page.getByRole("region", { name: "Validate results and prepare Refinement" }).getByText(/No Refinement job has been submitted or started/)).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)).toBe(false); expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});
