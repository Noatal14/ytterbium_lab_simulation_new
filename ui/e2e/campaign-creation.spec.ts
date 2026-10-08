import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test("operator previews and creates local files without Zeus", async ({ page }) => {
  await page.route("**/api/v1/campaigns", (route) => route.fulfill({ json: { api_version: 1, data: { campaigns: [], invalid_count: 0, total: 0 } } }));
  await page.route("**/api/v1/session", (route) => route.fulfill({ json: { api_version: 1, data: { csrf_token: "csrf" } } }));
  await page.route("**/api/v1/campaigns/2d/sources", (route) => route.fulfill({ json: { api_version: 1, data: { sources: [{ id: "source", path: "data/particle_states/after_zeeman/production", profile: "production", ensemble_count: 35, minimum_survivors: 31000, maximum_survivors: 32000, fingerprint: "f".repeat(64) }], invalid_count: 0, total: 1 } } }));
  await page.route("**/api/v1/campaigns/2d/preview", (route) => route.fulfill({ json: { api_version: 1, data: { preview_token: "token", expires_in_seconds: 300, plan: { name: "Fixed s0 1.3", path: "data/optimization/mot_2d/s0_1p3", s0_values: [1.3], source_id: "source", files: ["campaign.json", "jobs/01_smoke.pbs"], stage: "smoke" }, scientific_design: {}, provenance: { commit: "a".repeat(40), input_count: 35 }, duplicate: null } } }));
  await page.route("**/api/v1/campaigns/2d/confirm", (route) => route.fulfill({ status: 201, json: { api_version: 1, data: { status: "created", campaign_id: "created", path: "data/optimization/mot_2d/s0_1p3", stage: "smoke", submitted_to_zeus: false } } }));
  await page.goto("/");
  await page.getByRole("button", { name: "Start 2D-MOT campaign" }).click();
  await page.getByLabel(/^Campaign name/).fill("Fixed s0 1.3");
  await page.getByLabel(/^Campaign folder/).fill("s0_1p3");
  await page.getByLabel(/^Zeeman ensemble source/).selectOption("source");
  await page.getByLabel(/^Fixed s₀ values/).fill("1.3");
  await page.getByRole("button", { name: "Review campaign" }).click();
  await expect(page.getByRole("heading", { name: "Review before creating" })).toBeFocused();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.getByRole("button", { name: "Create campaign" }).click();
  await expect(page.getByRole("heading", { name: "Campaign created and validated" })).toBeFocused();
  await expect(page.getByText(/No simulation was run and no work was submitted to Zeus/)).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)).toBe(false);
});
