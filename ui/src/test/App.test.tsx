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

  it("explains an unavailable local source service and retries successfully", async () => {
    const user = userEvent.setup();
    let attempts = 0;
    const recovering = {
      ...creationFixture,
      sources: async () => {
        attempts += 1;
        if (attempts === 1) throw new Error("offline");
        return creationFixture.sources();
      },
    };
    render(<App api={fixtureApi} creation={recovering} />);
    await user.click(screen.getByRole("button", { name: "Start 2D-MOT campaign" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/local campaign service is not available/i);
    expect(screen.getByLabelText(/^Zeeman ensemble source/)).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("option", { name: /after_zeeman\/production/ })).toBeInTheDocument();
    expect(screen.getByLabelText(/^Zeeman ensemble source/)).toBeEnabled();
  });

  it("shows read-only Zeus job states without implying a live connection or submission", async () => {
    const user = userEvent.setup();
    render(<App api={fixtureApi} creation={creationFixture} jobs={[
      { id: "12[]", campaignId: campaignFixture.id, name: "Queued array", rawState: "Q", state: "queued", exitStatus: null, recordedAt: "Sample record" },
      { id: "13", campaignId: campaignFixture.id, name: "Running confirmation", rawState: "R", state: "running", exitStatus: null, recordedAt: "Sample record" },
      { id: "14", campaignId: campaignFixture.id, name: "Finished merge", rawState: "F", state: "completed", exitStatus: 0, recordedAt: "Sample record" },
      { id: "15", campaignId: campaignFixture.id, name: "Held dependency", rawState: "H", state: "blocked", exitStatus: null, recordedAt: "Sample record" },
    ]} />);
    await user.click(screen.getByRole("link", { name: "Zeus jobs" }));
    expect(screen.getByRole("heading", { name: "Monitor job readiness safely" })).toBeInTheDocument();
    expect(screen.getByText("Zeus connection: Not configured")).toBeInTheDocument();
    expect(screen.getByText(/No action needed while this job is running/)).toBeInTheDocument();
    expect(screen.getByText(/Raw PBS state H/)).toBeInTheDocument();
    expect(screen.getByText(/Viewing or copying a plan is not submission/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /submit/i })).not.toBeInTheDocument();
  });

  it("shows explicit loading and error states for local campaign readiness", async () => {
    const user = userEvent.setup();
    const pending = { list: () => new Promise<never>(() => {}), get: fixtureApi.get };
    const { unmount } = render(<App api={pending} creation={creationFixture} />);
    await user.click(screen.getByRole("link", { name: "Zeus jobs" }));
    expect(screen.getByText("Checking local campaign records")).toBeInTheDocument();
    unmount();

    render(<App api={{ list: async () => { throw new Error("unavailable"); }, get: fixtureApi.get }} creation={creationFixture} />);
    await user.click(screen.getByRole("link", { name: "Zeus jobs" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Campaign readiness is unavailable");
  });
});
