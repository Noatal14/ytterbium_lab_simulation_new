import { describe, expect, it } from "vitest";

import errorSnapshot from "../../../tests/contracts/v1/workflow_api_errors.json";
import successSnapshot from "../../../tests/contracts/v1/workflow_api_success.json";
import {
  campaignApi,
  creationApi,
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

  it("drives every frontend route snapshot through its real API and domain parser", async () => {
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

    const exercisedPaths = new Set(fetchMock.mock.calls.map(([input, init]) => `${String(init?.method ?? "GET").toUpperCase()} ${typeof input === "string" ? input : String(input)}`));
    for (const entry of successSnapshot.cases) {
      if (["health", "workflows"].includes(entry.id)) continue;
      expect(exercisedPaths).toContain(`${entry.method} ${entry.path}`);
    }
    expect(dataById("confirmation-confirm").status).toBe("confirmation_prepared");
    vi.unstubAllGlobals();
  });
});
