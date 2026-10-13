import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { IndividualZeemanRun, monitorCopy, particleCountAfterModeChange, userVisibleLockedSettings } from "../components/IndividualZeemanRun";
import type { IndividualZeemanApi } from "../api/clients/individualZeeman";

const preview = { preview_token: "token", expires_in_seconds: 300, plan: { run_id: "zeeman-test", family: "zeeman" as const, execution_mode: "local" as const, particle_count: 200, seed: 42, mot_2d_s0: 1.3, mot_2d_detuning_gamma: -0.9196610026631429, mot_2d_magnet_radius_m: 0.04676406447474441, npools: 8, retain_particle_states: true, suitability: "individual_only" as const, output_disposition: "retain_survivor_states" as const, locked_settings: { policy: "canonical" }, resolved_configuration: { solver: { name: "RK4StCustom" }, laser: { detuning: -1 } }, lifecycle_state: "configured" as const, laboratory_specification: { version: 1 }, numerical_policy: { version: 1 }, plan_sha256: "a".repeat(64), execution_started: false as const, submitted_to_zeus: false as const } };
function fake(): IndividualZeemanApi { return { reset: vi.fn(), preview: vi.fn().mockResolvedValue(preview), confirm: vi.fn().mockResolvedValue({ status: "created", run_id: "zeeman-test", family: "zeeman", path: "data/runs/zeeman/zeeman-test", lifecycle_state: "configured", execution_started: false, submitted_to_zeus: false }), startLocal: vi.fn().mockResolvedValue({ status: "queued" }), previewZeus: vi.fn().mockResolvedValue({ preview_token: "ztoken" }), confirmZeus: vi.fn().mockResolvedValue({ status: "submitted" }), refreshZeus: vi.fn().mockResolvedValue({ state: "running" }), runs: vi.fn().mockResolvedValue([]), run: vi.fn() }; }
const deferred = <T,>() => { let resolve!: (value: T) => void; const promise = new Promise<T>((done) => { resolve = done; }); return { promise, resolve }; };

describe("individual Zeeman wizard", () => {
  it("hides fixed internal polarization controls from the user-facing JSON", () => {
    const original = { boundary: { laser: { s0: 1.3, swap_polarization: false } } };
    expect(userVisibleLockedSettings(original)).toEqual({ boundary: { laser: { s0: 1.3 } } });
    expect(original.boundary.laser.swap_polarization).toBe(false);
  });
  it("uses mode-specific particle defaults and limits", async () => {
    const user = userEvent.setup();
    render(<IndividualZeemanRun api={fake()} onBack={vi.fn()} />);
    const particles = screen.getByRole("spinbutton", { name: /particle count/i });
    expect(particles).toHaveValue(200);
    expect(particles).toHaveAttribute("max", "1000");
    await user.click(screen.getByRole("radio", { name: "Zeus" }));
    expect(particles).toHaveValue(50_000);
    expect(particles).toHaveAttribute("max", "50000");
    await user.click(screen.getByRole("radio", { name: "This computer" }));
    expect(particles).toHaveValue(200);
    expect(particles).toHaveAttribute("max", "1000");
  });

  it("preserves a custom particle count when it is valid for the next mode", () => {
    expect(particleCountAfterModeChange(500, "local", "zeus")).toBe(500);
    expect(particleCountAfterModeChange(800, "zeus", "local")).toBe(800);
    expect(particleCountAfterModeChange(5_000, "zeus", "local")).toBe(200);
  });

  it.each([
    [undefined, "Check run progress", false],
    ["configured", "Nothing is running yet", true],
    ["validated", "Validation is complete", true],
    ["reviewed", "Ready to start", true],
    ["queued", "Run is queued", false],
    ["submitted", "Run was submitted", false],
    ["running", "Run is in progress", false],
    ["succeeded", "Run completed", false],
    ["failed", "Run failed safely", true],
    ["outcome_unknown", "Zeus outcome needs attention", true],
    ["cancelled", "Run was cancelled", true],
  ])("describes lifecycle %s truthfully", (state, title, attention) => {
    expect(monitorCopy(state)).toMatchObject({ title, attention });
  });

  it("exposes reviewed run controls and complete locked settings before creation", async () => {
    const api = fake(); const user = userEvent.setup(); render(<IndividualZeemanRun api={api} onBack={vi.fn()} />);
    expect(screen.getByRole("spinbutton", { name: /particle count/i })).toBeInTheDocument();
    expect(screen.getByRole("spinbutton", { name: /random seed/i })).toBeInTheDocument();
    expect(screen.getAllByRole("radio")).toHaveLength(2); expect(screen.getByRole("checkbox")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /validate and review/i }));
    await screen.findByRole("heading", { name: /validated run plan/i });
    expect(screen.getByText(/no files have been created/i)).toBeInTheDocument();
    expect(screen.getByText(/Scientific role: individual only/i)).toBeInTheDocument();
    expect(screen.getByText(/not validated campaign inputs/i)).toBeInTheDocument();
    await user.click(screen.getByText(/view all locked settings/i));
    expect(screen.getByText(/RK4StCustom/)).toBeInTheDocument();
    expect(api.confirm).not.toHaveBeenCalled();
  });

  it("keeps validation inside Configure instead of presenting it as a user step", async () => {
    const api = fake();
    const pending = deferred<Awaited<ReturnType<IndividualZeemanApi["preview"]>>>();
    vi.mocked(api.preview).mockReturnValue(pending.promise);
    const user = userEvent.setup();
    render(<IndividualZeemanRun api={api} onBack={vi.fn()} />);

    expect(screen.queryByText("Validate", { selector: ".run-stepper li" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /validate and review/i }));
    expect(screen.getByRole("button", { name: "Validating…" })).toBeDisabled();
    expect(screen.getByText("Configure", { selector: ".run-stepper li" })).toHaveAttribute("aria-current", "step");

    pending.resolve(preview);
    await screen.findByRole("heading", { name: /validated run plan/i });
    expect(screen.getByText("Review", { selector: ".run-stepper li" })).toHaveAttribute("aria-current", "step");
  });

  it("keeps creation and local start as separate explicit clicks", async () => {
    const api = fake(); const user = userEvent.setup(); render(<IndividualZeemanRun api={api} onBack={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: /validate and review/i }));
    await user.click(await screen.findByRole("button", { name: /create reviewed run/i }));
    await screen.findByText(/nothing is running yet/i); expect(api.startLocal).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: /start on this computer/i }));
    await screen.findByText(/check run progress/i); expect(api.startLocal).toHaveBeenCalledTimes(1);
  });

  it("does not send a second creation confirmation while the first is pending", async () => {
    const api = fake(); const pending = deferred<Awaited<ReturnType<IndividualZeemanApi["confirm"]>>>(); vi.mocked(api.confirm).mockReturnValue(pending.promise);
    const user = userEvent.setup(); render(<IndividualZeemanRun api={api} onBack={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: /validate and review/i })); const create = await screen.findByRole("button", { name: /create reviewed run/i });
    await user.click(create); await user.click(create); expect(api.confirm).toHaveBeenCalledTimes(1);
    pending.resolve({ status: "created", run_id: "zeeman-test", family: "zeeman", path: "data/runs/zeeman/zeeman-test", lifecycle_state: "configured", execution_started: false, submitted_to_zeus: false });
    await screen.findByText(/nothing is running yet/i);
  });

  it("requires a separate Zeus submission review and confirmation", async () => {
    const api = fake(); const user = userEvent.setup(); render(<IndividualZeemanRun api={api} onBack={vi.fn()} />);
    await user.click(screen.getByRole("radio", { name: "Zeus" })); await user.click(screen.getByRole("button", { name: /validate and review/i }));
    await user.click(await screen.findByRole("button", { name: /create reviewed run/i }));
    await user.type(screen.getByLabelText(/Technion username/i), "tal.noa");
    await user.click(screen.getByRole("button", { name: /review Zeus submission/i }));
    await screen.findByText(/ready for confirmation/i); expect(api.confirmZeus).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: /confirm and submit one Zeus job/i }));
    await waitFor(() => expect(api.confirmZeus).toHaveBeenCalledTimes(1));
  });
});
