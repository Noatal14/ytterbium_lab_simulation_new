import { describe, expect, it, vi } from "vitest";
import successSnapshot from "./teamContractFixture";
import {
  createMot3DClosureSubmissionApi,
  Mot3DClosureSubmissionApiError,
  parseMot3DClosureSubmissionPreview,
  parseMot3DClosureSubmissionResult,
  parseMot3DClosureSubmissionStatus,
} from "../api/clients/mot3dClosureSubmission";

const profile = { host: "zeus.technion.ac.il" as const, username: "tal.noa", project_directory: "/home/tal.noa/ytterbium_lab_simulation_ui", authentication: "ssh-key-or-agent" as const };
const data = (id: string) => structuredClone((successSnapshot.cases.find((entry) => entry.id === id)?.body as { data: Record<string, unknown> }).data);

describe("3D-MOT Closure submission contract", () => {
  it("strictly accepts the canonical status, review, and result", () => {
    expect(parseMot3DClosureSubmissionStatus(data("mot3d-closure-status"))).toMatchObject({ next_action: "review_submission" });
    expect(parseMot3DClosureSubmissionPreview(data("mot3d-closure-preview"), { campaignId: "campaign-id", profile })).toMatchObject({ stage: { id: "closure" } });
    expect(parseMot3DClosureSubmissionResult(data("mot3d-closure-confirm"), "campaign-id")).toMatchObject({ status: "submitted" });
  });

  it.each([
    ["status extra key", "mot3d-closure-status", (row: Record<string, unknown>) => { row.extra = true; }, "status"],
    ["wrong lifecycle action", "mot3d-closure-status", (row: Record<string, unknown>) => { row.next_action = "wait"; }, "status"],
    ["changed selection seed", "mot3d-closure-preview", (row: Record<string, unknown>) => { (row.science as Record<string, unknown>).selection_seed = 61001; }, "preview"],
    ["changed remote directory", "mot3d-closure-preview", (row: Record<string, unknown>) => { (row.remote as Record<string, unknown>).project_directory = "/tmp/project"; }, "preview"],
    ["missing effect", "mot3d-closure-preview", (row: Record<string, unknown>) => { delete (row.effects as Record<string, unknown>).submit_closure; }, "preview"],
    ["wrong result stage", "mot3d-closure-confirm", (row: Record<string, unknown>) => { row.stage = "refinement"; }, "result"],
  ])("rejects %s", (_label, id, mutate, parser) => {
    const row = data(id); mutate(row);
    expect(() => parser === "status" ? parseMot3DClosureSubmissionStatus(row) : parser === "preview" ? parseMot3DClosureSubmissionPreview(row, { campaignId: "campaign-id", profile }) : parseMot3DClosureSubmissionResult(row, "campaign-id")).toThrow(/Invalid/);
  });

  it("uses all three canonical routes and consumes the review token", async () => {
    const fetchMock = vi.fn(async (input: string | URL | Request) => {
      const path = typeof input === "string" ? input : String(input);
      const id = path.endsWith("/status") ? "mot3d-closure-status" : path.endsWith("/preview") ? "mot3d-closure-preview" : "mot3d-closure-confirm";
      return new Response(JSON.stringify({ api_version: 1, data: data(id) }), { status: id.endsWith("confirm") ? 201 : 200, headers: { "Content-Type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetchMock);
    const api = createMot3DClosureSubmissionApi(async () => "csrf");
    await api.status("campaign-id", profile);
    const preview = await api.preview("campaign-id", profile);
    await api.confirm(preview.preview_token);
    await expect(api.confirm(preview.preview_token)).rejects.toThrow(/no longer active/);
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it.each([
    ["transport loss", () => Promise.reject(new Error("connection lost"))],
    ["malformed success", () => Promise.resolve(new Response(JSON.stringify({ api_version: 1, data: { status: "submitted" } }), { status: 201 }))],
  ])("turns %s after confirm into an unknown outcome", async (_label, confirmation) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ api_version: 1, data: data("mot3d-closure-preview") }), { status: 200 })).mockImplementationOnce(confirmation));
    const api = createMot3DClosureSubmissionApi(async () => "csrf"), preview = await api.preview("campaign-id", profile);
    await expect(api.confirm(preview.preview_token)).rejects.toMatchObject({ code: "closure_submission_outcome_unknown" });
  });

  it("preserves a known deterministic confirmation rejection", async () => {
    const rejected = new Response(JSON.stringify({ error: { code: "confirmation_expired", message: "Review expired." } }), { status: 409 });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ api_version: 1, data: data("mot3d-closure-preview") }), { status: 200 })).mockResolvedValueOnce(rejected));
    const api = createMot3DClosureSubmissionApi(async () => "csrf"), preview = await api.preview("campaign-id", profile);
    await expect(api.confirm(preview.preview_token)).rejects.toEqual(expect.objectContaining<Partial<Mot3DClosureSubmissionApiError>>({ code: "confirmation_expired" }));
  });

  it("does not install a review context after reset during preview", async () => {
    let resolve!: (value: Response) => void;
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>((done) => { resolve = done; })));
    const api = createMot3DClosureSubmissionApi(async () => "csrf"), pending = api.preview("campaign-id", profile);
    await Promise.resolve();
    api.reset();
    resolve(new Response(JSON.stringify({ api_version: 1, data: data("mot3d-closure-preview") }), { status: 200 }));
    await expect(pending).rejects.toThrow(/stale/);
    await expect(api.confirm("mot3d-closure-token")).rejects.toThrow(/no longer active/);
  });
});
