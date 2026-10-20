import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Mot3DDiscoveryLifecycle } from "../api/clients/mot3dDiscovery";
import { Mot3DDiscoveryStage } from "../features/campaign/Mot3DDiscoveryStage";
import type { useMot3DDiscoveryController } from "../features/campaign/controllers/useMot3DDiscoveryController";

const populatedChain = {
  angled_donut: ["100[].zeus-master", "101[].zeus-master"],
  single_pass: [
    "200[].zeus-master",
    "201[].zeus-master",
    "202[].zeus-master",
  ],
};

function terminalFlow(lifecycle: Mot3DDiscoveryLifecycle) {
  const chain =
    lifecycle === "outcome_unknown"
      ? { angled_donut: [], single_pass: [] }
      : populatedChain;
  return {
    state: "terminal",
    status: {
      source: "zeus",
      queried_at: "2026-10-11T12:00:00+00:00",
      campaign: {
        id: "campaign-id",
        name: "mot_3d_run",
        stage: "discovery",
      },
      submission: { status: lifecycle, chain },
      next_action: "inspect_zeus",
      local_sync: { status: "not_synchronized" },
    },
    preview: null,
    result: null,
    error: "",
    refresh: vi.fn(),
    review: vi.fn(),
    confirm: vi.fn(),
    reset: vi.fn(),
  } as unknown as ReturnType<typeof useMot3DDiscoveryController>;
}

describe("3D Discovery terminal states", () => {
  it.each([
    "held",
    "completed_failed",
    "status_unknown",
    "outcome_unknown",
  ] satisfies Mot3DDiscoveryLifecycle[])(
    "renders %s only as an action-required state",
    (lifecycle) => {
      render(
        <Mot3DDiscoveryStage
          visible
          connected
          flow={terminalFlow(lifecycle)}
          onConnectZeus={vi.fn()}
          onViewJobs={vi.fn()}
        />,
      );

      expect(screen.getByRole("alert")).toBeInTheDocument();
      expect(
        screen.getByText("Manual verification required"),
      ).toBeInTheDocument();
      expect(
        screen.queryByText("Discovery is tracked on Zeus"),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByText(/No action is needed while the arrays/i),
      ).not.toBeInTheDocument();
    },
  );
});


it("shows the exact reviewed Discovery reservations and per-family workload", () => {
  const flow = {...terminalFlow("not_submitted"), state: "review", status: null, preview: {
    campaign: {name: "disposable"}, chain: {families: []}, remote: {host: "zeus.technion.ac.il", branch: "reviewed", commit: "a".repeat(40)},
    resources: {array: {ncpus_per_task: 4, memory_gb_per_task: 4, walltime: "01:00:00", vnode: "gd002"}},
    science: {total_trials: 24, input_ensembles: 12, particles_per_ensemble: 1, total_particles_per_trial: 12, npools: 4, dt_s: 1e-5, t_max_s: 0.05, solver: "RK4StHybridCustom", final_trial_targets: {angled_donut: [4,4,4], single_pass: [4,4,4]}},
  }} as unknown as ReturnType<typeof useMot3DDiscoveryController>;
  render(<Mot3DDiscoveryStage visible connected flow={flow} onConnectZeus={vi.fn()} onViewJobs={vi.fn()} />);
  expect(screen.getByText("4 CPU cores · 4 GiB · 01:00:00")).toBeVisible();
  expect(screen.getByText("gd002")).toBeVisible();
  expect(screen.getByText("12 atoms · 4 worker pools")).toBeVisible();
  expect(screen.getByText("2 arrays × 3 tasks · final trial targets per worker: 4 / 4 / 4")).toBeVisible();
  expect(screen.getByText("3 arrays × 3 tasks · final trial targets per worker: 4 / 4 / 4")).toBeVisible();
});


it("requires transfer before a new Discovery review while preserving read-only recovery", () => {
  const flow = {...terminalFlow("not_submitted"), state: "idle", status: null} as unknown as ReturnType<typeof useMot3DDiscoveryController>;
  const view = render(<Mot3DDiscoveryStage visible connected preparationReady={false} flow={flow} onConnectZeus={vi.fn()} onViewJobs={vi.fn()} />);
  expect(screen.getByText("Prepare this campaign on Zeus first")).toBeVisible();
  expect(screen.getByRole("button", {name: "Review Discovery jobs"})).toBeDisabled();
  expect(screen.getByRole("button", {name: "Check Zeus status"})).toBeEnabled();
  expect(flow.review).not.toHaveBeenCalled();
  view.rerender(<Mot3DDiscoveryStage visible connected preparationReady flow={flow} onConnectZeus={vi.fn()} onViewJobs={vi.fn()} />);
  expect(screen.getByRole("button", {name: "Review Discovery jobs"})).toBeEnabled();
});

it("withholds an old confirmation when transfer authority is lost", () => {
  const flow = {...terminalFlow("not_submitted"), state: "review", preview: {preview_token: "old"}} as unknown as ReturnType<typeof useMot3DDiscoveryController>;
  render(<Mot3DDiscoveryStage visible connected preparationReady={false} flow={flow} onConnectZeus={vi.fn()} onViewJobs={vi.fn()} />);
  expect(screen.queryByRole("button", {name: "Submit Discovery to Zeus"})).not.toBeInTheDocument();
  expect(flow.confirm).not.toHaveBeenCalled();
});
