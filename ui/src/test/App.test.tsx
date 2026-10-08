import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "../App";
import { ZeusApiError } from "../api/campaigns";
import { campaignFixture, fixtureApi } from "./campaignFixture";

const creationFixture = {
  sources: async () => [{ id: "source-1", path: "data/particle_states/after_zeeman/production", profile: "production", ensemble_count: 35 as const, minimum_survivors: 31000, maximum_survivors: 32000, fingerprint: "f".repeat(64) }],
  session: async () => "csrf-token",
  preview: async () => ({ preview_token: "preview-token", expires_in_seconds: 300, plan: { name: "Fixed s0 1.3", path: "data/optimization/mot_2d/s0_1p3", s0_values: [1.3], source_id: "source-1", files: ["campaign.json", "jobs/01_smoke.pbs"], stage: "smoke" as const }, scientific_design: {}, provenance: { commit: "a".repeat(40), input_count: 35 as const }, duplicate: null }),
  confirm: async () => ({ status: "created" as const, campaign_id: "mot_2d-created", path: "data/optimization/mot_2d/s0_1p3", stage: "smoke" as const, submitted_to_zeus: false as const }),
};
const zeusSnapshot = {
  connection_status: "connected" as const,
  profile: { host: "zeus.technion.ac.il" as const, username: "tal.noa", project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", authentication: "ssh-key-or-agent" as const },
  remote: { project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", git_commit: "a".repeat(40), branch: "main", dirty: false },
  scheduler: { status: "available" as const, queried_at: new Date().toISOString(), jobs: [
    { id: "12[]", name: "Queued array", raw_state: "Q" as const, state: "queued" as const, exit_status: null, walltime: null, start_time: null, comment: null, dependencies: [] },
    { id: "13", name: "Running confirmation", raw_state: "R" as const, state: "running" as const, exit_status: null, walltime: "00:12:00", start_time: null, comment: null, dependencies: [] },
    { id: "14", name: "Finished merge", raw_state: "F" as const, state: "completed_success" as const, exit_status: 0, walltime: "00:00:04", start_time: null, comment: null, dependencies: [] },
    { id: "15", name: "Held job", raw_state: "H" as const, state: "held_attention" as const, exit_status: null, walltime: null, start_time: null, comment: "held", dependencies: ["14"] },
    { id: "16", name: "Terminated job", raw_state: "X" as const, state: "completed_failed" as const, exit_status: -29, walltime: "00:01:00", start_time: null, comment: null, dependencies: [] },
  ] },
};

describe("onboarding home", () => {
  it("guides a new operator without enabling later or blocked workflows", async () => {
    render(<App api={fixtureApi} creation={creationFixture} />);
    expect(screen.getByRole("heading", { name: "Run or inspect a campaign" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Start 2D-MOT campaign/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: /Start 3D-MOT campaign/ })).toBeDisabled();
    expect(screen.getByText(/Zeus is contacted only after an explicit connection or preparation action/i)).toBeInTheDocument();
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

  it("keeps legacy campaigns inspectable while hiding every Zeus command", async () => {
    const user = userEvent.setup();
    const legacyCampaign = {
      ...campaignFixture,
      id: "mot_2d-legacy",
      name: "legacy fixed s0 1.3",
      trust: "legacy-incomplete" as const,
      scientific_role: "historical-evidence" as const,
      remote_preparation: { status: "legacy-local-only" as const, reason_code: "absolute-input-paths" as const },
    };
    const legacyApi = {
      async list() { return { campaigns: [legacyCampaign], invalid_count: 0, total: 1 }; },
      async get() { return legacyCampaign; },
    };
    render(<App api={legacyApi} creation={creationFixture} />);
    expect(await screen.findByText("Local-only campaign")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Open campaign" }));
    expect(screen.getByRole("heading", { name: "Recreate this campaign before using Zeus" })).toBeInTheDocument();
    expect(screen.getByText(/created with file locations tied to another computer/i)).toBeInTheDocument();
    expect(screen.getByText(/Nothing in this campaign will be changed or deleted/i)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Campaign timeline" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Copy command" })).not.toBeInTheDocument();
    expect(screen.queryByText("qsub data/example.pbs")).not.toBeInTheDocument();
  });

  it("explains an unavailable campaign and keeps its command hidden", async () => {
    const user = userEvent.setup();
    const unavailableCampaign = {
      ...campaignFixture,
      id: "mot_2d-unavailable",
      name: "incomplete portable campaign",
      remote_preparation: { status: "unavailable" as const, reason_code: "incomplete-portability-record" as const },
    };
    const unavailableApi = {
      async list() { return { campaigns: [unavailableCampaign], invalid_count: 0, total: 1 }; },
      async get() { return unavailableCampaign; },
    };
    render(<App api={unavailableApi} creation={creationFixture} />);
    expect(await screen.findByText("Zeus preparation unavailable")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Open campaign" }));
    expect(screen.getByRole("heading", { name: "Zeus preparation is unavailable" })).toBeInTheDocument();
    expect(screen.getByText(/does not pass the required portability and validation checks/i)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Campaign timeline" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Copy command" })).not.toBeInTheDocument();
    expect(screen.queryByText("qsub data/example.pbs")).not.toBeInTheDocument();
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

  it("never labels a non-portable campaign ready on the Zeus jobs page", async () => {
    const user = userEvent.setup();
    const blockedCampaign = {
      ...campaignFixture,
      id: "mot_2d-blocked",
      name: "blocked portable campaign",
      remote_preparation: { status: "unavailable" as const, reason_code: "incomplete-portability-record" as const },
    };
    const blockedApi = {
      async list() { return { campaigns: [blockedCampaign], invalid_count: 0, total: 1 }; },
      async get() { return blockedCampaign; },
    };
    render(<App api={blockedApi} creation={creationFixture} />);
    await screen.findByRole("button", { name: "Open campaign" });
    await user.click(screen.getByRole("link", { name: /Zeus jobs/i }));
    expect(screen.getByRole("heading", { name: "Campaign job readiness" })).toBeInTheDocument();
    expect(screen.getByText("This campaign cannot safely prepare or expose a Zeus action.")).toBeInTheDocument();
    expect(screen.getByText("Blocked")).toBeInTheDocument();
    expect(screen.queryByText("Ready to copy")).not.toBeInTheDocument();
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

  it("connects explicitly, derives the project directory, and renders read-only Zeus states", async () => {
    const user = userEvent.setup();
    const snapshot = vi.fn(async () => zeusSnapshot);
    render(<App api={fixtureApi} creation={creationFixture} zeus={{ snapshot }} />);
    await user.click(screen.getByRole("link", { name: "Zeus jobs" }));
    expect(screen.getByRole("heading", { name: "Monitor jobs safely" })).toHaveFocus();
    expect(snapshot).not.toHaveBeenCalled();
    await user.type(screen.getByLabelText("Technion username"), "tal.noa");
    expect(screen.getByLabelText("Remote project directory")).toHaveValue("/home/tal.noa/ytterbium_lab_simulation_new");
    await user.click(screen.getByRole("button", { name: "Connect and check status" }));
    expect(snapshot).toHaveBeenCalledWith("tal.noa", "/home/tal.noa/ytterbium_lab_simulation_new");
    expect(await screen.findByText("Connected — read-only snapshot received")).toBeInTheDocument();
    expect(screen.getByText(/No action needed while this job is running/)).toBeInTheDocument();
    expect(screen.getByText(/Raw PBS state H/)).toBeInTheDocument();
    expect(screen.getByText(/Recorded dependencies: 14 \(context only\)/)).toBeInTheDocument();
    expect(screen.getByText(/A hold always needs attention/)).toBeInTheDocument();
    expect(screen.getByText(/Raw PBS state X · Exit -29/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /submit/i })).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument();
  });

  it("previews and explicitly confirms Zeus preparation without submitting a job", async () => {
    const user = userEvent.setup();
    const smokeCampaign = { ...campaignFixture, stage: "smoke", git_commit: "b".repeat(40), next_plan: null };
    const api = { async list() { return { campaigns: [smokeCampaign], invalid_count: 0, total: 1 }; }, async get() { return smokeCampaign; } };
    const preview = vi.fn(async () => ({
      preview_token: "transfer-token", expires_in_seconds: 300,
      campaign: { id: smokeCampaign.id, name: smokeCampaign.name, path: smokeCampaign.path, git_commit: "b".repeat(40) },
      destination: { host: "zeus.technion.ac.il" as const, project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", campaign_directory: "/home/tal.noa/ytterbium_lab_simulation_new/data/optimization/mot_2d/sample" },
      artifacts: { ensemble_count: 35 as const, total_count: 72 as const, missing_count: 12, identical_count: 60, total_bytes: 52_000_000, missing_bytes: 9_000_000 },
      effects: { copy_missing_only: true as const, overwrite_existing: false as const, submit_jobs: false as const, run_simulation: false as const },
    }));
    const confirm = vi.fn(async () => ({ status: "prepared" as const, campaign_id: smokeCampaign.id, destination: "/home/tal.noa/ytterbium_lab_simulation_new/data/optimization/mot_2d/sample", transferred_count: 12, reused_identical_count: 60, bytes_transferred: 9_000_000, submitted_to_zeus: false as const, simulation_started: false as const }));
    render(<App api={api} creation={creationFixture} zeus={{ snapshot: async () => zeusSnapshot }} transfer={{ preview, confirm }} />);
    await user.click(screen.getByRole("link", { name: "Zeus jobs" }));
    await user.type(screen.getByLabelText("Technion username"), "tal.noa");
    await user.click(screen.getByRole("button", { name: "Connect and check status" }));
    await screen.findByText("Connected — read-only snapshot received");
    await user.click(screen.getByRole("button", { name: "Inspect campaign" }));
    expect(screen.getByRole("heading", { name: "Prepare campaign on Zeus" })).toBeInTheDocument();
    expect(screen.getByText("Zeus connection profile selected")).toBeInTheDocument();
    expect(screen.getByText(/file hashes will be checked again during review/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Review Zeus preparation" }));
    expect(preview).toHaveBeenCalledWith(smokeCampaign.id, zeusSnapshot.profile);
    expect(await screen.findByText("12 · 9 MB")).toBeInTheDocument();
    expect(screen.getByText(/Existing files will never be overwritten/)).toBeInTheDocument();
    expect(screen.getByText(/No Zeus job will be submitted/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Review preparation" })).toHaveFocus();
    expect(confirm).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByRole("button", { name: "Review Zeus preparation" })).toHaveFocus();
    await user.click(screen.getByRole("button", { name: "Review Zeus preparation" }));
    expect(await screen.findByRole("heading", { name: "Review preparation" })).toHaveFocus();
    await user.click(screen.getByRole("button", { name: "Prepare campaign on Zeus" }));
    expect(confirm).toHaveBeenCalledWith("transfer-token");
    expect(await screen.findByText("Campaign prepared on Zeus")).toBeInTheDocument();
    expect(screen.getByText("No simulation was started and no Zeus job was submitted.")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveFocus();
  });

  it("moves focus to a preparation error so it is immediately announced", async () => {
    const user = userEvent.setup();
    const smokeCampaign = { ...campaignFixture, stage: "smoke", git_commit: "b".repeat(40), next_plan: null };
    const api = { async list() { return { campaigns: [smokeCampaign], invalid_count: 0, total: 1 }; }, async get() { return smokeCampaign; } };
    const preview = async () => ({
      preview_token: "transfer-token", expires_in_seconds: 300,
      campaign: { id: smokeCampaign.id, name: smokeCampaign.name, path: smokeCampaign.path, git_commit: "b".repeat(40) },
      destination: { host: "zeus.technion.ac.il" as const, project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", campaign_directory: "/home/tal.noa/ytterbium_lab_simulation_new/data/optimization/mot_2d/sample" },
      artifacts: { ensemble_count: 35 as const, total_count: 72 as const, missing_count: 12, identical_count: 60, total_bytes: 52_000_000, missing_bytes: 9_000_000 },
      effects: { copy_missing_only: true as const, overwrite_existing: false as const, submit_jobs: false as const, run_simulation: false as const },
    });
    render(<App api={api} creation={creationFixture} zeus={{ snapshot: async () => zeusSnapshot }} transfer={{ preview, confirm: async () => { throw new Error("Preparation token expired. Review again."); } }} />);
    await user.click(screen.getByRole("link", { name: "Zeus jobs" }));
    await user.type(screen.getByLabelText("Technion username"), "tal.noa");
    await user.click(screen.getByRole("button", { name: "Connect and check status" }));
    await screen.findByText("Connected — read-only snapshot received");
    await user.click(screen.getByRole("button", { name: "Inspect campaign" }));
    await user.click(screen.getByRole("button", { name: "Review Zeus preparation" }));
    await user.click(await screen.findByRole("button", { name: "Prepare campaign on Zeus" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Preparation token expired");
    expect(alert).toHaveFocus();
  });

  it("does not offer Zeus preparation for an active campaign beyond smoke", async () => {
    const user = userEvent.setup();
    render(<App api={fixtureApi} creation={creationFixture} zeus={{ snapshot: async () => zeusSnapshot }} />);
    await user.click(await screen.findByRole("button", { name: "Open campaign" }));
    expect(screen.queryByRole("heading", { name: "Prepare campaign on Zeus" })).not.toBeInTheDocument();
  });

  it("shows explicit loading and error states for local campaign readiness", async () => {
    const user = userEvent.setup();
    const pending = { list: () => new Promise<never>(() => {}), get: fixtureApi.get };
    const zeus = { snapshot: async () => zeusSnapshot };
    const { unmount } = render(<App api={pending} creation={creationFixture} zeus={zeus} />);
    await user.click(screen.getByRole("link", { name: "Zeus jobs" }));
    expect(screen.getByText("Checking local campaign records")).toBeInTheDocument();
    unmount();

    render(<App api={{ list: async () => { throw new Error("unavailable"); }, get: fixtureApi.get }} creation={creationFixture} zeus={zeus} />);
    await user.click(screen.getByRole("link", { name: "Zeus jobs" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Campaign readiness is unavailable");
  });

  it("explains SSH authentication failures without asking for a password", async () => {
    const user = userEvent.setup();
    render(<App api={fixtureApi} creation={creationFixture} zeus={{ snapshot: async () => { throw new ZeusApiError("zeus_authentication_required", "Configure an existing SSH key or agent."); } }} />);
    await user.click(screen.getByRole("link", { name: "Zeus jobs" }));
    await user.type(screen.getByLabelText("Technion username"), "tal.noa");
    await user.click(screen.getByRole("button", { name: "Connect and check status" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("SSH authentication is required");
    expect(screen.getByRole("button", { name: "About SSH authentication" })).toHaveAccessibleName("About SSH authentication");
    expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument();
  });

  it("guides a first-time operator through safe local SSH setup", async () => {
    const user = userEvent.setup();
    render(<App api={fixtureApi} creation={creationFixture} zeus={{ snapshot: async () => zeusSnapshot }} />);
    await user.click(screen.getByRole("link", { name: "Zeus jobs" }));
    const guide = screen.getByText("First time connecting? View setup guide");
    await user.click(guide);
    expect(screen.getByText(/Connect this computer to the Technion VPN/)).toBeVisible();
    expect(screen.getByText(/Create a dedicated SSH key on this computer/)).toBeVisible();
    expect(screen.getByText((_, element) => element?.tagName === "LI" && element.textContent?.includes("install only the .pub public key in your Zeus account") === true)).toBeVisible();
    expect(screen.getByText(/compare the displayed server fingerprint with an official Technion source/)).toBeVisible();
    expect(screen.getByText(/Never paste your Zeus password, private key, or key passphrase/)).toBeVisible();
  });

  it("validates the Technion username before enabling a Zeus check", async () => {
    const user = userEvent.setup();
    const snapshot = vi.fn(async () => zeusSnapshot);
    render(<App api={fixtureApi} creation={creationFixture} zeus={{ snapshot }} />);
    await user.click(screen.getByRole("link", { name: "Zeus jobs" }));
    const username = screen.getByLabelText("Technion username");
    const connect = screen.getByRole("button", { name: "Connect and check status" });
    await user.type(username, "1tal.noa");
    expect(username).toHaveAccessibleName("Technion username");
    expect(username).toHaveAttribute("aria-invalid", "true");
    expect(connect).toBeDisabled();
    expect(screen.getByLabelText("Remote project directory")).toHaveValue("");
    expect(screen.getByText("Enter the username you use to sign in to Technion services.")).toBeVisible();
    await user.clear(username);
    await user.type(username, "tal.noa");
    expect(username).toHaveAttribute("aria-invalid", "false");
    expect(connect).toBeEnabled();
    expect(screen.queryByText("Enter the username you use to sign in to Technion services.")).not.toBeInTheDocument();
  });

  it("labels an old empty scheduler snapshot as stale without implying failure", async () => {
    const user = userEvent.setup();
    const stale = { ...zeusSnapshot, scheduler: { ...zeusSnapshot.scheduler, queried_at: "2026-01-01T00:00:00Z", jobs: [] } };
    render(<App api={fixtureApi} creation={creationFixture} zeus={{ snapshot: async () => stale }} />);
    await user.click(screen.getByRole("link", { name: "Zeus jobs" }));
    await user.type(screen.getByLabelText("Technion username"), "tal.noa");
    await user.click(screen.getByRole("button", { name: "Connect and check status" }));
    expect(await screen.findByText("Connected — snapshot is stale")).toBeInTheDocument();
    expect(screen.getByText("No jobs were returned")).toBeInTheDocument();
    expect(screen.getByText(/Status does not update automatically/)).toBeInTheDocument();
  });
});
