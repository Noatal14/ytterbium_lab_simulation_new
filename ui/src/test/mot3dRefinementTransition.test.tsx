import { act, render, renderHook, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  parseMot3DRefinementTransitionPreview,
  parseMot3DRefinementTransitionResult,
  parseMot3DRefinementTransitionStatus,
} from "../api/clients/mot3dRefinementTransition";
import { Mot3DCampaignFlow } from "../features/campaign/Mot3DCampaignFlow";
import { useMot3DRefinementTransitionController } from "../features/campaign/controllers/useMot3DRefinementTransitionController";
const chain = {
  dependency: "afterok within each family",
  families: [
    {
      id: "angled_donut",
      array_job_id: "610[].zeus-master",
      merge_job_id: "611.zeus-master",
    },
    {
      id: "single_pass",
      array_job_id: "612[].zeus-master",
      merge_job_id: "613.zeus-master",
    },
  ],
};
const status = (o: Record<string, unknown> = {}) => ({
  source: "zeus",
  queried_at: "2026-10-12T12:00:00Z",
  campaign: { id: "campaign-id", name: "Campaign", stage: "refinement" },
  refinement: { status: "ready_to_advance", chain },
  scheduler: {
    expected_array_tasks: 6,
    expected_merge_jobs: 2,
    completed_array_tasks: 6,
    completed_merge_jobs: 2,
  },
  validation: {
    status: "valid",
    result_artifacts: 200,
    expected_result_artifacts: 200,
    reason_code: null,
  },
  transition: { status: "not_prepared" },
  next_action: "review_transition",
  local_sync: { status: "not_synchronized", receipt_sha256: null },
  ...o,
});
const preview = {
  preview_token: "token",
  expires_in_seconds: 300,
  campaign: { id: "campaign-id", name: "Campaign", git_commit: "a".repeat(40) },
  from_stage: "refinement",
  to_stage: "closure",
  refinement: {
    result_artifacts: 200,
    expected_result_artifacts: 200,
    families: ["angled_donut", "single_pass"],
    evidence_sha256: "b".repeat(64),
  },
  artifacts: {
    synchronize: { result_files: 200, submission_receipts: 1 },
    create: { selection_files: 2, job_files: 4 },
    update: ["campaign.json"],
    transfer_files: 208,
  },
  effects: {
    synchronize_refinement: true,
    prepare_closure: true,
    submit_closure: false,
    start_simulation: false,
    overwrite_existing: false,
  },
};
const result = {
  status: "closure_prepared",
  campaign_id: "campaign-id",
  stage: "closure",
  artifacts: {
    synchronized: 201,
    created: 6,
    updated: 1,
    bundle_sha256: "c".repeat(64),
  },
  submitted_to_zeus: false,
  simulation_started: false,
  local_sync: { status: "synchronized", receipt_sha256: "d".repeat(64) },
};
const profile = {
  host: "zeus.technion.ac.il" as const,
  username: "tal.noa",
  project_directory: "/home/tal.noa/ytterbium_lab_simulation_new",
  authentication: "ssh-key-or-agent" as const,
};
const snapshot = {
  connection_status: "connected" as const,
  profile,
  remote: {
    project_directory: profile.project_directory,
    git_commit: "a".repeat(40),
    branch: "main",
    dirty: false,
  },
  scheduler: {
    status: "available" as const,
    queried_at: "2026-10-12T12:00:00Z",
    jobs: [],
  },
};
describe("3D Refinement transition", () => {
  it("accepts ready, recovery, prepared, invalid, and valid-unknown matrices", () => {
    expect(parseMot3DRefinementTransitionStatus(status()).next_action).toBe(
      "review_transition",
    );
    expect(
      parseMot3DRefinementTransitionStatus(
        status({
          refinement: { status: "closure_prepared", chain },
          transition: { status: "closure_prepared" },
          next_action: "synchronize_results",
        }),
      ).next_action,
    ).toBe("synchronize_results");
    expect(
      parseMot3DRefinementTransitionStatus(
        status({
          campaign: { id: "campaign-id", name: "Campaign", stage: "closure" },
          refinement: { status: "closure_prepared", chain },
          transition: { status: "closure_prepared" },
          next_action: "open_closure",
          local_sync: {
            status: "synchronized",
            receipt_sha256: "d".repeat(64),
          },
        }),
      ).next_action,
    ).toBe("open_closure");
    expect(
      parseMot3DRefinementTransitionStatus(
        status({
          refinement: { status: "completed_success_unvalidated", chain },
          validation: {
            status: "scientifically_invalid",
            result_artifacts: 0,
            expected_result_artifacts: 200,
            reason_code: "summary_mismatch",
          },
          next_action: "inspect_zeus",
        }),
      ).validation.status,
    ).toBe("scientifically_invalid");
    expect(
      parseMot3DRefinementTransitionStatus(
        status({
          refinement: { status: "outcome_unknown", chain },
          next_action: "inspect_zeus",
        }),
      ).validation.status,
    ).toBe("valid");
  });
  it.each([
    { local_sync: { status: "synchronized", receipt_sha256: "d".repeat(64) } },
    { refinement: { status: "partial", chain }, next_action: "inspect_zeus" },
    {
      validation: {
        status: "scientifically_invalid",
        result_artifacts: 1,
        expected_result_artifacts: 200,
        reason_code: "summary_mismatch",
      },
      next_action: "inspect_zeus",
    },
    {
      scheduler: {
        expected_array_tasks: 6,
        expected_merge_jobs: 2,
        completed_array_tasks: 5,
        completed_merge_jobs: 2,
      },
    },
  ])("rejects impossible matrices %#", (o) =>
    expect(() => parseMot3DRefinementTransitionStatus(status(o))).toThrow(),
  );
  it.each(["completed_array_tasks", "completed_merge_jobs"] as const)(
    "rejects nonnumeric and out-of-range original %s values",
    (field) => {
      const running = status({
        refinement: { status: "running", chain },
        scheduler: {
          expected_array_tasks: 6,
          expected_merge_jobs: 2,
          completed_array_tasks: 0,
          completed_merge_jobs: 0,
        },
        validation: {
          status: "not_started", result_artifacts: 0,
          expected_result_artifacts: 200, reason_code: null,
        },
        next_action: "wait",
      });
      for (const value of ["0", "1", false, true, null, undefined, [], {}, 0.5, -1, NaN, Infinity, 7]) {
        const scheduler = { ...running.scheduler, [field]: value };
        expect(() => parseMot3DRefinementTransitionStatus({ ...running, scheduler })).toThrow();
      }
      for (const value of [0, 1, field === "completed_array_tasks" ? 6 : 2]) {
        const scheduler = { ...running.scheduler, [field]: value };
        const parsed = parseMot3DRefinementTransitionStatus({ ...running, scheduler });
        expect(parsed.scheduler[field]).toBe(value);
        expect(typeof parsed.scheduler[field]).toBe("number");
      }
    },
  );
  it.each(["completed_array_tasks", "completed_merge_jobs"] as const)(
    "rejects a stringified terminal %s count",
    (field) => {
      const ready = status();
      expect(() => parseMot3DRefinementTransitionStatus({
        ...ready, scheduler: { ...ready.scheduler, [field]: String(ready.scheduler[field]) },
      })).toThrow();
    },
  );
  it("strictly decodes review and result", () => {
    expect(
      parseMot3DRefinementTransitionPreview(preview, "campaign-id").artifacts
        .transfer_files,
    ).toBe(208);
    expect(
      parseMot3DRefinementTransitionResult(result, "campaign-id").artifacts
        .synchronized,
    ).toBe(201);
    expect(() =>
      parseMot3DRefinementTransitionPreview(
        { ...preview, effects: { ...preview.effects, submit_closure: true } },
        "campaign-id",
      ),
    ).toThrow();
  });
  it("classifies valid unknown as terminal and suppresses stale responses", async () => {
    let resolve!: (v: any) => void;
    const api = {
      status: vi.fn(
        () =>
          new Promise((r) => {
            resolve = r;
          }),
      ),
      preview: vi.fn(),
      confirm: vi.fn(),
      reset: vi.fn(),
    };
    const hook = renderHook(
      ({ snap }) =>
        useMot3DRefinementTransitionController({
          campaignId: "campaign-id",
          snapshot: snap,
          enabled: true,
          api: api as any,
        }),
      { initialProps: { snap: snapshot } },
    );
    act(() => {
      void hook.result.current.refresh();
      void hook.result.current.refresh();
    });
    hook.rerender({
      snap: { ...snapshot, profile: { ...profile, username: "changed" } },
    });
    await act(async () =>
      resolve(
        status({
          refinement: { status: "outcome_unknown", chain },
          next_action: "inspect_zeus",
        }),
      ),
    );
    expect(hook.result.current.status).toBeNull();
    const terminal = {
      status: vi.fn(async () =>
        parseMot3DRefinementTransitionStatus(
          status({
            refinement: { status: "outcome_unknown", chain },
            next_action: "inspect_zeus",
          }),
        ),
      ),
      preview: vi.fn(),
      confirm: vi.fn(),
      reset: vi.fn(),
    };
    const second = renderHook(() =>
      useMot3DRefinementTransitionController({
        campaignId: "campaign-id",
        snapshot,
        enabled: true,
        api: terminal as any,
      }),
    );
    await act(async () => second.result.current.refresh());
    expect(second.result.current.state).toBe("terminal");
  });
  it("refreshes an active run into a scientifically ready state", async () => {
    const running = status({
      refinement: { status: "running", chain },
      scheduler: {
        expected_array_tasks: 6,
        expected_merge_jobs: 2,
        completed_array_tasks: 2,
        completed_merge_jobs: 0,
      },
      validation: {
        status: "not_started",
        result_artifacts: 0,
        expected_result_artifacts: 200,
        reason_code: null,
      },
      next_action: "wait",
    });
    const api = {
      status: vi
        .fn()
        .mockResolvedValueOnce(parseMot3DRefinementTransitionStatus(running))
        .mockResolvedValueOnce(parseMot3DRefinementTransitionStatus(status())),
      preview: vi.fn(),
      confirm: vi.fn(),
      reset: vi.fn(),
    };
    const hook = renderHook(() =>
      useMot3DRefinementTransitionController({
        campaignId: "campaign-id",
        snapshot,
        enabled: true,
        api: api as any,
      }),
    );
    await act(async () => hook.result.current.refresh());
    expect(hook.result.current.state).toBe("idle");
    await act(async () => hook.result.current.refresh());
    expect(hook.result.current.state).toBe("ready");
    expect(hook.result.current.status?.validation.status).toBe("valid");
  });
  it("keeps explicit monitoring actions available while Refinement is running", () => {
    const refresh = vi.fn();
    render(
      <Mot3DCampaignFlow
        stage="refinement"
        connected
        discovery={{} as any}
        transition={{} as any}
        preliminary={{} as any}
        preliminaryTransition={{} as any}
        refinement={{} as any}
        refinementTransition={{
          state: "idle",
          status: parseMot3DRefinementTransitionStatus(status({
            refinement: { status: "running", chain },
            scheduler: { expected_array_tasks: 6, expected_merge_jobs: 2, completed_array_tasks: 2, completed_merge_jobs: 0 },
            validation: { status: "not_started", result_artifacts: 0, expected_result_artifacts: 200, reason_code: null },
            next_action: "wait",
          })),
          preview: null,
          result: null,
          error: "",
          errorPhase: null,
          refresh,
          review: vi.fn(),
          confirm: vi.fn(),
          reset: vi.fn(),
        } as any}
        onConnectZeus={vi.fn()}
        onViewJobs={vi.fn()}
      />,
    );
    screen.getByRole("button", { name: "Refresh status" }).click();
    expect(refresh).toHaveBeenCalledOnce();
    expect(screen.getByRole("button", { name: "Open Zeus jobs" })).toBeVisible();
  });
  it("renders valid evidence, explicit no-job review, and Closure prepared truth", () => {
    const base = {
        stage: "refinement",
        connected: true,
        discovery: {} as any,
        transition: {} as any,
        preliminary: {} as any,
        preliminaryTransition: {} as any,
        refinement: {} as any,
        onConnectZeus: vi.fn(),
        onViewJobs: vi.fn(),
      },
      flow = (v: any, state = "ready", extra = {}) =>
        ({
          state,
          status: parseMot3DRefinementTransitionStatus(v),
          preview: null,
          result: null,
          error: "",
          errorPhase: null,
          refresh: vi.fn(),
          review: vi.fn(),
          confirm: vi.fn(),
          reset: vi.fn(),
          ...extra,
        }) as any;
    const unqueried = flow(status(), "idle", { status: null });
    const view = render(
      <Mot3DCampaignFlow {...base} refinementTransition={unqueried} />,
    );
    expect(screen.getByText("Check Refinement verification status")).toBeVisible();
    expect(unqueried.refresh).not.toHaveBeenCalled();
    expect(unqueried.review).not.toHaveBeenCalled();
    expect(unqueried.confirm).not.toHaveBeenCalled();
    view.rerender(
      <Mot3DCampaignFlow
        {...base}
        refinementTransition={flow(
          status({
            refinement: { status: "outcome_unknown", chain },
            next_action: "inspect_zeus",
          }),
          "terminal",
        )}
      />,
    );
    expect(
      screen.getByText(/All 200 artifacts passed validation/),
    ).toBeVisible();
    expect(screen.getByText(/Do not retry/)).toBeVisible();
    view.rerender(
      <Mot3DCampaignFlow
        {...base}
        refinementTransition={{ ...flow(status(), "review"), preview } as any}
      />,
    );
    expect(
      screen.getByText(/does not submit a job or start a simulation/),
    ).toBeVisible();
    view.rerender(
      <Mot3DCampaignFlow
        {...base}
        stage="closure"
        refinementTransition={
          {
            ...flow(
              status({
                campaign: {
                  id: "campaign-id",
                  name: "Campaign",
                  stage: "closure",
                },
                refinement: { status: "closure_prepared", chain },
                transition: { status: "closure_prepared" },
                next_action: "open_closure",
                local_sync: {
                  status: "synchronized",
                  receipt_sha256: "d".repeat(64),
                },
              }),
              "prepared",
            ),
            result,
          } as any
        }
      />,
    );
    expect(
      screen.getByText(/without submitting or starting a Closure job/),
    ).toBeVisible();
    expect(screen.queryByText("Check Refinement verification status")).not.toBeInTheDocument();
    expect(screen.queryByText(/have not happened yet/)).not.toBeInTheDocument();
  });
});
