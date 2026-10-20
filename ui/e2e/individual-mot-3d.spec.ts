import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { MOT_3D_INDIVIDUAL_SPECIFICATION_V1 as spec } from "../src/generated/mot3dIndividualSpec.v1";

const sourceId = `mot3d-source-${"a".repeat(32)}`;

async function routes(page: Page) {
  let confirmed = 0;
  let runId = "mot3d-browser-angled-donut";
  let executionMode: "local" | "zeus" = "local";
  await page.route("**/api/v1/campaigns", (route) => route.fulfill({ json: { api_version: 1, data: { campaigns: [], invalid_count: 0, total: 0 } } }));
  await page.route("**/api/v1/session", (route) => route.fulfill({ json: { api_version: 1, data: { csrf_token: "csrf" } } }));
  await page.route("**/api/v1/individual-runs/mot-3d/sources", (route) => route.fulfill({ json: { api_version: 1, data: {
    contract_version: "mot-3d-individual-source-catalog-v1",
    sources: [{
      id: sourceId,
      source_kind: "canonical_2d_campaign",
      label: "October 2D-MOT campaign",
      ensemble_count: 20,
      available_particle_count: { pooled: 12_000, minimum_per_ensemble: 500, maximum_per_ensemble: 700 },
      source_qualification: "canonical_campaign_source",
      result_suitability: "individual_only",
      provenance: {
        validation: "completed_canonical_2d_campaign",
        campaign_name: "october-2d",
        s0: 1.3,
        ensemble_count: 20,
        campaign_sha256: "d".repeat(64),
        final_report_sha256: "e".repeat(64),
        fingerprint: "f".repeat(64),
      },
    }],
    invalid_count: 0,
    total: 1,
    truncated: false,
  } } }));
  await page.route("**/api/v1/individual-runs/mot-3d/preview", async (route) => {
    const request = route.request().postDataJSON();
    executionMode = request.execution_mode;
    const singlePass = request.geometry_family === "single_pass";
    await route.fulfill({ json: { api_version: 1, data: {
      preview_token: `token-${request.geometry_family}`,
      expires_in_seconds: 300,
      plan: {
        run_id: `mot3d-browser-${String(request.geometry_family).replaceAll("_", "-")}`,
        family: "mot_3d",
        source: { id: sourceId, kind: "canonical_2d_campaign", qualification: "canonical_campaign_source", fingerprint: "a".repeat(64), pooled_particle_count: 12_000 },
        selection: { algorithm: spec.sampling.algorithm, version: spec.sampling.version, seed: request.selection_seed, selected_count: request.particle_count, selected_identities_sha256: "b".repeat(64) },
        geometry: {
          family: request.geometry_family,
          parameters: request.parameters,
          derived_parameters: singlePass ? { blue_detuning_gamma: -2.58, effective_slowing_z_offset_m: -0.044, effective_slowing_field_G: 12.5, reference_slowing_field_G: 10.25 } : {},
        },
        execution: { mode: request.execution_mode, particle_count: request.particle_count, simulation_seed: request.simulation_seed },
        retention: { particle_states: request.retain_particle_states },
        suitability: "individual_only",
        output_disposition: request.retain_particle_states ? "retain_survivor_states" : "discard_survivor_states_after_summary",
        locked_settings: {
          solver: spec.fixed_classification.solver,
          timestep_s: spec.fixed_classification.timestep_s,
          t_max_s: spec.fixed_classification.t_max_s,
          convergence_claim: spec.fixed_classification.convergence_claim,
          capture: spec.fixed_classification.capture,
          sampling_algorithm: spec.sampling.algorithm,
          sampling_version: spec.sampling.version,
          workers: spec.workers_by_execution_mode[request.execution_mode as "local" | "zeus"],
        },
        lifecycle_state: "configured",
        laboratory_specification: spec.authority_references.laboratory_specification,
        numerical_policy: spec.authority_references.numerical_policy,
        plan_sha256: "c".repeat(64),
        execution_started: false,
        submitted_to_zeus: false,
      },
    } } });
  });
  await page.route("**/api/v1/individual-runs/mot-3d/confirm", async (route) => {
    confirmed += 1;
    const token = route.request().postDataJSON().preview_token as string;
    const family = token.replace("token-", "").replaceAll("_", "-");
    runId = `mot3d-browser-${family}`;
    await route.fulfill({ status: 201, json: { api_version: 1, data: {
      status: "created",
      run_id: `mot3d-browser-${family}`,
      family: "mot_3d",
      path: `data/runs/mot_3d/mot3d-browser-${family}`,
      lifecycle_state: "configured",
      execution_started: false,
      submitted_to_zeus: false,
    } } });
  });
  await page.route("**/api/v1/individual-runs/mot-3d/local/start", async (route) => {
    const request = route.request().postDataJSON();
    await route.fulfill({ status: 202, json: { api_version: 1, data: { status: "queued", run_id: request.run_id, execution_mode: "local" } } });
  });
  await page.route("**/api/v1/individual-runs/mot-3d/zeus/preview", async (route) => {
    const request = route.request().postDataJSON();
    await route.fulfill({ json: { api_version: 1, data: { preview_token: "zeus-review", expires_in_seconds: 300, run_id: request.run_id, job: { kind: "scalar", array: false, pbs_sha256: "4".repeat(64), resources: { queue: "zeus_combined_q", cores: 200, memory_bytes: 68719476736, walltime_seconds: 28800 } }, package_sha256: "5".repeat(64), submission_key: "6".repeat(64), effects: { submit_one_job: true, reconcile_existing_job: false, cancel_job: false } } } });
  });
  await page.route("**/api/v1/individual-runs/mot-3d/zeus/confirm", async (route) => {
    await route.fulfill({ status: 202, json: { api_version: 1, data: { status: "submitted", run_id: runId, job_id: "500.zeus-master", submission_key: "6".repeat(64) } } });
  });
  await page.route("**/api/v1/individual-runs/mot-3d/zeus/refresh", async (route) => {
    await route.fulfill({ json: { api_version: 1, data: { state: "running", job_id: "500.zeus-master" } } });
  });
  await page.route("**/api/v1/individual-runs", (route) => route.fulfill({ json: { api_version: 1, data: {
    runs: [{
      id: `individual-run-${"1".repeat(24)}`, record_kind: "individual_simulation_run", run_kind: "mot_3d", display_name: runId,
      stage_semantics: "single-run-lifecycle", source: "local", queried_at: "2026-10-12T12:00:00+00:00", trust: "verified-package",
      scientific_role: "individual-only", record_state: "running", integrity: "active", lifecycle: "running", next_action: "wait",
      created_at: "2026-10-12T12:00:00+00:00", updated_at: "2026-10-12T12:00:00+00:00", execution: { mode: executionMode, zeus_job_id: executionMode === "zeus" ? "500.zeus-master" : null },
      retention: { particle_states_requested: true, status: "pending" }, results: { availability: "not_ready", completed_at: null }, warnings: [],
    }], invalid_count: 0, total: 1, truncated: false,
  } } }));
  return () => confirmed;
}

test("requires Zeus review before explicitly submitting one 3D-MOT job", async ({ page }) => {
  await routes(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Configure 3D-MOT run" }).click();
  await page.getByLabel("Zeus").click();
  await page.getByRole("button", { name: "Validate setup" }).click();
  await page.getByRole("button", { name: "Create run record" }).click();
  await page.getByLabel(/Technion username/).fill("tal.noa");
  await page.getByRole("button", { name: "Review Zeus submission" }).click();
  await expect(page.getByText(/ready for confirmation/)).toBeVisible();
  await page.getByRole("button", { name: "Confirm and submit one Zeus job" }).click();
  await expect(page.getByText("Status has not been checked")).toBeVisible();
  await page.getByRole("button", { name: "Check status" }).click();
  await expect(page.getByText("Run is in progress")).toBeVisible();
});

for (const family of ["angled_donut", "single_pass"] as const) {
  test(`creates a reviewed ${family} 3D-MOT record without execution`, async ({ page }) => {
    const confirmed = await routes(page);
    await page.goto("/");
    await page.getByRole("button", { name: "Configure 3D-MOT run" }).click();
    await expect(page.getByRole("heading", { name: "Configure one 3D-MOT simulation" })).toBeFocused();
    await expect(page.getByRole("combobox", { name: /2D-MOT survivor source/ })).toHaveValue(sourceId);
    await expect(page.getByRole("spinbutton", { name: /Particle count/ })).toHaveAttribute("max", "1000");
    if (family === "single_pass") await page.getByRole("radio", { name: /^Single pass/ }).click();
    await page.getByRole("button", { name: "Validate setup" }).click();
    await expect(page.getByText("Scientific role: individual only")).toBeVisible();
    if (family === "single_pass") {
      await expect(page.getByRole("heading", { name: "Derived single-pass values" })).toBeVisible();
      await expect(page.getByText("-2.58 Γ")).toBeVisible();
    } else {
      await expect(page.getByRole("heading", { name: "Angled-donut parameters" })).toBeVisible();
    }
    expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
    const overflow = await page.evaluate(() => [...document.querySelectorAll<HTMLElement>("body *")]
      .filter((element) => element.getBoundingClientRect().right > document.documentElement.clientWidth + 1)
      .map((element) => `${element.tagName.toLowerCase()}.${element.className}`));
    expect(overflow).toEqual([]);
    await page.getByRole("button", { name: "Create run record" }).click();
    await expect(page.getByText("Reviewed run is ready")).toBeVisible();
    await expect(page.getByText(/Nothing is running yet/)).toBeVisible();
    await page.getByRole("button", { name: "Start on this computer" }).click();
    await expect(page.getByText("Status has not been checked")).toBeVisible();
    await page.getByRole("button", { name: "Check status" }).click();
    await expect(page.getByText("Run is in progress")).toBeVisible();
    await expect(page.getByText(/No action is required/)).toBeVisible();
    expect(confirmed()).toBe(1);
  });
}
