import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "../App";
import { SubmissionApiError, ZeusApiError } from "../api/campaigns";
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

  it("routes an eligible smoke campaign to guarded review without exposing raw qsub", async () => {
    const user = userEvent.setup();
    const smokeCampaign = { ...campaignFixture, stage: "smoke", progress: [], next_plan: { ...campaignFixture.next_plan!, operation_scope: "remote-submission" as const } };
    const smokeApi = {
      async list() { return { campaigns: [smokeCampaign], invalid_count: 0, total: 1 }; },
      async get() { return smokeCampaign; },
    };
    render(<App api={smokeApi} creation={creationFixture} />);
    await screen.findByRole("button", { name: "Open campaign" });
    await user.click(screen.getByRole("link", { name: /Zeus jobs/i }));
    expect(screen.getByText("Ready for guarded review")).toBeInTheDocument();
    expect(screen.getByText(/Open the campaign to prepare it on Zeus and review the smoke submission/)).toBeInTheDocument();
    expect(screen.queryByText("Ready to copy")).not.toBeInTheDocument();
    expect(screen.queryByText("qsub data/example.pbs")).not.toBeInTheDocument();
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

  it("reviews and explicitly submits only the prepared smoke check", async () => {
    const user = userEvent.setup();
    const smokeCampaign = { ...campaignFixture, stage: "smoke", git_commit: "b".repeat(40), next_plan: null };
    const api = { async list() { return { campaigns: [smokeCampaign], invalid_count: 0, total: 1 }; }, async get() { return smokeCampaign; } };
    const transfer = {
      preview: async () => ({ preview_token: "transfer", expires_in_seconds: 300, campaign: { id: smokeCampaign.id, name: smokeCampaign.name, path: smokeCampaign.path, git_commit: "b".repeat(40) }, destination: { host: "zeus.technion.ac.il" as const, project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", campaign_directory: `/home/tal.noa/ytterbium_lab_simulation_new/${smokeCampaign.path}` }, artifacts: { ensemble_count: 35 as const, total_count: 72 as const, missing_count: 0, identical_count: 72, total_bytes: 52_000_000, missing_bytes: 0 }, effects: { copy_missing_only: true as const, overwrite_existing: false as const, submit_jobs: false as const, run_simulation: false as const } }),
      confirm: async () => ({ status: "prepared" as const, campaign_id: smokeCampaign.id, destination: `/home/tal.noa/ytterbium_lab_simulation_new/${smokeCampaign.path}`, transferred_count: 0, reused_identical_count: 72, bytes_transferred: 0, submitted_to_zeus: false as const, simulation_started: false as const }),
    };
    const preview = vi.fn(async () => ({ preview_token: "submit-token", expires_in_seconds: 300, campaign: { id: smokeCampaign.id, name: smokeCampaign.name, path: smokeCampaign.path, git_commit: "b".repeat(40), s0_values: [1.3] }, stage: { id: "smoke" as const, label: "Smoke check" as const, purpose: "Validate the campaign setup with two-particle test runs" }, job: { file: "jobs/01_smoke.pbs" as const, kind: "job" as const, task_count: 1, queue: "zeus_combined_q" as const, cores_per_task: 1 as const, memory_per_task_bytes: 68719476736 as const, walltime_seconds: 1200 as const }, remote: { host: "zeus.technion.ac.il" as const, project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", commit: "b".repeat(40), branch: "main", dirty: false as const }, inputs: { verified_count: 72 as const, status: "ready" as const }, effects: { submit_smoke: true as const, submit_later_stages: false as const, modify_files: false as const }, later_stages_locked: true as const }));
    const confirm = vi.fn(async () => ({ status: "submitted" as const, campaign_id: smokeCampaign.id, stage: "smoke" as const, job_id: "4759999.zeus-master", submitted_at: "2026-10-08T12:00:00Z", later_stages_locked: true as const }));
    render(<App api={api} creation={creationFixture} zeus={{ snapshot: async () => ({ ...zeusSnapshot, remote: { ...zeusSnapshot.remote, git_commit: "b".repeat(40) } }) }} transfer={transfer} submission={{ preview, confirm }} />);
    await user.click(screen.getByRole("link", { name: "Zeus jobs" }));
    await user.type(screen.getByLabelText("Technion username"), "tal.noa");
    await user.click(screen.getByRole("button", { name: "Connect and check status" }));
    await screen.findByText("Connected — read-only snapshot received");
    await user.click(screen.getByRole("button", { name: "Inspect campaign" }));
    expect(screen.queryByRole("button", { name: "Submit smoke check to Zeus" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Review Zeus preparation" }));
    await user.click(await screen.findByRole("button", { name: "Prepare campaign on Zeus" }));
    await user.click(await screen.findByRole("button", { name: "Review smoke submission" }));
    expect(await screen.findByRole("heading", { name: "Submit smoke check to Zeus" })).toHaveFocus();
    expect(screen.getByText("1 PBS job · 1 task")).toBeInTheDocument();
    expect(screen.getByText("1 CPU core · 64 GB memory")).toBeInTheDocument();
    expect(screen.getByText(/Screening or any later stage/i)).toBeInTheDocument();
    expect(confirm).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Submit smoke check to Zeus" }));
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(await screen.findByRole("heading", { name: "No action needed" })).toBeInTheDocument();
    expect(screen.getAllByText(/job 4759999\.zeus-master/i)).toHaveLength(2);
    expect(screen.getAllByText(/Screening remains locked/i)).toHaveLength(2);
    expect(screen.getByText("Smoke check submitted").closest('[role="status"]')).toHaveFocus();
  });

  it("blocks retry when the smoke submission outcome is unknown", async () => {
    const user = userEvent.setup();
    const smokeCampaign = { ...campaignFixture, stage: "smoke", git_commit: "b".repeat(40), next_plan: null };
    const api = { async list() { return { campaigns: [smokeCampaign], invalid_count: 0, total: 1 }; }, async get() { return smokeCampaign; } };
    const preparedTransfer = {
      preview: async () => ({ preview_token: "transfer", expires_in_seconds: 300, campaign: { id: smokeCampaign.id, name: smokeCampaign.name, path: smokeCampaign.path, git_commit: "b".repeat(40) }, destination: { host: "zeus.technion.ac.il" as const, project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", campaign_directory: `/home/tal.noa/ytterbium_lab_simulation_new/${smokeCampaign.path}` }, artifacts: { ensemble_count: 35 as const, total_count: 72 as const, missing_count: 0, identical_count: 72, total_bytes: 52_000_000, missing_bytes: 0 }, effects: { copy_missing_only: true as const, overwrite_existing: false as const, submit_jobs: false as const, run_simulation: false as const } }),
      confirm: async () => ({ status: "prepared" as const, campaign_id: smokeCampaign.id, destination: `/home/tal.noa/ytterbium_lab_simulation_new/${smokeCampaign.path}`, transferred_count: 0, reused_identical_count: 72, bytes_transferred: 0, submitted_to_zeus: false as const, simulation_started: false as const }),
    };
    const submissionPreview = async () => ({ preview_token: "submit-token", expires_in_seconds: 300, campaign: { id: smokeCampaign.id, name: smokeCampaign.name, path: smokeCampaign.path, git_commit: "b".repeat(40), s0_values: [1.3] }, stage: { id: "smoke" as const, label: "Smoke check" as const, purpose: "Validate setup" }, job: { file: "jobs/01_smoke.pbs" as const, kind: "job" as const, task_count: 1, queue: "zeus_combined_q" as const, cores_per_task: 1 as const, memory_per_task_bytes: 68719476736 as const, walltime_seconds: 1200 as const }, remote: { host: "zeus.technion.ac.il" as const, project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", commit: "b".repeat(40), branch: "main", dirty: false as const }, inputs: { verified_count: 72 as const, status: "ready" as const }, effects: { submit_smoke: true as const, submit_later_stages: false as const, modify_files: false as const }, later_stages_locked: true as const });
    render(<App api={api} creation={creationFixture} zeus={{ snapshot: async () => zeusSnapshot }} transfer={preparedTransfer} submission={{ preview: submissionPreview, confirm: async () => { throw new SubmissionApiError("submission_outcome_unknown", "timeout"); } }} />);
    await user.click(screen.getByRole("link", { name: "Zeus jobs" })); await user.type(screen.getByLabelText("Technion username"), "tal.noa"); await user.click(screen.getByRole("button", { name: "Connect and check status" })); await screen.findByText("Connected — read-only snapshot received"); await user.click(screen.getByRole("button", { name: "Inspect campaign" })); await user.click(screen.getByRole("button", { name: "Review Zeus preparation" })); await user.click(await screen.findByRole("button", { name: "Prepare campaign on Zeus" })); await user.click(await screen.findByRole("button", { name: "Review smoke submission" })); await user.click(await screen.findByRole("button", { name: "Submit smoke check to Zeus" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Do not submit again");
    expect(alert).toHaveFocus();
    expect(screen.getByRole("heading", { name: "Check Zeus jobs before continuing" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Submit smoke check to Zeus" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "View Zeus jobs" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "View Zeus jobs" }));
    expect(await screen.findByRole("heading", { name: "Monitor jobs safely" })).toBeInTheDocument();
    expect(screen.getByText("No Zeus snapshot loaded")).toBeInTheDocument();
    expect(screen.queryByText("Connected — read-only snapshot received")).not.toBeInTheDocument();
  });

  it.each([
    ["already_submitted", "No action needed", "durable Zeus submission record"],
    ["smoke_already_started", "Check Zeus jobs before continuing", "Smoke outputs already exist on Zeus"],
  ])("locks submission after terminal preview result %s", async (code, priority, copy) => {
    const user = userEvent.setup();
    const smokeCampaign = { ...campaignFixture, stage: "smoke", git_commit: "b".repeat(40), next_plan: null };
    const api = { async list() { return { campaigns: [smokeCampaign], invalid_count: 0, total: 1 }; }, async get() { return smokeCampaign; } };
    const transfer = {
      preview: async () => ({ preview_token: "transfer", expires_in_seconds: 300, campaign: { id: smokeCampaign.id, name: smokeCampaign.name, path: smokeCampaign.path, git_commit: "b".repeat(40) }, destination: { host: "zeus.technion.ac.il" as const, project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", campaign_directory: `/home/tal.noa/ytterbium_lab_simulation_new/${smokeCampaign.path}` }, artifacts: { ensemble_count: 35 as const, total_count: 72 as const, missing_count: 0, identical_count: 72, total_bytes: 52_000_000, missing_bytes: 0 }, effects: { copy_missing_only: true as const, overwrite_existing: false as const, submit_jobs: false as const, run_simulation: false as const } }),
      confirm: async () => ({ status: "prepared" as const, campaign_id: smokeCampaign.id, destination: `/home/tal.noa/ytterbium_lab_simulation_new/${smokeCampaign.path}`, transferred_count: 0, reused_identical_count: 72, bytes_transferred: 0, submitted_to_zeus: false as const, simulation_started: false as const }),
    };
    render(<App api={api} creation={creationFixture} zeus={{ snapshot: async () => zeusSnapshot }} transfer={transfer} submission={{ preview: async () => { throw new SubmissionApiError(code, "terminal"); }, confirm: async () => { throw new Error("must not confirm"); } }} />);
    await user.click(screen.getByRole("link", { name: "Zeus jobs" }));
    await user.type(screen.getByLabelText("Technion username"), "tal.noa");
    await user.click(screen.getByRole("button", { name: "Connect and check status" }));
    await screen.findByText("Connected — read-only snapshot received");
    await user.click(screen.getByRole("button", { name: "Inspect campaign" }));
    await user.click(screen.getByRole("button", { name: "Review Zeus preparation" }));
    await user.click(await screen.findByRole("button", { name: "Prepare campaign on Zeus" }));
    await user.click(await screen.findByRole("button", { name: "Review smoke submission" }));
    expect(await screen.findByRole("heading", { name: priority })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(copy);
    expect(screen.queryByRole("button", { name: "Review again" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Review smoke submission" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Submit smoke check to Zeus" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "View Zeus jobs" })).toBeInTheDocument();
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

  it("shows Zeus smoke evidence, accepts zero capture, and prepares Screening without submitting it", async () => {
    const user = userEvent.setup();
    const smokeCampaign = { ...campaignFixture, stage: "smoke", progress: [], next_plan: null, git_commit: "a".repeat(40) };
    const api = { async list() { return { campaigns: [smokeCampaign], invalid_count: 0, total: 1 }; }, async get() { return smokeCampaign; } };
    const status = vi.fn(async () => ({ source: "zeus" as const, queried_at: "2026-10-08T12:10:00Z", campaign: { id: smokeCampaign.id, name: smokeCampaign.name, stage: "smoke" as const }, submission: { job_id: "4759999.zeus-master" }, scheduler: { state: "completed_success" as const, raw_state: "F", exit_status: 0 }, validation: { status: "valid" as const, points: [{ s0: 1.3, captured: 0, input: 2 as const, efficiency: 0 }], artifact_count: 3 }, lifecycle: "ready_to_prepare_screen" as const, next_action: "review_screening_preparation" as const }));
    const preview = vi.fn(async () => ({ preview_token: "screen-token", expires_in_seconds: 300, campaign: { id: smokeCampaign.id, name: smokeCampaign.name, git_commit: "a".repeat(40) }, from_stage: "smoke" as const, to_stage: "screen" as const, smoke: { job_id: "4759999.zeus-master", points: [{ s0: 1.3, captured: 0, input: 2 as const, efficiency: 0 }], artifact_count: 3 }, artifacts: { create: ["screen/tasks.json", "jobs/02_screen.pbs"] as ["screen/tasks.json", "jobs/02_screen.pbs"], update: ["campaign.json"] as ["campaign.json"] }, effects: { prepare_screening: true as const, submit_screening: false as const, start_simulation: false as const, overwrite_existing: false as const }, local_sync: { status: "not_synchronized" as const } }));
    const confirm = vi.fn(async () => ({ status: "screening_prepared" as const, campaign_id: smokeCampaign.id, stage: "screen" as const, artifacts: { created: 2 as const, updated: 1 as const }, submitted_to_zeus: false as const, simulation_started: false as const, local_sync: { status: "not_synchronized" as const } }));
    render(<App api={api} creation={creationFixture} zeus={{ snapshot: async () => zeusSnapshot }} lifecycle={{ status, preview, confirm }} />);
    await user.click(screen.getByRole("link", { name: "Zeus jobs" }));
    await user.type(screen.getByLabelText("Technion username"), "tal.noa");
    await user.click(screen.getByRole("button", { name: "Connect and check status" }));
    await user.click(await screen.findByRole("button", { name: "Inspect campaign" }));
    await user.click(screen.getByRole("button", { name: "Check smoke status" }));
    expect(await screen.findByRole("heading", { name: "Action required" })).toBeInTheDocument();
    expect(screen.getByText(/zero-capture smoke point is valid/i)).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "0 of 2" })).toBeInTheDocument();
    expect(screen.getByText(/Zeus is the execution source/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Review screening preparation" }));
    expect(await screen.findByRole("heading", { name: "Prepare Screening on Zeus" })).toHaveFocus();
    expect(screen.getByText("screen/tasks.json")).toBeInTheDocument();
    expect(screen.getByText("jobs/02_screen.pbs")).toBeInTheDocument();
    expect(screen.getAllByText(/Does not submit a Zeus job/i).length).toBeGreaterThan(0);
    await user.click(screen.getByRole("button", { name: "Prepare Screening on Zeus" }));
    expect(await screen.findByText("Screening prepared on Zeus")).toBeInTheDocument();
    expect(screen.getByText(/No Screening job was submitted/)).toBeInTheDocument();
    expect(screen.getAllByText(/local campaign record has not been synchronized/i)).toHaveLength(2);
    expect(confirm).toHaveBeenCalledWith("screen-token");
  });

  it("leads with no action needed while the remote smoke job is running", async () => {
    const user = userEvent.setup();
    const smokeCampaign = { ...campaignFixture, stage: "smoke", progress: [], next_plan: null, git_commit: "a".repeat(40) };
    const api = { async list() { return { campaigns: [smokeCampaign], invalid_count: 0, total: 1 }; }, async get() { return smokeCampaign; } };
    const status = vi.fn()
      .mockResolvedValueOnce({ source: "zeus" as const, queried_at: "2026-10-08T12:10:00Z", campaign: { id: smokeCampaign.id, name: smokeCampaign.name, stage: "smoke" as const }, submission: { job_id: "4759999.zeus-master" }, scheduler: { state: "running" as const, raw_state: "R", exit_status: null }, validation: { status: "not_ready" as const, points: [], artifact_count: 0 }, lifecycle: "running" as const, next_action: "wait" as const })
      .mockResolvedValueOnce({ source: "zeus" as const, queried_at: "2026-10-08T12:11:00Z", campaign: { id: smokeCampaign.id, name: smokeCampaign.name, stage: "smoke" as const }, submission: { job_id: "4759999.zeus-master" }, scheduler: { state: "completed_success" as const, raw_state: "F", exit_status: 0 }, validation: { status: "not_ready" as const, points: [], artifact_count: 0 }, lifecycle: "awaiting_outputs" as const, next_action: "wait" as const });
    const lifecycle = { status, preview: vi.fn(), confirm: vi.fn() };
    render(<App api={api} creation={creationFixture} zeus={{ snapshot: async () => zeusSnapshot }} lifecycle={lifecycle} />);
    await user.click(screen.getByRole("link", { name: "Zeus jobs" })); await user.type(screen.getByLabelText("Technion username"), "tal.noa"); await user.click(screen.getByRole("button", { name: "Connect and check status" })); await user.click(await screen.findByRole("button", { name: "Inspect campaign" })); await user.click(screen.getByRole("button", { name: "Check smoke status" }));
    expect(await screen.findByRole("heading", { name: "No action needed" })).toBeInTheDocument();
    expect(screen.getByText(/safely close this application/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Review screening preparation" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Refresh smoke status" }));
    expect(await screen.findByText(/still publishing the expected smoke output files/i)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "No action needed" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Review screening preparation" })).not.toBeInTheDocument();
  });
});
