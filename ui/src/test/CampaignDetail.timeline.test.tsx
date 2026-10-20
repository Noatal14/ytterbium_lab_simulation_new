/** Copy-only component regression. Scheduler transport is a labeled fixture. */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import success from "../../../tests/contracts/v1/workflow_api_success.json";
import { CampaignDetail } from "../features/campaign/CampaignDetail";
import {
  parseCampaign,
  parseSmokeLifecycle,
  parseZeusSnapshot,
} from "../api/schema/domain";
const data = (id: string) =>
  structuredClone(
    success.cases.find((row) => row.id === id)!.body.data,
  ) as Record<string, unknown>;
it("distinguishes absent local outputs from a confirmed running Zeus job", async () => {
  const campaign = parseCampaign({
    ...data("campaign-detail"),
    progress: [
      { stage: "smoke", completed: 0, expected: 1, status: "not-started" },
    ],
  });
  const raw = data("smoke-status");
  raw.campaign = { id: campaign.id, name: campaign.name, stage: "smoke" };
  raw.scheduler = { state: "running", raw_state: "R", exit_status: null };
  raw.validation = { status: "not_ready", points: [], artifact_count: 0 };
  raw.lifecycle = "running";
  raw.next_action = "wait";
  const forbidden = vi.fn(async () => {
    throw new Error("Copy regression must not preview or confirm");
  });
  const unused = {
    preview: forbidden,
    confirm: forbidden,
    reset: vi.fn(),
    status: forbidden,
  };
  const lifecycle = {
    ...unused,
    status: vi.fn(async () => parseSmokeLifecycle(raw)),
  };
  render(
    <CampaignDetail
      campaign={campaign}
      zeusSnapshot={parseZeusSnapshot(data("zeus-snapshot"))}
      onBack={vi.fn()}
      onConnectZeus={vi.fn()}
      onViewJobs={vi.fn()}
      transfer={unused}
      submission={unused}
      lifecycle={lifecycle}
      screeningSubmission={unused}
      screeningLifecycle={unused}
      refinementSubmission={unused}
      refinementLifecycle={unused}
    />,
  );
  await userEvent
    .setup()
    .click(
      screen.getByRole("button", { name: "Recover submitted Zeus campaign" }),
    );
  expect(await screen.findByText("Smoke check running")).toBeVisible();
  const timeline = screen.getByRole("region", { name: "Campaign timeline" });
  expect(within(timeline).getByText("No local outputs")).toBeVisible();
  expect(
    within(timeline).getByText("Status: No local outputs"),
  ).toBeInTheDocument();
  expect(within(timeline).queryByText(/not started/i)).not.toBeInTheDocument();
  expect(timeline.querySelector(".timeline-item--not-started")).not.toBeNull();
  expect(timeline.querySelector(".timeline-item--complete")).toBeNull();
  expect(
    screen.queryByRole("heading", { name: "Sealed final results" }),
  ).not.toBeInTheDocument();
  expect(lifecycle.status).toHaveBeenCalledOnce();
  expect(forbidden).not.toHaveBeenCalled();
});
