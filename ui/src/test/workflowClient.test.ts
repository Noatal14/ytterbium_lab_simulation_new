import { afterEach, describe, expect, it, vi } from "vitest";

import { createSubmissionApi } from "../api/clients/smoke";
import { createTransferApi } from "../api/clients/zeus";
import { createSmokeLifecycleApi } from "../api/clients/smoke";
import { createScreeningLifecycleApi, createScreeningSubmissionApi } from "../api/clients/screening";
import { createRefinementLifecycleApi, createRefinementSubmissionApi } from "../api/clients/refinement";
import { createWorkflowApiClient } from "../api/workflowClient";
import successSnapshot from "../../../tests/contracts/v1/workflow_api_success.json";

const profile = { host: "zeus.technion.ac.il" as const, username: "tal.noa", project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", authentication: "ssh-key-or-agent" as const };

function smokePreview(campaignId: string, token: string) {
  return {
    preview_token: token, expires_in_seconds: 300,
    campaign: { id: campaignId, name: campaignId, path: `data/optimization/mot_2d/${campaignId}`, git_commit: "a".repeat(40), s0_values: [1.3] },
    stage: { id: "smoke", label: "Smoke check", purpose: "Validate setup" },
    job: { file: "jobs/01_smoke.pbs", kind: "job", task_count: 1, queue: "zeus_combined_q", cores_per_task: 1, memory_per_task_bytes: 68719476736, walltime_seconds: 1200 },
    remote: { host: "zeus.technion.ac.il", project_directory: profile.project_directory, commit: "a".repeat(40), branch: "main", dirty: false },
    inputs: { verified_count: 72, status: "ready" }, effects: { submit_smoke: true, submit_later_stages: false, modify_files: false }, later_stages_locked: true,
  };
}

function installSmokeServer(blockConfirm?: Promise<void>) {
  const campaigns = new Map<string, string>();
  const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const path = typeof input === "string" ? input : input instanceof URL ? input.pathname : new URL(input.url).pathname;
    if (path === "/api/v1/session") return { ok: true, status: 200, json: async () => ({ api_version: 1, data: { csrf_token: "aggregate-csrf" } }) };
    const body = JSON.parse(String(init?.body ?? "{}")) as { campaign_id?: string; preview_token?: string };
    if (path.endsWith("/preview")) {
      const campaignId = String(body.campaign_id); const token = `token-${campaignId}`; campaigns.set(token, campaignId);
      return { ok: true, status: 200, json: async () => ({ api_version: 1, data: smokePreview(campaignId, token) }) };
    }
    if (blockConfirm) await blockConfirm;
    const campaignId = campaigns.get(String(body.preview_token));
    return { ok: true, status: 201, json: async () => ({ api_version: 1, data: { status: "submitted", campaign_id: campaignId, stage: "smoke", job_id: "4759999.zeus-master", submitted_at: "2026-10-09T10:00:00Z", later_stages_locked: true } }) };
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

describe("per-client workflow review state", () => {
  it("keeps parallel campaign previews isolated and confirms them in either order", async () => {
    installSmokeServer();
    const api = createSubmissionApi(async () => "csrf-one");
    const [a, b] = await Promise.all([api.preview("campaign-a", profile), api.preview("campaign-b", profile)]);
    expect((await api.confirm(b.preview_token)).campaign_id).toBe("campaign-b");
    expect((await api.confirm(a.preview_token)).campaign_id).toBe("campaign-a");
  });

  it("keeps two tab-like clients isolated and reset affects only its owner", async () => {
    installSmokeServer();
    const first = createSubmissionApi(async () => "csrf-first");
    const second = createSubmissionApi(async () => "csrf-second");
    const firstPreview = await first.preview("campaign-a", profile);
    const secondPreview = await second.preview("campaign-b", profile);
    first.reset();
    await expect(first.confirm(firstPreview.preview_token)).rejects.toThrow("no longer active");
    expect((await second.confirm(secondPreview.preview_token)).campaign_id).toBe("campaign-b");
  });

  it("consumes a preview before the network call so a double confirm cannot submit twice", async () => {
    let release!: () => void;
    const blocked = new Promise<void>((resolve) => { release = resolve; });
    const fetchMock = installSmokeServer(blocked);
    const api = createSubmissionApi(async () => "csrf");
    const preview = await api.preview("campaign-a", profile);
    const first = api.confirm(preview.preview_token);
    await expect(api.confirm(preview.preview_token)).rejects.toThrow("no longer active");
    release();
    await expect(first).resolves.toMatchObject({ campaign_id: "campaign-a" });
    expect(fetchMock.mock.calls.filter(([path]) => String(path).endsWith("/confirm"))).toHaveLength(1);
  });
});

type PreviewContextApi = {
  preview(campaignId: string, selectedProfile: typeof profile): Promise<{ preview_token: string }>;
  confirm(token: string): Promise<{ campaign_id: string }>;
  reset(): void;
};

const contextFlows = [
  ["transfer", createTransferApi, "transfer-preview", "transfer-confirm"],
  ["smoke submission", createSubmissionApi, "smoke-submit-preview", "smoke-submit-confirm"],
  ["screening preparation", createSmokeLifecycleApi, "screening-preview", "screening-confirm"],
  ["screening submission", createScreeningSubmissionApi, "screen-submit-preview", "screen-submit-confirm"],
  ["refinement preparation", createScreeningLifecycleApi, "refinement-preview", "refinement-confirm"],
  ["refinement submission", createRefinementSubmissionApi, "refinement-submit-preview", "refinement-submit-confirm"],
  ["confirmation preparation", createRefinementLifecycleApi, "confirmation-preview", "confirmation-confirm"],
] as const;

type SnapshotCase = { id: string; path: string; body: { api_version: number; data: Record<string, unknown> } };
const snapshots = new Map((successSnapshot.cases as SnapshotCase[]).map((entry) => [entry.id, entry]));

function installContextServer(previewId: string, confirmId: string, blockConfirm?: Promise<void>) {
  const previewCase = snapshots.get(previewId)!;
  const confirmCase = snapshots.get(confirmId)!;
  const originalToken = String(previewCase.body.data.preview_token);
  const contexts = new Map<string, { campaignId: string; csrf: string }>();
  const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const path = typeof input === "string" ? input : input instanceof URL ? input.pathname : new URL(input.url).pathname;
    if (path === "/api/v1/session") return { ok: true, status: 200, json: async () => ({ api_version: 1, data: { csrf_token: "aggregate-csrf" } }) };
    const body = JSON.parse(String(init?.body ?? "{}")) as { campaign_id?: string; preview_token?: string };
    const csrf = String(new Headers(init?.headers).get("X-CSRF-Token"));
    if (path === previewCase.path) {
      const campaignId = String(body.campaign_id);
      const token = `${originalToken}-${campaignId}`;
      contexts.set(token, { campaignId, csrf });
      const responseBody = JSON.parse(JSON.stringify(previewCase.body).replaceAll(originalToken, token).replaceAll("campaign-id", campaignId));
      return { ok: true, status: 200, json: async () => responseBody };
    }
    if (path === confirmCase.path) {
      if (blockConfirm) await blockConfirm;
      const context = contexts.get(String(body.preview_token));
      if (!context) throw new Error("Unknown test preview token.");
      const responseBody = JSON.parse(JSON.stringify(confirmCase.body).replaceAll("campaign-id", context.campaignId));
      return { ok: true, status: 201, json: async () => responseBody };
    }
    throw new Error(`Unexpected test request: ${path}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, contexts };
}

describe.each(contextFlows)("%s preview context", (_name, factory, previewId, confirmId) => {
  it("keeps parallel campaigns and their captured CSRF tokens isolated", async () => {
    const { fetchMock, contexts } = installContextServer(previewId, confirmId);
    let sessions = 0;
    const api = factory(async () => `csrf-${++sessions}`) as PreviewContextApi;
    const first = await api.preview("campaign-a", profile);
    const second = await api.preview("campaign-b", profile);
    expect((await api.confirm(second.preview_token)).campaign_id).toBe("campaign-b");
    expect((await api.confirm(first.preview_token)).campaign_id).toBe("campaign-a");
    const confirms = fetchMock.mock.calls.filter(([path]) => String(path) === snapshots.get(confirmId)!.path);
    expect(new Headers(confirms[0][1]?.headers).get("X-CSRF-Token")).toBe(contexts.get(second.preview_token)!.csrf);
    expect(new Headers(confirms[1][1]?.headers).get("X-CSRF-Token")).toBe(contexts.get(first.preview_token)!.csrf);
  });

  it("consumes before confirm and reset does not affect another client", async () => {
    let release!: () => void;
    const blocked = new Promise<void>((resolve) => { release = resolve; });
    const { fetchMock } = installContextServer(previewId, confirmId, blocked);
    const first = factory(async () => "csrf-first") as PreviewContextApi;
    const second = factory(async () => "csrf-second") as PreviewContextApi;
    const firstPreview = await first.preview("campaign-a", profile);
    const secondPreview = await second.preview("campaign-b", profile);
    const pending = second.confirm(secondPreview.preview_token);
    await expect(second.confirm(secondPreview.preview_token)).rejects.toThrow("no longer active");
    first.reset();
    await expect(first.confirm(firstPreview.preview_token)).rejects.toThrow("no longer active");
    release();
    await expect(pending).resolves.toMatchObject({ campaign_id: "campaign-b" });
    expect(fetchMock.mock.calls.filter(([path]) => String(path) === snapshots.get(confirmId)!.path)).toHaveLength(1);
  });
});

it("aggregate reset clears contexts from different flows", async () => {
  const client = createWorkflowApiClient();
  // Each focused factory is independently covered above; this verifies the aggregate owns and resets both ends.
  const transfer = client.transfer as PreviewContextApi;
  const smoke = client.submission as PreviewContextApi;
  const transferServer = installContextServer("transfer-preview", "transfer-confirm");
  const transferPreview = await transfer.preview("campaign-a", profile);
  const smokeServer = installContextServer("smoke-submit-preview", "smoke-submit-confirm");
  const smokePreviewValue = await smoke.preview("campaign-b", profile);
  client.reset();
  await expect(transfer.confirm(transferPreview.preview_token)).rejects.toThrow("no longer active");
  await expect(smoke.confirm(smokePreviewValue.preview_token)).rejects.toThrow("no longer active");
  expect(transferServer.fetchMock).toHaveBeenCalled();
  expect(smokeServer.fetchMock).toHaveBeenCalled();
});
