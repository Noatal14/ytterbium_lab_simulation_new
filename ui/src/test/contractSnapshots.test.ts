import { describe, expect, it } from "vitest";

import errorSnapshot from "../../../tests/contracts/v1/workflow_api_errors.json";
import successSnapshot from "../../../tests/contracts/v1/workflow_api_success.json";
import {
  campaignApi,
  creationApi,
  confirmationSubmissionApi,
  parseApiErrorEnvelope,
  parseApiSuccessEnvelope,
  refinementLifecycleApi,
  refinementSubmissionApi,
  screeningLifecycleApi,
  screeningSubmissionApi,
  smokeLifecycleApi,
  submissionApi,
  transferApi,
  zeusApi,
} from "../api/campaigns";
import { sensitivityApi, sensitivitySubmissionApi } from "../api/clients/sensitivity";
import { finalizationApi, productionApi, productionSubmissionApi } from "../api/clients/production";
import { createMot3DBootstrapApi } from "../api/clients/mot3d";
import { createMot3DDiscoveryApi } from "../api/clients/mot3dDiscovery";
import { createMot3DDiscoveryTransitionApi } from "../api/clients/mot3dDiscoveryTransition";
import { createPreliminaryCheckApi } from "../api/clients/mot3dPreliminaryCheck";
import { createIndividualMot3DApi, type Mot3DRequest } from "../api/clients/individualMot3D";

type SnapshotCase = (typeof successSnapshot.cases)[number];
const caseById = (id: string) => successSnapshot.cases.find((entry) => entry.id === id) as SnapshotCase;
const dataById = (id: string) => (caseById(id).body as { data: Record<string, unknown> }).data;

describe("backend-generated workflow API contract snapshots", () => {
  it("covers unique successful route shapes with the current schema version", () => {
    expect(successSnapshot.schema_version).toBe(1);
    expect(successSnapshot.cases.length).toBeGreaterThan(0);
    expect(new Set(successSnapshot.cases.map((entry) => entry.id)).size).toBe(successSnapshot.cases.length);

    for (const entry of successSnapshot.cases) {
      expect(entry.status).toBeGreaterThanOrEqual(200);
      expect(entry.status).toBeLessThan(300);
      if (entry.id === "health") {
        expect(entry.body).toStrictEqual({ api_version: 1, status: "ok" });
      } else {
        expect(() => parseApiSuccessEnvelope(entry.body)).not.toThrow();
      }
    }
  });

  it("keeps every generated error contract exact and unversioned", () => {
    expect(errorSnapshot.schema_version).toBe(1);
    expect(errorSnapshot.cases.length).toBeGreaterThan(0);
    expect(new Set(errorSnapshot.cases.map((entry) => entry.id)).size).toBe(errorSnapshot.cases.length);

    for (const entry of errorSnapshot.cases) {
      expect(entry.status).toBeGreaterThanOrEqual(400);
      expect(parseApiErrorEnvelope(entry.body)).toStrictEqual(entry.body.error);
      expect(entry.body).not.toHaveProperty("api_version");
      expect(entry.body).not.toHaveProperty("data");
    }
  });

  it("drives every campaign-workflow route snapshot through its real API and domain parser", async () => {
    const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const path = typeof input === "string" ? input : input instanceof URL ? input.pathname : new URL(input.url).pathname;
      const method = String(init?.method ?? "GET").toUpperCase();
      const entry = successSnapshot.cases.find((candidate) => candidate.path === path && candidate.method === method);
      if (!entry) throw new Error(`No backend contract snapshot for ${method} ${path}`);
      return { ok: entry.status >= 200 && entry.status < 300, status: entry.status, json: async () => entry.body };
    });
    vi.stubGlobal("fetch", fetchMock);

    const campaignId = "campaign-id";
    const profile = { host: "zeus.technion.ac.il" as const, username: "tal.noa", project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", authentication: "ssh-key-or-agent" as const };

    await campaignApi.list();
    await campaignApi.get(campaignId);
    await creationApi.sources();
    await creationApi.session();
    const creationPreview = await creationApi.preview({ name: "Campaign", slug: "campaign-id", source_id: "source", s0_values: [1.3] }, "<csrf-token>");
    await creationApi.confirm(String(creationPreview.preview_token), "<csrf-token>");
    const mot3d = createMot3DBootstrapApi(async () => "<csrf-token>");
    await mot3d.status();
    const mot3dPreview = await mot3d.preview("a".repeat(64), "mot_3d_contract");
    await mot3d.confirm(mot3dPreview.preview_token, "mot_3d_contract");
    const mot3dDiscovery = createMot3DDiscoveryApi(async () => "<csrf-token>");
    await mot3dDiscovery.status(campaignId, profile);
    const mot3dDiscoveryPreview = await mot3dDiscovery.preview(campaignId, profile);
    await mot3dDiscovery.confirm(mot3dDiscoveryPreview.preview_token);
    const mot3dTransition = createMot3DDiscoveryTransitionApi(async () => "<csrf-token>");
    await mot3dTransition.status(campaignId, profile);
    const mot3dTransitionPreview = await mot3dTransition.preview(campaignId, profile);
    await mot3dTransition.confirm(mot3dTransitionPreview.preview_token);
    const preliminaryCheck = createPreliminaryCheckApi(async () => "<csrf-token>");
    await preliminaryCheck.status(campaignId, profile);
    const preliminaryPreview = await preliminaryCheck.preview(campaignId, profile);
    await preliminaryCheck.confirm(preliminaryPreview.preview_token);
    await zeusApi.snapshot(profile.username, profile.project_directory);

    const transferPreview = await transferApi.preview(campaignId, profile);
    await transferApi.confirm(transferPreview.preview_token);
    const smokeSubmitPreview = await submissionApi.preview(campaignId, profile);
    await submissionApi.confirm(smokeSubmitPreview.preview_token);
    await smokeLifecycleApi.status(campaignId, profile);
    const screeningPreview = await smokeLifecycleApi.preview(campaignId, profile);
    await smokeLifecycleApi.confirm(screeningPreview.preview_token);
    const screenSubmitPreview = await screeningSubmissionApi.preview(campaignId, profile);
    await screeningSubmissionApi.confirm(screenSubmitPreview.preview_token);
    await screeningLifecycleApi.status(campaignId, profile);
    const refinementPreview = await screeningLifecycleApi.preview(campaignId, profile);
    await screeningLifecycleApi.confirm(refinementPreview.preview_token);
    await refinementSubmissionApi.status(campaignId, profile);
    const refinementSubmitPreview = await refinementSubmissionApi.preview(campaignId, profile);
    await refinementSubmissionApi.confirm(refinementSubmitPreview.preview_token);
    await refinementLifecycleApi.status(campaignId, profile);
    const confirmationPreview = await refinementLifecycleApi.preview(campaignId, profile);
    await refinementLifecycleApi.confirm(confirmationPreview.preview_token);
    await confirmationSubmissionApi.status(campaignId, profile);
    const confirmationSubmitPreview = await confirmationSubmissionApi.preview(
      campaignId,
      profile,
    );
    await confirmationSubmissionApi.confirm(
      confirmationSubmitPreview.preview_token,
    );
    await sensitivityApi.status(campaignId, profile);
    const sensitivityPreview = await sensitivityApi.preview(campaignId, profile);
    await sensitivityApi.confirm(sensitivityPreview.preview_token);
    await sensitivitySubmissionApi.status(campaignId, profile);
    const sensitivitySubmitPreview = await sensitivitySubmissionApi.preview(campaignId, profile);
    await sensitivitySubmissionApi.confirm(sensitivitySubmitPreview.preview_token);
    await productionApi.status(campaignId, profile);
    const productionPreview = await productionApi.preview(campaignId, profile);
    await productionApi.confirm(productionPreview.preview_token);
    await productionSubmissionApi.status(campaignId, profile);
    const productionSubmitPreview = await productionSubmissionApi.preview(campaignId, profile);
    await productionSubmissionApi.confirm(productionSubmitPreview.preview_token);
    await finalizationApi.status(campaignId, profile);
    const finalizationPreview = await finalizationApi.preview(campaignId, profile);
    await finalizationApi.confirm(finalizationPreview.preview_token);
    const individualMot3D = createIndividualMot3DApi(async () => "<csrf-token>");
    await individualMot3D.sources();
    const individualMot3DRequest: Mot3DRequest = {
      source_id: `mot3d-source-${"a".repeat(32)}`,
      geometry_family: "angled_donut",
      particle_count: 20,
      selection_seed: 1,
      simulation_seed: 2,
      parameters: {
        green_s0: 30,
        green_detuning_gamma: -25,
        green_waist_m: 0.0075,
        blue_s0: 1.5,
        blue_waist_m: 0.0075,
        magnetic_gradient_G_cm: 2.5,
        blue_detuning_gamma: -3,
        core_shell_split_radius_m: 0.0025,
      },
      retain_particle_states: false,
      execution_mode: "local",
    };
    const individualMot3DPreview = await individualMot3D.preview(individualMot3DRequest);
    const createdMot3D = await individualMot3D.confirm(individualMot3DPreview.preview_token);
    await individualMot3D.startLocal(createdMot3D.run_id);
    const mot3DZeusPreview = await individualMot3D.previewZeus(createdMot3D.run_id, "tal.noa");
    await individualMot3D.confirmZeus(mot3DZeusPreview.preview_token);
    await individualMot3D.refreshZeus(createdMot3D.run_id, "tal.noa");

    const exercisedPaths = new Set(fetchMock.mock.calls.map(([input, init]) => `${String(init?.method ?? "GET").toUpperCase()} ${typeof input === "string" ? input : String(input)}`));
    for (const entry of successSnapshot.cases) {
      // Individual-run routes have richer stateful fixtures and are exercised by
      // their dedicated strict client/component suites. This contract walk owns
      // the campaign workflow APIs, including every guarded stage transition.
      if (
        ["health", "workflows"].includes(entry.id) ||
        entry.id.startsWith("zeeman-") ||
        entry.id.startsWith("mot2d-")
      ) continue;
      expect(exercisedPaths).toContain(`${entry.method} ${entry.path}`);
    }
    expect(dataById("confirmation-confirm").status).toBe("confirmation_prepared");
    expect(dataById("confirmation-submit-confirm").status).toBe("submitted");
    expect(dataById("sensitivity-confirm").status).toBe("sensitivity_prepared");
    expect(dataById("sensitivity-submit-confirm").status).toBe("submitted");
    expect(dataById("production-confirm").status).toBe("production_prepared");
    expect(dataById("production-submit-confirm").status).toBe("submitted");
    expect(dataById("finalization-confirm").status).toBe("campaign_complete");
    vi.unstubAllGlobals();
  });
});
