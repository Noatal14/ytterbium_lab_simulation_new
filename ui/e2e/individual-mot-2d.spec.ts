import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const sourceId = `mot2d-source-${"a".repeat(32)}`;

for (const cpus of [1, 2]) {
test(`operator reviews and explicitly starts one local 2D-MOT run on ${cpus} CPUs`, async ({
  page,
}) => {
  await page.addInitScript((cpus) => Object.defineProperty(navigator, "hardwareConcurrency", { value: cpus }), cpus);
  let previewWorkers: number | undefined;
  await page.route("**/api/v1/campaigns", (route) =>
    route.fulfill({
      json: {
        api_version: 1,
        data: { campaigns: [], invalid_count: 0, total: 0 },
      },
    }),
  );
  await page.route("**/api/v1/session", (route) =>
    route.fulfill({ json: { api_version: 1, data: { csrf_token: "csrf" } } }),
  );
  await page.route("**/api/v1/individual-runs/mot-2d/sources", (route) =>
    route.fulfill({
      json: {
        api_version: 1,
        data: {
          contract_version: "mot-2d-individual-source-catalog-v1",
          sources: [
            {
              id: sourceId,
              source_kind: "canonical_folder",
              label: "October ensembles",
              ensemble_count: 35,
              available_particle_count: {
                pooled: 10000,
                minimum_per_ensemble: 200,
                maximum_per_ensemble: 400,
              },
              source_qualification: "canonical_campaign_source",
              result_suitability: "individual_only",
              provenance: {
                validation: "canonical_zeeman_folder",
                profile: "laboratory",
                fingerprint: "d".repeat(64),
              },
            },
          ],
          invalid_count: 0,
          total: 1,
          truncated: false,
        },
      },
    }),
  );
  await page.route("**/api/v1/individual-runs/mot-2d/preview", (route) => {
    previewWorkers = route.request().postDataJSON().npools;
    return route.fulfill({
      json: {
        api_version: 1,
        data: {
          preview_token: "token",
          expires_in_seconds: 300,
          plan: {
            run_id: "mot2d-browser",
            family: "mot_2d",
            source: {
              id: sourceId,
              kind: "canonical_folder",
              qualification: "canonical_campaign_source",
              fingerprint: "a".repeat(64),
              pooled_particle_count: 10000,
            },
            selection: {
              algorithm: "stable",
              version: "1",
              seed: 42,
              selected_count: 200,
              selected_identities_sha256: "b".repeat(64),
            },
            controls: {
              s0: 1.3,
              detuning_gamma: -0.9196610026631429,
              magnet_radius_m: 0.04676406447474441,
            },
            execution: { mode: "local", particle_count: 200, mot_seed: 42 },
            retention: { particle_states: true },
            suitability: "individual_only",
            output_disposition: "retain_survivor_states",
            locked_settings: {
              solver: "RK4StHybridCustom",
              timestep_s: 0.000000625,
              workers: previewWorkers,
            },
            lifecycle_state: "configured",
            laboratory_specification: {},
            numerical_policy: {},
            plan_sha256: "c".repeat(64),
            execution_started: false,
            submitted_to_zeus: false,
          },
        },
      },
    });
  });
  await page.route("**/api/v1/individual-runs/mot-2d/confirm", (route) =>
    route.fulfill({
      status: 201,
      json: {
        api_version: 1,
        data: {
          status: "created",
          run_id: "mot2d-browser",
          family: "mot_2d",
          path: "data/runs/mot_2d/mot2d-browser",
          lifecycle_state: "configured",
          execution_started: false,
          submitted_to_zeus: false,
        },
      },
    }),
  );
  let starts = 0;
  await page.route("**/api/v1/individual-runs/mot-2d/local/start", (route) => {
    starts += 1;
    return route.fulfill({
      status: 202,
      json: {
        api_version: 1,
        data: {
          status: "queued",
          run_id: "mot2d-browser",
          execution_mode: "local",
        },
      },
    });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "Configure 2D-MOT run" }).click();
  await expect(
    page.getByRole("heading", { name: "Run one 2D-MOT simulation" }),
  ).toBeFocused();
  await expect(
    page.getByRole("combobox", { name: /Zeeman survivor source/ }),
  ).toHaveValue(sourceId);
  await expect(
    page.getByRole("option", { name: /October ensembles/ }),
  ).toHaveCount(1);
  await expect(
    page.getByRole("spinbutton", { name: /Particle count/ }),
  ).toHaveAttribute("max", "1000");
  await page
    .getByRole("combobox", { name: /Zeeman survivor source/ })
    .selectOption(sourceId);
  await expect(page.locator("#mot2d-npools")).toHaveValue(String(cpus));
  await expect(page.locator("#mot2d-npools")).toHaveAttribute("max", String(cpus));
  await page.getByRole("button", { name: "Validate and review" }).click();
  await expect(
    page.getByText("Scientific role: individual only"),
  ).toBeVisible();
  await expect(
    page.getByText(/not automatically valid campaign inputs/),
  ).toBeVisible();
  await page.getByRole("button", { name: "Create reviewed run" }).click();
  expect(starts).toBe(0);
  await page.getByRole("button", { name: "Start on this computer" }).click();
  await expect(page.getByText(/Status has not been checked/)).toBeVisible();
  expect(starts).toBe(1);
  expect(previewWorkers).toBe(cpus);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth >
        document.documentElement.clientWidth,
    ),
  ).toBe(false);
});

}
