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
  expect(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)).toBe(false);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});
