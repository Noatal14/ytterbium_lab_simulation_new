import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import contracts from "./teamContractFixture";
import { App } from "../App";
import * as transitionObserver from "../features/campaign/shared/observeCampaignTransition";
import type { CanonicalTransitionCommit } from "../features/campaign/shared/observeCampaignTransition";
import { campaignFixture } from "./campaignFixture";
import type { Campaign, CampaignApi } from "../api/clients/campaign";
import type { ZeusSnapshot } from "../api/schema/domain";

const definitions = [
  ["mot3d-transition", "discovery", "preliminary_check", "mot3d-transition-heading", "Synchronize and prepare", "mot3d-preliminary-heading"],
  ["mot3d-preliminary-transition", "preliminary_check", "refinement", "mot3d-preliminary-transition-heading", "Synchronize and prepare Refinement", "mot3d-refinement-submit-heading"],
  ["mot3d-refinement-transition", "refinement", "closure", "mot3d-refinement-transition-heading", "Synchronize and prepare Closure", "mot3d-closure-submit-heading"],
  ["mot3d-closure-transition", "closure", "finalist_selection", "mot3d-closure-transition-heading", "Synchronize and prepare finalist selection", "mot3d-finalist-submit-heading"],
  ["mot3d-finalist-transition", "finalist_selection", "final_validation_input_generation", "mot3d-finalist-transition-heading", "Synchronize and prepare validation inputs", "mot3d-final-input-heading"],
  ["mot3d-final-validation-transition", "final_validation_input_generation", "final_validation", "final-validation-transition-heading", "Verify, synchronize, and prepare Final Validation", "mot3d-final-validation-submit-heading"],
  ["mot3d-final-validation-completion", "final_validation", "complete", "final-validation-completion-heading", "Synchronize and publish final report", "final-validation-completion-heading"],
] as const;
const profile = { host: "zeus.technion.ac.il", username: "tal.noa", project_directory: "/home/tal.noa/ytterbium_lab_simulation_ui", authentication: "ssh-key-or-agent" } as const;
const snapshot: ZeusSnapshot = { connection_status: "connected", profile, remote: { project_directory: profile.project_directory, git_commit: "a".repeat(40), branch: "main", dirty: false }, scheduler: { status: "available", queried_at: "2026-10-12T00:00:00Z", jobs: [] } };
const envelope = (data: unknown) => new Response(JSON.stringify({ api_version: 1, data }), { status: 200 });
const campaign = (stage: string): Campaign => ({ ...campaignFixture, id: "campaign-id", family: "mot_3d", kind: "mot_3d_campaign_v2", name: "mot_3d_contract", path: "data/optimization/mot_3d/contract", stage, git_commit: "a".repeat(40), progress: [], warnings: [], next_plan: null, families: ["angled_donut", "single_pass"] });
const deferred = <T,>() => { let resolve!: (value: T) => void; let reject!: (error: Error) => void; const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

async function setup(definition: readonly [string, string, string, string, string, string] = definitions[0], read?: () => Promise<Campaign>, extension = false) {
  const [prefix, from, to, section, confirm] = definition;
  const rows = contracts.cases.filter((c) => c.id.startsWith(prefix + "-"));
  const posts: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (path: string, init?: RequestInit) => {
    if (path === "/api/v1/session") return envelope({ csrf_token: "csrf-token" });
    let match = rows.find((r) => r.path === path);
    if (prefix === "mot3d-preliminary-transition" && path === "/api/v1/zeus/submissions/mot-3d-preliminary-check/status") match = contracts.cases.find((r) => r.id === "mot3d-preliminary-status");
    if (!match || init?.method !== "POST") throw new Error("Unmocked API route: " + path);
    posts.push(path);
    const body = structuredClone(match.body) as { data: Record<string, unknown> };
    if (prefix === "mot3d-preliminary-transition" && path === "/api/v1/zeus/submissions/mot-3d-preliminary-check/status") {
      body.data.submission = { status: "completed_success_unvalidated", chain: (rows.find((r) => r.id === prefix + "-status")!.body.data as Record<string, unknown>).preliminary && ((rows.find((r) => r.id === prefix + "-status")!.body.data as Record<string, unknown>).preliminary as Record<string, unknown>).chain };
      body.data.next_action = "validate_outputs";
      body.data.scheduler = { ...(body.data.scheduler as Record<string, unknown>), completed_array_tasks: 6, completed_merge_jobs: 2 };
    }
    if (prefix === "mot3d-final-validation-completion" && path.endsWith("/status")) {
      const d = body.data;
      (d.campaign as Record<string, unknown>).stage = "final_validation";
      (d.final_validation as Record<string, unknown>).status = "ready_to_advance";
      d.completion = { status: "not_completed", detail: null };
      d.local_sync = { status: "not_synchronized", receipt_sha256: null };
      d.next_action = "review_completion";
    }
    if (extension && path.endsWith("/preview")) {
      const completion = body.data.completion as Record<string, unknown>;
      completion.outcome = "final_validation_extension_required";
      for (const family of completion.families as Record<string, unknown>[]) {
        family.bootstrap_95_ci = [0.48, 0.52]; family.ci_half_width = (0.52 - 0.48) / 2; family.precision_target_met = false;
      }
    }
    if (extension && path.endsWith("/confirm")) { body.data.status = "final_validation_extension_required"; body.data.stage = "final_validation_extension_required"; }
    return envelope(body.data);
  }));
  const get = vi.fn(async () => get.mock.calls.length === 1 ? campaign(from) : read ? read() : campaign(to));
  const api: CampaignApi = { list: async () => ({ campaigns: [campaign(from)], invalid_count: 0, total: 1 }), get };
  const user = userEvent.setup();
  const rendered = render(<App api={api} zeus={{ snapshot: async () => snapshot }} />);
  await user.click(screen.getByRole("link", { name: "Zeus connection" }));
  await user.type(screen.getByLabelText("Technion username"), "tal.noa");
  await user.click(screen.getByRole("button", { name: "Connect and check status" }));
  await user.click(await screen.findByRole("button", { name: "Inspect campaign" }));
  if (prefix === "mot3d-preliminary-transition") await user.click(screen.getByRole("button", { name: "Check Zeus status" }));
  await waitFor(() => expect(document.querySelector(`section[aria-labelledby="${section}"]`)).toBeVisible());
  const region = document.querySelector(`section[aria-labelledby="${section}"]`) as HTMLElement;
  expect(region).toBeVisible();
  await user.click(within(region).getByRole("button"));
  await user.click(await within(region).findByRole("button", { name: /^Review/ }));
  await user.click(await within(region).findByRole("button", { name: extension ? "Record extension required" : confirm }));
  return { ...rendered, user, get, api, posts, region };
}

describe("canonical campaign refresh after a verified 3D transition", () => {
  it.each(definitions)("refreshes canonical stage after %s without submitting next-stage work", async (...definition) => {
    const { get, posts } = await setup(definition);
    await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(document.querySelector(`section[aria-labelledby="${definition[5]}"]`)).toBeVisible());
    expect(posts).toHaveLength(definition[0] === "mot3d-preliminary-transition" ? 4 : 3);
    expect(posts.filter((p) => p.endsWith("/confirm"))).toHaveLength(1);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("refreshes the canonical extension-required outcome without submitting an extension", async () => {
    const { get, posts } = await setup(definitions[6], async () => campaign("final_validation_extension_required"), true);
    await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("Final Validation extension is required")).toBeVisible();
    expect(posts).toHaveLength(3);
    expect(screen.queryByText("Campaign stage verification is required")).not.toBeInTheDocument();
  });

  it("keeps the old stage through pending/failed GET and retries only the canonical read", async () => {
    const first = deferred<Campaign>(); const second = deferred<Campaign>(); let reads = 0;
    const { user, get, posts } = await setup(definitions[0], () => ++reads === 1 ? first.promise : second.promise);
    expect(screen.getByText(/Refreshing campaign details/)).toBeVisible();
    expect(document.querySelector('#mot3d-preliminary-heading')).not.toBeInTheDocument();
    await act(async () => first.reject(new Error("network unavailable")));
    expect(await screen.findByRole("alert")).toHaveTextContent("previous verified stage is still shown");
    await user.dblClick(screen.getByRole("button", { name: "Refresh campaign details" }));
    expect(get).toHaveBeenCalledTimes(3);
    expect(document.querySelector('#mot3d-preliminary-heading')).not.toBeInTheDocument();
    await act(async () => second.resolve(campaign("preliminary_check")));
    await waitFor(() => expect(document.querySelector('#mot3d-preliminary-heading')).toBeVisible());
    expect(posts).toHaveLength(3);
  });

  it.each(["id", "stage", "path", "git_commit", "family", "trust"] as const)("rejects a canonical GET with changed %s", async (key) => {
    const wrong = { ...campaign("preliminary_check"), [key]: "foreign-value" };
    const { posts } = await setup(definitions[0], async () => wrong);
    expect(await screen.findByRole("alert")).toHaveTextContent("Campaign stage verification is required");
    expect(document.querySelector('#mot3d-preliminary-heading')).not.toBeInTheDocument();
    expect(posts).toHaveLength(3);
  });

  it("retires a pending refresh when navigating away", async () => {
    const pending = deferred<Campaign>(); const { user, posts } = await setup(definitions[0], () => pending.promise);
    await user.click(screen.getByRole("link", { name: "Home" }));
    await act(async () => pending.resolve(campaign("preliminary_check")));
    expect(screen.getByRole("heading", { name: "Run or inspect a campaign" })).toBeVisible();
    expect(document.querySelector('#mot3d-preliminary-heading')).not.toBeInTheDocument();
    expect(posts).toHaveLength(3);
  });

  it("retires a pending refresh when the campaign API changes", async () => {
    const pending = deferred<Campaign>(); const { rerender, posts } = await setup(definitions[0], () => pending.promise);
    const nextApi: CampaignApi = { list: async () => ({ campaigns: [], invalid_count: 0, total: 0 }), get: vi.fn(async () => campaign("preliminary_check")) };
    rerender(<App api={nextApi} zeus={{ snapshot: async () => snapshot }} />);
    await act(async () => pending.resolve(campaign("preliminary_check")));
    expect(document.querySelector('#mot3d-preliminary-heading')).not.toBeInTheDocument();
    expect(nextApi.get).not.toHaveBeenCalled();
    expect(posts).toHaveLength(3);
  });
  it("retires retained transition callbacks after navigation and same-ID reopening", async () => {
    const original = transitionObserver.observeCampaignTransition;
    const callbacks: ((result: CanonicalTransitionCommit) => void)[] = [];
    vi.spyOn(transitionObserver, "observeCampaignTransition").mockImplementation((api, callback) => { callbacks.push(callback); return original(api, callback); });
    const pending = deferred<Campaign>();
    const { user, get, posts } = await setup(definitions[0], () => pending.promise);
    const retired = callbacks[callbacks.length - 1];
    await user.click(screen.getByRole("link", { name: "Home" }));
    get.mockImplementation(async () => campaign("discovery"));
    await user.click(await screen.findByRole("button", { name: "Open campaign" }));
    await waitFor(() => expect(document.querySelector('#mot3d-transition-heading')).toBeVisible());
    const count = get.mock.calls.length;
    act(() => retired({ campaign_id: "campaign-id", stage: "refinement", submitted_to_zeus: false, simulation_started: false, local_sync: { status: "synchronized", receipt_sha256: "b".repeat(64) } }));
    expect(get).toHaveBeenCalledTimes(count);
    await act(async () => pending.resolve(campaign("preliminary_check")));
    expect(document.querySelector('#mot3d-preliminary-heading')).not.toBeInTheDocument();
    const current = callbacks[callbacks.length - 1];
    get.mockImplementation(async () => campaign("preliminary_check"));
    act(() => current({ campaign_id: "campaign-id", stage: "preliminary_check", submitted_to_zeus: false, simulation_started: false, local_sync: { status: "synchronized", receipt_sha256: "c".repeat(64) } }));
    await waitFor(() => expect(document.querySelector('#mot3d-preliminary-heading')).toBeVisible());
    expect(posts).toHaveLength(3);
  });

  it("publishes only the newest canonical read when distinct receipt observations overlap", async () => {
    const original = transitionObserver.observeCampaignTransition;
    let committed!: (result: CanonicalTransitionCommit) => void;
    vi.spyOn(transitionObserver, "observeCampaignTransition").mockImplementation((api, callback) => { committed = callback; return original(api, callback); });
    const old = deferred<Campaign>(); const latest = deferred<Campaign>(); let reads = 0;
    const { get, posts } = await setup(definitions[0], () => ++reads === 1 ? old.promise : latest.promise);
    const result: CanonicalTransitionCommit = { campaign_id: "campaign-id", stage: "refinement", submitted_to_zeus: false, simulation_started: false, local_sync: { status: "synchronized", receipt_sha256: "d".repeat(64) } };
    act(() => { committed(result); committed(result); });
    expect(get).toHaveBeenCalledTimes(3);
    await act(async () => latest.resolve(campaign("refinement")));
    await waitFor(() => expect(document.querySelector('#mot3d-refinement-submit-heading')).toBeVisible());
    await act(async () => old.resolve(campaign("preliminary_check")));
    expect(document.querySelector('#mot3d-refinement-submit-heading')).toBeVisible();
    expect(posts).toHaveLength(3);
  });

});
