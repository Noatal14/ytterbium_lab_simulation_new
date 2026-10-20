import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { CampaignDetail } from "../features/campaign/CampaignDetail";

it("requires shared preparation before a fresh 3D Discovery and never submits during transfer", async () => {
  const user = userEvent.setup();
  const forbidden = vi.fn(async () => { throw Error("Preparation cannot submit jobs"); });
  const unused = { preview: forbidden, confirm: forbidden, status: forbidden, reset: vi.fn() };
  const campaign = { id: "mot_3d-test", name: "3D transfer test", family: "mot_3d", kind: "mot_3d", path: "data/optimization/mot_3d/transfer_test", stage: "discovery", trust: "trusted-current", scientific_role: "campaign", progress: [], warnings: [], next_plan: null, remote_preparation: {status: "ready", reason_code: null} };
  const profile = {host: "zeus.technion.ac.il", username: "tal.noa", project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", authentication: "ssh-key-or-agent"};
  const transfer = {
    preview: vi.fn(async () => ({preview_token: "transfer", expires_in_seconds: 300, campaign: {...campaign, git_commit: "a".repeat(40)}, destination: {host: profile.host, project_directory: profile.project_directory, campaign_directory: `${profile.project_directory}/${campaign.path}`}, artifacts: {ensemble_count: 20, total_count: 52, missing_count: 52, identical_count: 0, total_bytes: 10000, missing_bytes: 10000}, effects: {copy_missing_only: true, overwrite_existing: false, submit_jobs: false, run_simulation: false}})),
    confirm: vi.fn(async () => ({status: "prepared", campaign_id: campaign.id, destination: `${profile.project_directory}/${campaign.path}`, transferred_count: 52, reused_identical_count: 0, bytes_transferred: 10000, submitted_to_zeus: false, simulation_started: false})),
  };
  render(<CampaignDetail campaign={campaign as any} onBack={vi.fn()} transfer={transfer as any} submission={unused as any} lifecycle={unused as any} screeningSubmission={unused as any} screeningLifecycle={unused as any} refinementSubmission={unused as any} refinementLifecycle={unused as any} mot3DDiscovery={unused as any} zeusSnapshot={{profile} as any} onConnectZeus={vi.fn()} onViewJobs={vi.fn()} />);
  expect(screen.getByRole("button", {name: "Review Discovery jobs"})).toBeDisabled();
  expect(screen.getByRole("button", {name: "Check Zeus status"})).toBeEnabled();
  await user.click(screen.getByRole("button", {name: "Review Zeus preparation"}));
  expect(transfer.preview).toHaveBeenCalledWith(campaign.id, profile);
  expect(screen.getByText("Sealed input ensembles")).toBeVisible();
  expect(screen.getByRole("button", {name: "Review Discovery jobs"})).toBeDisabled();
  await user.dblClick(screen.getByRole("button", {name: "Prepare campaign on Zeus"}));
  expect(await screen.findByText("Campaign prepared on Zeus")).toBeVisible();
  expect(transfer.confirm).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("button", {name: "Review Discovery jobs"})).toBeEnabled();
  expect(forbidden).not.toHaveBeenCalled();
});
