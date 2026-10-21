import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { CampaignExplorer } from "../components/CampaignExplorer";

it("directs a new user to campaign creation and explains how to check Zeus jobs", () => {
  render(<CampaignExplorer campaigns={[]} invalidCount={0} loading={false} error={null} onOpen={vi.fn()} />);
  expect(screen.getByText("Start a campaign from Home. Saved campaigns will appear here.")).toBeVisible();
  expect(screen.getByText("Open a saved campaign to inspect its results or connect to Zeus to check its jobs.")).toBeVisible();
  expect(screen.queryByText(/later milestone|this milestone/i)).not.toBeInTheDocument();
});
