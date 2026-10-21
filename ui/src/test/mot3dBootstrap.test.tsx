import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  parseMot3DBootstrapPreview,
  parseMot3DBootstrapResult,
  parseMot3DBootstrapStatus,
  type Mot3DBootstrapApi,
} from "../api/clients/mot3d";
import { Mot3DCampaignCreation } from "../components/Mot3DCampaignCreation";

const hash = "a".repeat(64);
const source = {
  source_id: hash,
  campaign_name: "Completed 2D",
  s0: 1.3,
  sealed_ensemble_count: 20 as const,
  completion: "complete" as const,
  provenance_fingerprint: "b".repeat(64),
};
const status = {
  lifecycle: "ready" as const,
  sources: [source],
  reason: null,
  evidence_requirement: null,
  timestep_policy: {
    status: "pragmatic_user_approved_after_inconclusive_study" as const,
    convergence_claim: "not_established" as const,
    sha256: "d".repeat(64),
  },
};
const preview = {
  preview_token: "token",
  expires_in_seconds: 300,
  campaign: { name: "mot_3d_run", stage: "discovery" as const },
  source,
  discovery: {
    families: ["angled_donut", "single_pass"] as [
      "angled_donut",
      "single_pass",
    ],
    solver: "RK4StHybridCustom",
    screening_dt_s: 10e-6,
    production_dt_s: 5e-6,
    timestep_policy_status:
      "pragmatic_user_approved_after_inconclusive_study" as const,
    convergence_claim: "not_established" as const,
    input_role_counts: {
      discovery: 12 as const,
      refinement: 4 as const,
      preliminary_check: 4 as const,
    },
  },
  artifacts: {
    create: [
      "campaign.json",
      "jobs/01_smoke_angled_donut.pbs",
      "jobs/01_smoke_single_pass.pbs",
      "jobs/02_submit_discovery_chain.sh",
      "jobs/angled_donut/round_01.pbs",
      "jobs/angled_donut/round_02.pbs",
      "jobs/single_pass/round_01.pbs",
      "jobs/single_pass/round_02.pbs",
      "jobs/single_pass/round_03.pbs",
    ],
  },
  effects: {
    create_campaign: true as const,
    submit_job: false as const,
    start_simulation: false as const,
    prepare_dt_validation: false as const,
  },
};

function api(overrides: Partial<Mot3DBootstrapApi> = {}): Mot3DBootstrapApi {
  return {
    reset: vi.fn(),
    status: vi.fn().mockResolvedValue(status),
    preview: vi.fn().mockResolvedValue(preview),
    confirm: vi
      .fn()
      .mockResolvedValue({
        lifecycle: "discovery_prepared",
        campaign_name: "mot_3d_run",
        stage: "discovery",
        submitted_to_zeus: false,
        bootstrap_key: "c".repeat(64),
      }),
    ...overrides,
  } as Mot3DBootstrapApi;
}

describe("3D bootstrap strict contracts", () => {
  it("rejects unknown fields and mismatched scientific counts", () => {
    expect(() =>
      parseMot3DBootstrapStatus({ ...status, secret: true }),
    ).toThrow();
    expect(() =>
      parseMot3DBootstrapStatus({
        ...status,
        lifecycle: "blocked_missing_approved_timestep",
      }),
    ).toThrow();
    expect(() =>
      parseMot3DBootstrapStatus({
        ...status,
        timestep_policy: {
          ...status.timestep_policy,
          convergence_claim: "established",
        },
      }),
    ).toThrow();
    expect(() =>
      parseMot3DBootstrapStatus({
        ...status,
        sources: [{ ...source, campaign_name: "unsafe\nname" }],
      }),
    ).toThrow();
    expect(() =>
      parseMot3DBootstrapPreview(
        {
          ...preview,
          discovery: {
            ...preview.discovery,
            input_role_counts: {
              discovery: 11,
              refinement: 4,
              preliminary_check: 4,
            },
          },
        },
        { sourceId: hash, campaignName: "mot_3d_run" },
      ),
    ).toThrow();
    expect(() =>
      parseMot3DBootstrapPreview(
        {
          ...preview,
          discovery: {
            ...preview.discovery,
            timestep_policy_status: "approved_by_paired_convergence_validation",
          },
        },
        { sourceId: hash, campaignName: "mot_3d_run" },
      ),
    ).toThrow();
    expect(() =>
      parseMot3DBootstrapPreview(
        { ...preview, discovery: { ...preview.discovery, solver: "other" } },
        { sourceId: hash, campaignName: "mot_3d_run" },
      ),
    ).toThrow();
    expect(() =>
      parseMot3DBootstrapPreview(
        {
          ...preview,
          discovery: { ...preview.discovery, screening_dt_s: 1.25e-6 },
        },
        { sourceId: hash, campaignName: "mot_3d_run" },
      ),
    ).toThrow();
    expect(() =>
      parseMot3DBootstrapResult(
        {
          lifecycle: "discovery_prepared",
          campaign_name: "other",
          stage: "discovery",
          submitted_to_zeus: false,
          bootstrap_key: "c".repeat(64),
        },
        "mot_3d_run",
      ),
    ).toThrow();
  });

  it("shows the pragmatic policy read-only and requires a new campaign", async () => {
    render(<Mot3DCampaignCreation api={api()} onBack={vi.fn()} />);
    const heading = await screen.findByRole("heading", {
      name: /Create a 3D-MOT Discovery campaign/i,
    });
    // DOM presence can precede the passive effect that transfers focus.
    await waitFor(() => expect(heading).toHaveFocus());
    expect(
      screen.getByText(/older inconclusive 3D campaign cannot be resumed/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/Search stages use 10 µs/i)).toBeInTheDocument();
    expect(
      screen.getByText(/timestep convergence is not established/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/timestep policy is read-only/i)).toBeInTheDocument();
    expect(screen.queryByRole("spinbutton")).not.toBeInTheDocument();
  });

  it("moves focus after deferred source readiness without starting a review", async () => {
    let resolveStatus!: (value: typeof status) => void;
    const pending = new Promise<typeof status>((resolve) => {
      resolveStatus = resolve;
    });
    const service = api({ status: vi.fn(() => pending) });
    render(<Mot3DCampaignCreation api={service} onBack={vi.fn()} />);
    const back = screen.getByRole("button", { name: /Back to home/i });
    back.focus();
    expect(back).toHaveFocus();
    expect(screen.getByText("Checking 3D campaign readiness…")).toBeVisible();
    expect(screen.queryByRole("heading", {
      name: /Create a 3D-MOT Discovery campaign/i,
    })).not.toBeInTheDocument();

    await act(async () => resolveStatus(status));
    const heading = await screen.findByRole("heading", {
      name: /Create a 3D-MOT Discovery campaign/i,
    });
    await waitFor(() => expect(heading).toHaveFocus());
    expect(service.status).toHaveBeenCalledTimes(1);
    expect(service.preview).not.toHaveBeenCalled();
    expect(service.confirm).not.toHaveBeenCalled();
  });

  it("reviews before creation and never implies submission", async () => {
    const service = api();
    render(<Mot3DCampaignCreation api={service} onBack={vi.fn()} />);
    await screen.findByRole("heading", {
      name: /Create a 3D-MOT Discovery campaign/i,
    });
    fireEvent.change(screen.getByLabelText(/Completed 2D-MOT campaign/i), {
      target: { value: hash },
    });
    fireEvent.change(screen.getByLabelText(/3D campaign name/i), {
      target: { value: "mot_3d_run" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Review campaign/i }));
    expect(
      await screen.findByRole("heading", {
        name: /Review the Discovery bootstrap/i,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/one-off study was inconclusive/i),
    ).toBeInTheDocument();
    expect(screen.getByText("10 µs")).toBeInTheDocument();
    expect(screen.getByText("5 µs")).toBeInTheDocument();
    expect(screen.getByText("Not established")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: /Create Discovery campaign/i }),
    );
    expect(
      await screen.findByRole("heading", {
        name: /Discovery campaign prepared/i,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/No job was submitted to Zeus/i),
    ).toBeInTheDocument();
    await waitFor(() => expect(service.confirm).toHaveBeenCalledTimes(1));
  });

  it("suppresses a double-click while bootstrap review is pending", async () => {
    let resolvePreview!: (value: typeof preview) => void;
    const pending = new Promise<typeof preview>((resolve) => {
      resolvePreview = resolve;
    });
    const service = api({ preview: vi.fn(() => pending) });
    render(<Mot3DCampaignCreation api={service} onBack={vi.fn()} />);
    await screen.findByRole("heading", {
      name: /Create a 3D-MOT Discovery campaign/i,
    });
    fireEvent.change(screen.getByLabelText(/Completed 2D-MOT campaign/i), {
      target: { value: hash },
    });
    fireEvent.change(screen.getByLabelText(/3D campaign name/i), {
      target: { value: "mot_3d_run" },
    });
    const review = screen.getByRole("button", { name: /Review campaign/i });
    fireEvent.click(review);
    fireEvent.click(review);
    expect(service.preview).toHaveBeenCalledTimes(1);
    await act(async () => resolvePreview(preview));
  });

  it("suppresses a double-click while bootstrap confirmation is pending", async () => {
    const confirmed = {
      lifecycle: "discovery_prepared" as const,
      campaign_name: "mot_3d_run",
      stage: "discovery" as const,
      submitted_to_zeus: false as const,
      bootstrap_key: "c".repeat(64),
    };
    let resolveConfirm!: (value: typeof confirmed) => void;
    const pending = new Promise<typeof confirmed>((resolve) => {
      resolveConfirm = resolve;
    });
    const service = api({ confirm: vi.fn(() => pending) });
    render(<Mot3DCampaignCreation api={service} onBack={vi.fn()} />);
    await screen.findByRole("heading", {
      name: /Create a 3D-MOT Discovery campaign/i,
    });
    fireEvent.change(screen.getByLabelText(/Completed 2D-MOT campaign/i), {
      target: { value: hash },
    });
    fireEvent.change(screen.getByLabelText(/3D campaign name/i), {
      target: { value: "mot_3d_run" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Review campaign/i }));
    const confirm = await screen.findByRole("button", {
      name: /Create Discovery campaign/i,
    });
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    expect(service.confirm).toHaveBeenCalledTimes(1);
    await act(async () => resolveConfirm(confirmed));
  });
});
