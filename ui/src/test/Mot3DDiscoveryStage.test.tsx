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
