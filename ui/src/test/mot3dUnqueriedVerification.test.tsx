import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";
import { parseMot3DDiscoveryStatus } from "../api/clients/mot3dDiscovery";
import { Mot3DCampaignFlow } from "../features/campaign/Mot3DCampaignFlow";
import { Mot3DDiscoveryStage } from "../features/campaign/Mot3DDiscoveryStage";

type Props = ComponentProps<typeof Mot3DCampaignFlow>;

describe("unqueried 3D verification after opening or reopening a campaign", () => {
  it("distinguishes an unchecked Discovery submission from a verified absence of jobs", async () => {
    const flow = {
      state: "idle",
      status: null,
      preview: null,
      result: null,
      error: "",
      refresh: vi.fn(),
      review: vi.fn(),
      confirm: vi.fn(),
      reset: vi.fn(),
    } as unknown as Props["discovery"];
    const props = {
      visible: true,
      connected: true,
      preparationReady: true,
      flow,
      onConnectZeus: vi.fn(),
      onViewJobs: vi.fn(),
    };
    const view = render(<Mot3DDiscoveryStage {...props} />);
    expect(screen.getByText("Check Discovery submission status")).toBeVisible();
    expect(
      screen.queryByText("Discovery is prepared, but not submitted"),
    ).not.toBeInTheDocument();
    expect(flow.refresh).not.toHaveBeenCalled();
    expect(flow.review).not.toHaveBeenCalled();
    expect(flow.confirm).not.toHaveBeenCalled();
    await userEvent.click(
      screen.getByRole("button", { name: "Check Zeus status" }),
    );
    expect(flow.refresh).toHaveBeenCalledTimes(1);
    const status = parseMot3DDiscoveryStatus({
      source: "zeus",
      queried_at: "2026-10-23T00:00:00Z",
      campaign: { id: "campaign-id", name: "Campaign", stage: "discovery" },
      submission: {
        status: "not_submitted",
        chain: { angled_donut: [], single_pass: [] },
      },
      next_action: "review_submission",
      local_sync: { status: "not_synchronized" },
    });
    view.rerender(
      <Mot3DDiscoveryStage {...props} flow={{ ...flow, status }} />,
    );
    expect(
      screen.getByText("Discovery is prepared, but not submitted"),
    ).toBeVisible();
    expect(
      screen.queryByText("Check Discovery submission status"),
    ).not.toBeInTheDocument();
    expect(flow.refresh).toHaveBeenCalledTimes(1);
    expect(flow.review).not.toHaveBeenCalled();
    expect(flow.confirm).not.toHaveBeenCalled();
  });

  it.each([
    ["discovery", "transition", "Discovery"],
    ["refinement", "preliminaryTransition", "preliminary-check"],
    ["closure", "refinementTransition", "Refinement"],
  ] as const)(
    "does not infer completion from an idle %s controller",
    async (stage, key, name) => {
      const flow = {
        state: "idle",
        status: null,
        preview: null,
        result: null,
        error: "",
        refresh: vi.fn(),
        review: vi.fn(),
        confirm: vi.fn(),
        reset: vi.fn(),
      };
      const props = {
        stage,
        connected: true,
        discovery: flow,
        transition: flow,
        preliminary: flow,
        [key]: flow,
        onConnectZeus: vi.fn(),
        onViewJobs: vi.fn(),
      } as unknown as Props;
      render(<Mot3DCampaignFlow {...props} />);

      expect(
        screen.getByText(`Check ${name} verification status`),
      ).toBeVisible();
      expect(
        screen.queryByText(/The scheduler has finished/),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByText(/have not happened yet/),
      ).not.toBeInTheDocument();
      expect(
        screen.getByText(/Checking status does not submit jobs/),
      ).toBeVisible();
      expect(flow.refresh).not.toHaveBeenCalled();
      expect(flow.review).not.toHaveBeenCalled();
      expect(flow.confirm).not.toHaveBeenCalled();

      await userEvent.click(
        screen.getByRole("button", {
          name: `Verify ${name} results`,
        }),
      );
      expect(flow.refresh).toHaveBeenCalledTimes(1);
      expect(flow.review).not.toHaveBeenCalled();
      expect(flow.confirm).not.toHaveBeenCalled();
    },
  );
});
