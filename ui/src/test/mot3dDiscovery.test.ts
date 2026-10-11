import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  createMot3DDiscoveryApi,
  parseMot3DDiscoveryPreview,
  parseMot3DDiscoveryResult,
  parseMot3DDiscoveryStatus,
} from "../api/clients/mot3dDiscovery";
import type { ZeusSnapshot } from "../api/schema/domain";
import { useMot3DDiscoveryController } from "../features/campaign/controllers/useMot3DDiscoveryController";

const campaignId = "campaign-id";
const profile = {
  host: "zeus.technion.ac.il" as const,
  username: "tal.noa",
  project_directory: "/home/tal.noa/ytterbium_lab_simulation_new",
  authentication: "ssh-key-or-agent" as const,
};
const chain = {
  angled_donut: ["100[].zeus-master", "101[].zeus-master"],
  single_pass: ["200[].zeus-master", "201[].zeus-master", "202[].zeus-master"],
};
const preview = {
  preview_token: "token",
  expires_in_seconds: 300,
  campaign: { id: campaignId, name: "mot_3d_run", git_commit: "a".repeat(40) },
  stage: { id: "discovery", label: "Discovery" },
  chain: {
    families: [
      { id: "angled_donut", rounds: 2 },
      { id: "single_pass", rounds: 3 },
    ],
    arrays: 5,
    tasks_per_array: 3,
    dependency: "afterok within each family",
  },
  remote: {
    host: profile.host,
    project_directory: profile.project_directory,
    commit: "a".repeat(40),
    branch: "main",
    dirty: false,
  },
  effects: {
    submit_discovery_chain: true,
    submit_smoke: false,
    submit_later_stages: false,
    modify_campaign_files: false,
    record_submission_receipt: true,
  },
};
const status = {
  source: "zeus",
  queried_at: "2026-10-11T12:00:00+00:00",
  campaign: { id: campaignId, name: "mot_3d_run", stage: "discovery" },
  submission: { status: "running", chain },
  next_action: "wait",
  local_sync: { status: "not_synchronized" },
};
const result = {
  status: "submitted",
  campaign_id: campaignId,
  stage: "discovery",
  chain,
  submitted_at: "2026-10-11T12:00:00+00:00",
  local_sync: { status: "not_synchronized" },
};

describe("3D Discovery response contracts", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("accepts the exact canonical five-array contract", () => {
    expect(parseMot3DDiscoveryStatus(status).submission.status).toBe("running");
    expect(
      parseMot3DDiscoveryPreview(preview, { campaignId, profile }).chain.arrays,
    ).toBe(5);
    expect(
      parseMot3DDiscoveryResult(result, campaignId).chain.single_pass,
    ).toHaveLength(3);
  });

  it.each([
    { ...preview, extra: true },
    { ...preview, chain: { ...preview.chain, arrays: 7 } },
    { ...preview, effects: { ...preview.effects, submit_smoke: true } },
    {
      ...preview,
      remote: { ...preview.remote, project_directory: "/tmp/other" },
    },
    {
      ...preview,
      chain: {
        ...preview.chain,
        families: [...preview.chain.families].reverse(),
      },
    },
  ])("rejects drifted review payloads", (value) => {
    expect(() =>
      parseMot3DDiscoveryPreview(value, { campaignId, profile }),
    ).toThrow();
  });

  it.each([
    {
      ...status,
      submission: {
        status: "running",
        chain: { angled_donut: [], single_pass: [] },
      },
    },
    { ...status, submission: { ...status.submission, status: "mystery" } },
    { ...status, next_action: "review_submission" },
    { ...status, campaign: { ...status.campaign, stage: "screen" } },
  ])("rejects incoherent scheduler status", (value) => {
    expect(() => parseMot3DDiscoveryStatus(value)).toThrow();
  });

  it("binds confirm to a reviewed token and prevents duplicate confirmation", async () => {
    const responses = [preview, result];
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({ api_version: 1, data: responses.shift() }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
      ),
    );
    const api = createMot3DDiscoveryApi(async () => "csrf");
    const reviewed = await api.preview(campaignId, profile);
    await expect(api.confirm(reviewed.preview_token)).resolves.toMatchObject({
      status: "submitted",
    });
    await expect(api.confirm(reviewed.preview_token)).rejects.toThrow(
      "no longer active",
    );
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("suppresses a double-click while preview is pending", async () => {
    let resolve!: (value: typeof preview) => void;
    const pending = new Promise<typeof preview>((done) => {
      resolve = done;
    });
    const api = {
      status: vi.fn(),
      preview: vi.fn(() => pending),
      confirm: vi.fn(),
      reset: vi.fn(),
    } as unknown as ReturnType<typeof createMot3DDiscoveryApi>;
    const snapshot: ZeusSnapshot = {
      connection_status: "connected",
      profile,
      remote: {
        project_directory: profile.project_directory,
        git_commit: "a".repeat(40),
        branch: "main",
        dirty: false,
      },
      scheduler: {
        status: "available",
        queried_at: "2026-10-11T00:00:00Z",
        jobs: [],
      },
    };
    const { result: hook } = renderHook(() =>
      useMot3DDiscoveryController({ campaignId, snapshot, enabled: true, api }),
    );
    await act(async () => {
      void hook.current.review();
      void hook.current.review();
    });
    expect(api.preview).toHaveBeenCalledTimes(1);
    await act(async () => resolve(preview));
    expect(hook.current.state).toBe("review");
  });

  it("drops a stale response after the Zeus profile changes", async () => {
    let resolve!: (value: typeof status) => void;
    const pending = new Promise<typeof status>((done) => {
      resolve = done;
    });
    const api = {
      status: vi.fn(() => pending),
      preview: vi.fn(),
      confirm: vi.fn(),
      reset: vi.fn(),
    } as unknown as ReturnType<typeof createMot3DDiscoveryApi>;
    const snapshot: ZeusSnapshot = {
      connection_status: "connected",
      profile,
      remote: {
        project_directory: profile.project_directory,
        git_commit: "a".repeat(40),
        branch: "main",
        dirty: false,
      },
      scheduler: {
        status: "available",
        queried_at: "2026-10-11T00:00:00Z",
        jobs: [],
      },
    };
    const { result: hook, rerender } = renderHook(
      ({ value }) =>
        useMot3DDiscoveryController({
          campaignId,
          snapshot: value,
          enabled: true,
          api,
        }),
      { initialProps: { value: snapshot } },
    );
    await act(async () => {
      void hook.current.refresh();
    });
    rerender({
      value: { ...snapshot, profile: { ...profile, username: "other" } },
    });
    await act(async () => resolve(status));
    expect(hook.current.status).toBeNull();
    expect(hook.current.state).toBe("idle");
  });
});
