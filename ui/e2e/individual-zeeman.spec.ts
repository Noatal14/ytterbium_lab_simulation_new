import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test("operator reviews and explicitly starts one local Zeeman run", async ({ page }) => {
  const publicId = `individual-run-${"a".repeat(24)}`;
  const runBase = {
    id: publicId, record_kind: "individual_simulation_run", run_kind: "zeeman", display_name: "zeeman-browser",
    stage_semantics: "single-run-lifecycle", source: "local", queried_at: "2026-10-13T10:00:00+00:00",
    trust: "verified-package", scientific_role: "individual-only", created_at: "2026-10-13T09:00:00+00:00",
    updated_at: "2026-10-13T10:00:00+00:00", execution: { mode: "local", zeus_job_id: null, progress: null },
    warnings: [],
  };
  let catalogReads = 0;
  await page.route("**/api/v1/campaigns", (route) => route.fulfill({ json: { api_version: 1, data: { campaigns: [], invalid_count: 0, total: 0 } } }));
  await page.route("**/api/v1/session", (route) => route.fulfill({ json: { api_version: 1, data: { csrf_token: "csrf" } } }));
  await page.route("**/api/v1/individual-runs/zeeman/preview", (route) => route.fulfill({ json: { api_version: 1, data: { preview_token: "token", expires_in_seconds: 300, plan: { run_id: "zeeman-browser", family: "zeeman", execution_mode: "local", particle_count: 200, seed: 42, mot_2d_s0: 1.3, mot_2d_detuning_gamma: -0.9196610026631429, mot_2d_magnet_radius_m: 0.04676406447474441, npools: route.request().postDataJSON().npools, retain_particle_states: true, suitability: "individual_only", output_disposition: "retain_survivor_states", locked_settings: { policy: "canonical" }, resolved_configuration: { solver: { name: "RK4StCustom" }, field: { profile: "laboratory" } }, lifecycle_state: "configured", laboratory_specification: { version: 1 }, numerical_policy: { version: 1 }, plan_sha256: "a".repeat(64), execution_started: false, submitted_to_zeus: false } } } }));
  await page.route("**/api/v1/individual-runs/zeeman/confirm", (route) => route.fulfill({ status: 201, json: { api_version: 1, data: { status: "created", run_id: "zeeman-browser", family: "zeeman", path: "data/runs/zeeman/zeeman-browser", lifecycle_state: "configured", execution_started: false, submitted_to_zeus: false } } }));
  let starts = 0;
  await page.route("**/api/v1/individual-runs/zeeman/local/start", (route) => { starts += 1; return route.fulfill({ status: 202, json: { api_version: 1, data: { status: "queued", run_id: "zeeman-browser", execution_mode: "local" } } }); });
  await page.route(`**/api/v1/individual-runs/${publicId}`, (route) => route.fulfill({ json: { api_version: 1, data: {
    ...runBase, record_state: "succeeded", integrity: "complete_verified", lifecycle: "results_ready", next_action: "view_results",
    retention: { particle_states_requested: true, status: "retained" }, results: { availability: "verified", completed_at: "2026-10-13T10:00:00+00:00" },
    provenance: { git_revision: "a".repeat(40), configuration_sha256: "b".repeat(64), inputs_sha256: "c".repeat(64), laboratory_spec: {}, numerical_policy: {} },
    configuration: { status: "complete", resolved: {} }, inputs: { status: "complete", artifacts: [] }, artifacts: [],
    metrics: { captured: 120, elapsed_s: 8.94, n_initial: 200, n_survivors: 120, survival_fraction: 0.6 }, error: null,
  } } }));
  await page.route("**/api/v1/individual-runs", (route) => {
    catalogReads += 1;
    const complete = catalogReads > 1;
    const run = complete
      ? { ...runBase, record_state: "succeeded", integrity: "complete_verified", lifecycle: "results_ready", next_action: "view_results", retention: { particle_states_requested: true, status: "retained" }, results: { availability: "verified", completed_at: "2026-10-13T10:00:00+00:00" } }
      : { ...runBase, record_state: "running", integrity: "active", lifecycle: "running", next_action: "wait", retention: { particle_states_requested: true, status: "pending" }, results: { availability: "not_ready", completed_at: null } };
    return route.fulfill({ json: { api_version: 1, data: { runs: [run], invalid_count: 0, total: 1, truncated: false } } });
  });
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
  await expect(page.getByText(/Check run progress/)).toBeVisible();
  expect(starts).toBe(1);
  await page.reload();
  await page.getByRole("button", { name: "Configure Zeeman run" }).click();
  await expect(page.getByRole("heading", { name: "Verified results are ready" })).toBeVisible();
  await expect(page.getByText("120", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)).toBe(false);
  expect(starts).toBe(1);
});
