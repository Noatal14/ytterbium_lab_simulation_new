import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test("operator reviews and explicitly starts one local Zeeman run", async ({ page }) => {
  await page.route("**/api/v1/campaigns", (route) => route.fulfill({ json: { api_version: 1, data: { campaigns: [], invalid_count: 0, total: 0 } } }));
  await page.route("**/api/v1/session", (route) => route.fulfill({ json: { api_version: 1, data: { csrf_token: "csrf" } } }));
  await page.route("**/api/v1/individual-runs/zeeman/preview", (route) => route.fulfill({ json: { api_version: 1, data: { preview_token: "token", expires_in_seconds: 300, plan: { run_id: "zeeman-browser", family: "zeeman", execution_mode: "local", particle_count: 200, seed: 42, retain_particle_states: true, suitability: "individual_only", output_disposition: "retain_survivor_states", locked_settings: { policy: "canonical" }, resolved_configuration: { solver: { name: "RK4StCustom" }, field: { profile: "laboratory" } }, lifecycle_state: "configured", laboratory_specification: { version: 1 }, numerical_policy: { version: 1 }, plan_sha256: "a".repeat(64), execution_started: false, submitted_to_zeus: false } } } }));
  await page.route("**/api/v1/individual-runs/zeeman/confirm", (route) => route.fulfill({ status: 201, json: { api_version: 1, data: { status: "created", run_id: "zeeman-browser", family: "zeeman", path: "data/runs/zeeman/zeeman-browser", lifecycle_state: "configured", execution_started: false, submitted_to_zeus: false } } }));
  let starts = 0;
  await page.route("**/api/v1/individual-runs/zeeman/local/start", (route) => { starts += 1; return route.fulfill({ status: 202, json: { api_version: 1, data: { status: "queued", run_id: "zeeman-browser", execution_mode: "local" } } }); });
  await page.goto("/");
  await page.getByRole("button", { name: "Configure Zeeman run" }).click();
  await expect(page.getByRole("heading", { name: "Run one Zeeman simulation" })).toBeFocused();
  await expect(page.getByRole("spinbutton", { name: /Particle count/ })).toHaveValue("200");
  await expect(page.getByRole("spinbutton", { name: /Particle count/ })).toHaveAttribute("max", "1000");
  await page.getByRole("button", { name: "Validate and review" }).click();
  await expect(page.getByRole("heading", { name: "Validated run plan" })).toBeVisible();
  await expect(page.getByText("No files have been created and no work has started.")).toBeVisible();
  await page.getByRole("button", { name: "Create reviewed run" }).click();
  await expect(page.getByText("Nothing is running yet. Start only when you are ready.")).toBeVisible();
  expect(starts).toBe(0);
  await page.getByRole("button", { name: "Start on this computer" }).click();
  await expect(page.getByText(/Status has not been checked/)).toBeVisible();
  expect(starts).toBe(1);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)).toBe(false);
});
