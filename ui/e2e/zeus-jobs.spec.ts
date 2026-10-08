import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test("Zeus Jobs is honest, read-only, accessible, and responsive", async ({ page }) => {
  const requests: string[] = [];
  page.on("request", (request) => requests.push(`${request.method()} ${new URL(request.url()).pathname}`));
  await page.route("**/api/v1/campaigns", (route) => route.fulfill({ json: { api_version: 1, data: { campaigns: [{
    id: "mot_2d-test", family: "mot_2d", kind: "mot_2d_s0_campaign", name: "Fixed s0 1.3", path: "data/optimization/mot_2d/test", stage: "confirmation", stage_semantics: "prepared-workflow-stage", scheduler_status: "unchecked", trust: "trusted-current", scientific_role: "candidate-selection", progress: [{ stage: "confirmation", completed: 2, expected: 5, status: "in-progress" }], warnings: [{ severity: "info", message: "Scheduler state is not checked." }], next_plan: null, s0_values: [1.3], families: [], git_commit: "abc"
  }], invalid_count: 0, total: 1 } } }));
  await page.goto("/");
  await page.getByRole("link", { name: "Zeus jobs" }).click();
  await expect(page.getByRole("heading", { name: "Monitor job readiness safely" })).toBeVisible();
  await expect(page.getByText("Zeus connection: Not configured")).toBeVisible();
  await expect(page.getByText("No locally recorded Zeus jobs")).toBeVisible();
  await expect(page.getByText("Partial local outputs")).toBeVisible();
  await expect(page.getByText(/cannot run SSH, qsub, or any scheduler command/)).toBeVisible();
  await expect(page.getByRole("button", { name: /submit/i })).toHaveCount(0);
  expect(requests.filter((request) => request.startsWith("GET /api/") && !request.endsWith("/api/v1/campaigns"))).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)).toBe(false);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});
