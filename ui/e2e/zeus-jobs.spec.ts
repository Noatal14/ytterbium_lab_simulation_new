import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test("Zeus Jobs connects only on request and renders a read-only snapshot", async ({ page }) => {
  const requests: string[] = [];
  let snapshotRequests = 0;
  page.on("request", (request) => requests.push(`${request.method()} ${new URL(request.url()).pathname}`));
  await page.route("**/api/v1/campaigns", (route) => route.fulfill({ json: { api_version: 1, data: { campaigns: [{
    id: "mot_2d-test", family: "mot_2d", kind: "mot_2d_s0_campaign", name: "Fixed s0 1.3", path: "data/optimization/mot_2d/test", stage: "confirmation", stage_semantics: "prepared-workflow-stage", scheduler_status: "unchecked", trust: "trusted-current", scientific_role: "candidate-selection", progress: [{ stage: "confirmation", completed: 2, expected: 5, status: "in-progress" }], warnings: [{ severity: "info", message: "Scheduler state is not checked." }], next_plan: null, s0_values: [1.3], families: [], git_commit: "abc"
  }], invalid_count: 0, total: 1 } } }));
  await page.route("**/api/v1/session", (route) => route.fulfill({ json: { api_version: 1, data: { csrf_token: "csrf-token" } } }));
  await page.route("**/api/v1/zeus/snapshot", async (route) => {
    snapshotRequests += 1;
    expect(route.request().method()).toBe("POST");
    expect(route.request().headers()["x-csrf-token"]).toBe("csrf-token");
    expect(route.request().postDataJSON()).toEqual({ username: "tal.noa", project_directory: "/home/tal.noa/ytterbium_lab_simulation_new" });
    await route.fulfill({ json: { api_version: 1, data: {
      connection_status: "connected",
      profile: { host: "zeus-login.zeus.technion.ac.il", username: "tal.noa", project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", authentication: "ssh-key-or-agent" },
      remote: { project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", git_commit: "a".repeat(40), branch: "main", dirty: false },
      scheduler: { status: "available", queried_at: new Date().toISOString(), jobs: [
        { id: "4756504[0]", name: "2D confirmation", raw_state: "R", state: "running", exit_status: null, walltime: "00:12:00", start_time: null, comment: null, dependencies: [] },
        { id: "4756505", name: "Held merge", raw_state: "H", state: "held_attention", exit_status: null, walltime: null, start_time: null, comment: "held", dependencies: ["4756504[0]"] },
      ] },
    } } });
  });
  await page.goto("/");
  await page.getByRole("link", { name: "Zeus jobs" }).click();
  await expect(page.getByRole("heading", { name: "Monitor jobs safely" })).toBeVisible();
  await expect(page.getByText("Not connected", { exact: true })).toBeVisible();
  expect(requests.filter((request) => request.includes("/api/v1/session") || request.includes("/api/v1/zeus/snapshot"))).toEqual([]);
  await page.getByLabel("Technion username").fill("tal.noa");
  await expect(page.getByLabel("Remote project directory")).toHaveValue("/home/tal.noa/ytterbium_lab_simulation_new");
  await page.getByRole("button", { name: "Connect and check status" }).click();
  await expect(page.getByText("Connected — read-only snapshot received")).toBeVisible();
  await expect(page.getByText("Running", { exact: true })).toBeVisible();
  await expect(page.getByText(/No action needed while this job is running/)).toBeVisible();
  await expect(page.getByText(/Raw PBS state H/)).toBeVisible();
  await expect(page.getByText("Held — attention needed")).toBeVisible();
  await expect(page.getByText(/Recorded dependencies: 4756504\[0\] \(context only\)/)).toBeVisible();
  await expect(page.getByText(/A hold always needs attention/)).toBeVisible();
  expect(snapshotRequests).toBe(1);
  await page.getByRole("button", { name: "Refresh status" }).click();
  await expect.poll(() => snapshotRequests).toBe(2);
  await expect(page.getByText("Partial local outputs")).toBeVisible();
  await expect(page.getByRole("button", { name: /submit/i })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /cancel/i })).toHaveCount(0);
  await expect(page.getByLabel(/password/i)).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)).toBe(false);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});
