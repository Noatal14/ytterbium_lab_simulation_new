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
