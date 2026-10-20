import { StrictMode } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  IndividualMot2DRun,
  mot2dMonitorCopy,
  refreshMot2DTransaction,
} from "../components/IndividualMot2DRun";
import type {
  IndividualMot2DApi,
  Mot2DRun,
} from "../api/clients/individualMot2D";

function api(): IndividualMot2DApi {
  return {
    reset: vi.fn(),
    sources: vi.fn().mockResolvedValue([
      {
        id: `mot2d-source-${"a".repeat(32)}`,
        source_kind: "canonical_folder",
        label: "October ensembles",
        ensemble_count: 35,
        available_particle_count: {
          pooled: 10000,
          minimum_per_ensemble: 200,
          maximum_per_ensemble: 400,
        },
        source_qualification: "canonical_campaign_source",
        result_suitability: "individual_only",
        provenance: {},
      },
    ]),
    preview: vi.fn(),
    confirm: vi.fn(),
    startLocal: vi.fn(),
    previewZeus: vi.fn(),
    confirmZeus: vi.fn(),
    refreshZeus: vi.fn(),
    runs: vi.fn(),
    run: vi.fn(),
  } as unknown as IndividualMot2DApi;
}

beforeEach(() => window.localStorage.clear());

describe("IndividualMot2DRun", () => {
  it("drops a superseded local multi-await refresh", async () => {
    let resolve!: (value: Mot2DRun[]) => void,
      active = true;
    const service = api();
    vi.mocked(service.runs).mockReturnValue(
      new Promise((done) => {
        resolve = done;
      }) as ReturnType<IndividualMot2DApi["runs"]>,
    );
    const pending = refreshMot2DTransaction(
      service,
      "local",
      "mot2d-ui",
      "",
      () => active,
    );
    active = false;
    resolve([]);
    await expect(pending).resolves.toBeNull();
    expect(service.run).not.toHaveBeenCalled();
  });
  it("drops a superseded Zeus refresh before reading the run list", async () => {
    let resolve!: (value: { state: string; job_id: string }) => void,
      active = true;
    const service = api();
    vi.mocked(service.refreshZeus).mockReturnValue(
      new Promise<{ state: string; job_id: string }>((done) => {
        resolve = done;
      }) as ReturnType<IndividualMot2DApi["refreshZeus"]>,
    );
    const pending = refreshMot2DTransaction(
      service,
      "zeus",
      "mot2d-ui",
      "tal.noa",
      () => active,
    );
    active = false;
    resolve({ state: "running", job_id: "123.zeus-master" });
    await expect(pending).resolves.toBeNull();
    expect(service.runs).not.toHaveBeenCalled();
  });
  it("shows friendly pooled sources without private paths and applies mode-aware cap", async () => {
    const user = userEvent.setup();
    render(<IndividualMot2DRun api={api()} onBack={vi.fn()} />);
    expect(
      await screen.findByRole("option", { name: /October ensembles/ }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/data\/particle_states/)).not.toBeInTheDocument();
    const particles = screen.getByRole("spinbutton", {
      name: /Particle count/,
    }) as HTMLInputElement;
    expect(particles.max).toBe("1000");
    await user.click(screen.getByLabelText("Zeus"));
    expect(particles.max).toBe("10000");
  });
  it("explains zero and fractional particle counts beside the invalid input", async () => {
    const user = userEvent.setup(),
      service = api();
    render(<IndividualMot2DRun api={service} onBack={vi.fn()} />);
    await screen.findByRole("option", { name: /October ensembles/ });
    const input = screen.getByRole("spinbutton", { name: /Particle count/ });
    for (const value of ["0", "1.5"]) {
      await user.clear(input);
      await user.type(input, value);
      expect(input).toHaveAttribute("aria-invalid", "true");
      expect(input).toHaveAccessibleDescription(/whole number.*starting at 1/);
      expect(
        screen.getByRole("button", { name: "Validate and review" }),
      ).toBeDisabled();
    }
    expect(service.preview).not.toHaveBeenCalled();
  });
  it("uses truthful state-specific monitor copy", () => {
    expect(mot2dMonitorCopy(undefined).title).toMatch(/not been checked/);
    expect(mot2dMonitorCopy("running").body).toMatch(/No action/);
    expect(mot2dMonitorCopy("outcome_unknown").body).toMatch(/Do not resubmit/);
  });
  it("uses the reviewed MOT seed default", async () => {
    render(<IndividualMot2DRun api={api()} onBack={vi.fn()} />);
    await screen.findByRole("option", { name: /October ensembles/ });
    expect(screen.getByRole("spinbutton", { name: /MOT seed/ })).toHaveValue(
      42,
    );
  });
  it("shows an action failure beside the button that triggered it", async () => {
    const user = userEvent.setup(),
      service = api();
    vi.mocked(service.preview).mockRejectedValue(
      new Error("The 2D-MOT run could not be validated."),
    );
    render(<IndividualMot2DRun api={service} onBack={vi.fn()} />);
    await screen.findByRole("option", { name: /October ensembles/ });
    await user.click(
      screen.getByRole("button", { name: "Validate and review" }),
    );
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveClass("action-error");
    expect(alert.closest("form")?.lastElementChild).toBe(alert);
  });
  it("freezes the labelled Zeus identity after submission review", async () => {
    const user = userEvent.setup(),
      service = api(),
      sourceId = `mot2d-source-${"a".repeat(32)}`;
    vi.mocked(service.preview).mockResolvedValue({
      preview_token: "create",
      expires_in_seconds: 300,
      plan: {
        run_id: "mot2d-ui",
        family: "mot_2d",
        source: {
          id: sourceId,
          kind: "canonical_folder",
          qualification: "canonical_campaign_source",
          fingerprint: "a".repeat(64),
          pooled_particle_count: 10000,
        },
        selection: {
          algorithm: "stable",
          version: "1",
          seed: 42,
          selected_count: 200,
          selected_identities_sha256: "b".repeat(64),
        },
        controls: {
          s0: 1.3,
          detuning_gamma: -0.9196610026631429,
          magnet_radius_m: 0.04676406447474441,
        },
        execution: { mode: "zeus", particle_count: 200, mot_seed: 42 },
        retention: { particle_states: true },
        suitability: "individual_only",
        output_disposition: "retain_survivor_states",
        locked_settings: {},
        lifecycle_state: "configured",
        laboratory_specification: {},
        numerical_policy: {},
        plan_sha256: "c".repeat(64),
        execution_started: false,
        submitted_to_zeus: false,
      },
    });
    vi.mocked(service.confirm).mockResolvedValue({
      status: "created",
      run_id: "mot2d-ui",
    });
    vi.mocked(service.previewZeus).mockResolvedValue({
      preview_token: "zeus-review",
      effects: {
        submit_one_job: true,
        reconcile_existing_job: false,
        cancel_job: false,
      },
      job: {
        resources: {
          queue: "zeus_combined_q",
          cores: 200,
          memory_bytes: 68719476736,
          walltime_seconds: 28800,
          vnode: "gd002",
        },
      },
      run_id: "mot2d-ui",
      submission_key: "d".repeat(64),
    });
    render(<IndividualMot2DRun api={service} onBack={vi.fn()} />);
    await screen.findByRole("option", { name: /October ensembles/ });
    await user.click(screen.getByLabelText("Zeus"));
    await user.click(
      screen.getByRole("button", { name: "Validate and review" }),
    );
    expect(await screen.findByText("Selection seed")).toBeVisible();
    expect(screen.getByText("MOT seed")).toBeVisible();
    await user.click(
      await screen.findByRole("button", { name: "Create reviewed run" }),
    );
    const username = await screen.findByLabelText("Technion username");
    await user.type(username, "tal.noa");
    await user.click(
      screen.getByRole("button", { name: "Review Zeus submission" }),
    );
    expect(await screen.findByText("Zeus submission reviewed")).toBeVisible();
    expect(screen.getByText("64 GiB")).toBeVisible();
    expect(screen.getByText("Test compute node")).toBeVisible();
    expect(screen.getByText("gd002")).toBeVisible();
    expect(screen.getByText("8 hours")).toBeVisible();
    expect(screen.getByText("zeus_combined_q")).toBeVisible();

    expect(username).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Change connection" }));
    expect(username).toBeEnabled();
    expect(screen.queryByText("64 GiB")).not.toBeInTheDocument();
    vi.mocked(service.confirmZeus).mockResolvedValue({
      status: "submitted",
      run_id: "mot2d-ui",
      job_id: "987.zeus-master",
      submission_key: "d".repeat(64),
    });
    await user.click(
      screen.getByRole("button", { name: "Review Zeus submission" }),
    );
    await user.click(
      await screen.findByRole("button", {
        name: "Confirm and submit one Zeus job",
      }),
    );
    expect(await screen.findByText(/987.zeus-master/)).toBeVisible();
    expect(service.confirmZeus).toHaveBeenCalledOnce();
  });
  it("shows validated provenance with explicit result metrics", async () => {
    const user = userEvent.setup(),
      service = api(),
      sourceId = `mot2d-source-${"a".repeat(32)}`,
      base = {
        id: `individual-run-${"a".repeat(24)}`,
        display_name: "mot2d-ui",
        record_state: "succeeded",
        lifecycle: "results_ready",
        execution: { mode: "local" as const, zeus_job_id: null },
        retention: { particle_states_requested: true, status: "retained" },
        results: {
          availability: "verified",
          completed_at: "2026-10-11T00:00:00Z",
        },
      };
    vi.mocked(service.preview).mockResolvedValue({
      preview_token: "create",
      expires_in_seconds: 300,
      plan: {
        run_id: "mot2d-ui",
        family: "mot_2d",
        source: {
          id: sourceId,
          kind: "canonical_folder",
          qualification: "canonical_campaign_source",
          fingerprint: "a".repeat(64),
          pooled_particle_count: 10000,
        },
        selection: {
          algorithm: "stable",
          version: "1",
          seed: 42,
          selected_count: 200,
          selected_identities_sha256: "b".repeat(64),
        },
        controls: {
          s0: 1.3,
          detuning_gamma: -0.9196610026631429,
          magnet_radius_m: 0.04676406447474441,
        },
        execution: { mode: "local", particle_count: 200, mot_seed: 42 },
        retention: { particle_states: true },
        suitability: "individual_only",
        output_disposition: "retain_survivor_states",
        locked_settings: {},
        lifecycle_state: "configured",
        laboratory_specification: {},
        numerical_policy: {},
        plan_sha256: "c".repeat(64),
        execution_started: false,
        submitted_to_zeus: false,
      },
    });
    vi.mocked(service.confirm).mockResolvedValue({
      status: "created",
      run_id: "mot2d-ui",
    });
    vi.mocked(service.startLocal).mockResolvedValue({
      status: "queued",
      run_id: "mot2d-ui",
    });
    vi.mocked(service.runs).mockResolvedValue([base]);
    vi.mocked(service.run).mockResolvedValue({
      ...base,
      metrics: {
        n_input: 200,
        n_survivors: 50,
        conditional_efficiency: 0.25,
        elapsed_s: 1.5,
        selection_sha256: "d".repeat(64),
        provenance: {},
      },
      provenance: { git_revision: "reviewed-commit" },
    });
    const onBack = vi.fn();
    render(<IndividualMot2DRun api={service} onBack={onBack} />);
    await screen.findByRole("option", { name: /October ensembles/ });
    await user.click(
      screen.getByRole("button", { name: "Validate and review" }),
    );
    await user.click(
      await screen.findByRole("button", { name: "Create reviewed run" }),
    );
    await user.click(
      screen.getByRole("button", { name: "Start on this computer" }),
    );
    await user.click(screen.getByRole("button", { name: "Check status" }));
    expect(await screen.findByText("25.000%")).toBeVisible();
    await user.click(screen.getByText("Technical provenance"));
    expect(screen.getByText(/reviewed-commit/)).toBeVisible();
    await user.click(
      screen.getByRole("button", { name: "Configure another simulation" }),
    );
    expect(onBack).toHaveBeenCalledOnce();
    expect(
      window.localStorage.getItem("ytterbium.individual-run.mot_2d.v1"),
    ).toBeNull();
  });
  it.each(["local", "zeus"] as const)(
    "restores a completed %s run under StrictMode without restarting or reconnecting",
    async (mode) => {
      const service = api();
      const completed = {
        id: `individual-run-${"a".repeat(24)}`,
        display_name: "mot2d-ui",
        lifecycle: "results_ready",
        record_state: "succeeded",
        execution: {
          mode,
          zeus_job_id: mode === "zeus" ? "123.zeus-master" : null,
        },
        retention: { status: "retained", particle_states_requested: true },
        results: {
          availability: "verified",
          completed_at: "2026-10-18T17:40:00Z",
        },
        metrics: {
          n_input: 20,
          n_survivors: 1,
          conditional_efficiency: 0.05,
          elapsed_s: 1,
        },
        provenance: {},
      } as unknown as Awaited<ReturnType<IndividualMot2DApi["run"]>>;
      window.localStorage.setItem(
        "ytterbium.individual-run.mot_2d.v1",
        JSON.stringify({
          version: 1,
          family: "mot_2d",
          display_name: "mot2d-ui",
          execution_mode: mode,
          ...(mode === "zeus" ? { username: "tal.noa" } : {}),
        }),
      );
      vi.mocked(service.runs).mockResolvedValue([completed]);
      vi.mocked(service.run).mockResolvedValue(completed);
      service.recoverZeus = vi.fn().mockRejectedValue(new Error("offline"));
      render(
        <StrictMode>
          <IndividualMot2DRun api={service} onBack={vi.fn()} />
        </StrictMode>,
      );
      expect(
        await screen.findByRole("heading", {
          name: "Verified results are ready",
        }),
      ).toBeVisible();
      expect(service.recoverZeus).not.toHaveBeenCalled();
      expect(service.confirm).not.toHaveBeenCalled();
      expect(service.startLocal).not.toHaveBeenCalled();
    },
  );
});
