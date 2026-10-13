import { act, render, renderHook, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import snapshot from "../../../tests/contracts/v1/workflow_api_success.json";
import {
  Mot3DFinalValidationTransitionApiError,
  parseMot3DFinalValidationTransitionPreview,
  parseMot3DFinalValidationTransitionResult,
  parseMot3DFinalValidationTransitionStatus,
} from "../api/clients/mot3dFinalValidationTransition";
import { Mot3DCampaignFlow } from "../features/campaign/Mot3DCampaignFlow";
import { useMot3DFinalValidationTransitionController } from "../features/campaign/controllers/useMot3DFinalValidationTransitionController";
const data = (id: string) =>
    structuredClone(
      (
        snapshot.cases.find((x) => x.id === id)!.body as {
          data: Record<string, unknown>;
        }
      ).data,
    ),
  status = () =>
    parseMot3DFinalValidationTransitionStatus(
      data("mot3d-final-validation-transition-status"),
    ),
  preview = () =>
    parseMot3DFinalValidationTransitionPreview(
      data("mot3d-final-validation-transition-preview"),
      { campaignId: "campaign-id", commit: "a".repeat(40) },
    ),
  result = () =>
    parseMot3DFinalValidationTransitionResult(
      data("mot3d-final-validation-transition-confirm"),
      "campaign-id",
    ),
  flow = (x: Record<string, unknown>) =>
    ({
      phase: "idle",
      status: null,
      preview: null,
      result: null,
      error: "",
      errorPhase: null,
      refresh: vi.fn(),
      review: vi.fn(),
      confirm: vi.fn(),
      reset: vi.fn(),
      ...x,
    }) as never,
  base = {
    stage: "final_validation_input_generation",
    connected: true,
    discovery: {} as never,
    transition: {} as never,
    preliminary: {} as never,
    onConnectZeus: vi.fn(),
    onViewJobs: vi.fn(),
  };
describe("final validation transition", () => {
  it("strictly decodes contracts and mutations", () => {
    expect(status().validation.result_artifacts).toBe(101);
    expect(preview().artifacts.transfer_files).toBe(107);
    expect(result().artifacts.synchronized).toBe(102);
    for (const mutate of [
      (v: Record<string, unknown>) => (v.from_stage = "finalist_selection"),
      (v: Record<string, unknown>) =>
        ((v.effects as Record<string, unknown>).submit_final_validation = true),
      (v: Record<string, unknown>) =>
        ((v.artifacts as Record<string, unknown>).transfer_files = 106),
    ]) {
      const v = data("mot3d-final-validation-transition-preview");
      mutate(v);
      expect(() =>
        parseMot3DFinalValidationTransitionPreview(v, { campaignId: "campaign-id", commit: "a".repeat(40) }),
      ).toThrow();
    }
    for (const mutate of [
      (v: Record<string, unknown>) =>
        ((
          v.final_validation_input_generation as Record<string, unknown>
        ).status = "invented"),
      (v: Record<string, unknown>) =>
        ((v.validation as Record<string, unknown>).status = "invented"),
      (v: Record<string, unknown>) =>
        ((v.campaign as Record<string, unknown>).stage = ["final_validation"]),
      (v: Record<string, unknown>) =>
        ((v.scheduler as Record<string, unknown>).completed_array_tasks = 39),
      (v: Record<string, unknown>) => (v.next_action = "wait"),
    ]) {
      const v = data("mot3d-final-validation-transition-status");
      mutate(v);
      expect(() => parseMot3DFinalValidationTransitionStatus(v)).toThrow();
    }
  });
  it("renders seed disclosure, zero-submit review and truthful success", () => {
    const view = render(
      <Mot3DCampaignFlow
        {...base}
        finalValidationTransition={flow({
          phase: "review",
          status: status(),
          preview: preview(),
        })}
      />,
    );
    expect(
      screen.getByRole("heading", { name: /Verify, synchronize/ }),
    ).toHaveFocus();
    expect(screen.getByText("3035–3054")).toBeVisible();
    expect(screen.getByText("Zeeman 3035 → 2D-MOT 43035")).not.toBeVisible();
    expect(screen.getByText("None")).toBeVisible();
    view.rerender(
      <Mot3DCampaignFlow
        {...base}
        finalValidationTransition={flow({ phase: "success", result: result() })}
      />,
    );
    expect(screen.getByText(/no Final Validation result yet/)).toBeVisible();
  });
  it("guards stale context, duplicate actions, and ambiguous confirmation", async () => {
    const profile={host:"zeus.technion.ac.il" as const,authentication:"ssh-key-or-agent" as const,username:"tal.noa",project_directory:"/home/tal.noa/project"},snap={connection_status:"connected" as const,profile,remote:{project_directory:profile.project_directory,git_commit:"a".repeat(40),branch:"main",dirty:false},scheduler:{status:"available" as const,queried_at:"2026-10-12T00:00:00Z",jobs:[]}};
    let resolve!:(v:ReturnType<typeof status>)=>void;const api={status:vi.fn(()=>new Promise<ReturnType<typeof status>>(done=>{resolve=done})),preview:vi.fn(async()=>preview()),confirm:vi.fn(async()=>{throw new Error("unknown")}),reset:vi.fn()};
    const hook=renderHook(({snapshot})=>useMot3DFinalValidationTransitionController({campaignId:"campaign-id",snapshot,enabled:true,api}),{initialProps:{snapshot:snap}});act(()=>{void hook.result.current.refresh();void hook.result.current.refresh()});expect(api.status).toHaveBeenCalledOnce();hook.rerender({snapshot:{...snap,remote:{...snap.remote,git_commit:"b".repeat(40)}}});await act(async()=>resolve(status()));expect(hook.result.current.status).toBeNull();
  });
  it("consumes an ambiguous confirmation and never retries", async () => {
    const profile={host:"zeus.technion.ac.il" as const,authentication:"ssh-key-or-agent" as const,username:"tal.noa",project_directory:"/home/tal.noa/project"},snapshot={connection_status:"connected" as const,profile,remote:{project_directory:profile.project_directory,git_commit:"a".repeat(40),branch:"main",dirty:false},scheduler:{status:"available" as const,queried_at:"2026-10-12T00:00:00Z",jobs:[]}};
    const api={status:vi.fn(async()=>status()),preview:vi.fn(async()=>preview()),confirm:vi.fn(async()=>{throw new Mot3DFinalValidationTransitionApiError("final_validation_transition_outcome_unknown","Unknown")}),reset:vi.fn()};
    const hook=renderHook(()=>useMot3DFinalValidationTransitionController({campaignId:"campaign-id",snapshot,enabled:true,api}));await act(async()=>hook.result.current.refresh());await act(async()=>hook.result.current.review());await act(async()=>{void hook.result.current.confirm();void hook.result.current.confirm()});expect(api.confirm).toHaveBeenCalledOnce();expect(hook.result.current.errorPhase).toBe("confirm_unknown");await act(async()=>hook.result.current.confirm());expect(api.confirm).toHaveBeenCalledOnce();
  });
});
