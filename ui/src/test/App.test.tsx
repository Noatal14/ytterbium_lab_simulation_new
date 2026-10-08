import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "../App";
import { campaignFixture, fixtureApi } from "./campaignFixture";

const creationFixture = {
  sources: async () => [{ id: "source-1", path: "data/particle_states/after_zeeman/production", profile: "production", ensemble_count: 35 as const, minimum_survivors: 31000, maximum_survivors: 32000, fingerprint: "f".repeat(64) }],
  session: async () => "csrf-token",
  preview: async () => ({ preview_token: "preview-token", expires_in_seconds: 300, plan: { name: "Fixed s0 1.3", path: "data/optimization/mot_2d/s0_1p3", s0_values: [1.3], source_id: "source-1", files: ["campaign.json", "jobs/01_smoke.pbs"], stage: "smoke" as const }, scientific_design: {}, provenance: { commit: "a".repeat(40), input_count: 35 as const }, duplicate: null }),
  confirm: async () => ({ status: "created" as const, campaign_id: "mot_2d-created", path: "data/optimization/mot_2d/s0_1p3", stage: "smoke" as const, submitted_to_zeus: false as const }),
};

describe("onboarding home", () => {
  it("guides a new operator without enabling later or blocked workflows", async () => {
    render(<App api={fixtureApi} creation={creationFixture} />);
    expect(screen.getByRole("heading", { name: "Run or inspect a campaign" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Start 2D-MOT campaign/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: /Start 3D-MOT campaign/ })).toBeDisabled();
    expect(screen.getByText(/cannot run simulations, contact Zeus, or submit jobs/i)).toBeInTheDocument();
    await screen.findByRole("button", { name: "Open campaign" });
  });

  it("renders honest sample labels and values as adjacent definition pairs", async () => {
    render(<App api={fixtureApi} creation={creationFixture} />);
    const branchLabel = screen.getByText("Branch");
    expect(branchLabel.tagName).toBe("DT");
    expect(branchLabel.nextElementSibling).toHaveTextContent("Unavailable in sample data");
    const zeusLabel = screen.getByText("Zeus connection");
    expect(zeusLabel.tagName).toBe("DT");
    expect(zeusLabel.nextElementSibling).toHaveTextContent("Not configured in sample data");
    await screen.findByRole("button", { name: "Open campaign" });
  });

  it("uses the same icon-and-label pattern for every navigation item", async () => {
    render(<App api={fixtureApi} creation={creationFixture} />);
    const navigation = screen.getByRole("navigation", { name: "Primary navigation" });
    expect(navigation.querySelectorAll("svg")).toHaveLength(3);
    await screen.findByRole("button", { name: "Open campaign" });
  });

  it("opens a campaign without claiming that its prepared stage is running", async () => {
    const user = userEvent.setup();
    render(<App api={fixtureApi} creation={creationFixture} />);
    await user.click(await screen.findByRole("button", { name: "Open campaign" }));
    expect(screen.getByRole("heading", { name: campaignFixture.name })).toHaveFocus();
    expect(screen.getByText(/does not mean a Zeus job is running/i)).toBeInTheDocument();
    expect(screen.getByText(/^not checked\.$/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy command" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("2 of 5 validated outputs")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /Back to campaigns/ }));
    expect(screen.getByRole("button", { name: "Open campaign" })).toHaveFocus();
  });

  it("reviews and confirms a local campaign without implying Zeus submission", async () => {
    const user = userEvent.setup();
    render(<App api={fixtureApi} creation={creationFixture} />);
    await user.click(screen.getByRole("button", { name: "Start 2D-MOT campaign" }));
    await screen.findByRole("option", { name: /after_zeeman\/production/ });
    await user.type(screen.getByLabelText(/^Campaign name/), "Fixed s0 1.3");
    await user.type(screen.getByLabelText(/^Campaign folder/), "s0_1p3");
    await user.selectOptions(screen.getByLabelText(/^Zeeman ensemble source/), "source-1");
    await user.type(screen.getByLabelText(/^Fixed s₀ values/), "1.3");
    await user.click(screen.getByRole("button", { name: "Review campaign" }));
    expect(await screen.findByRole("heading", { name: "Review before creating" })).toHaveFocus();
    expect(screen.getByText("35 Zeeman ensembles")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Create campaign" }));
    expect(await screen.findByRole("heading", { name: "Campaign created and validated" })).toHaveFocus();
    expect(screen.getByText(/No simulation was run and no work was submitted to Zeus/)).toBeInTheDocument();
  });
});
