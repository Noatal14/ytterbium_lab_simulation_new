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
