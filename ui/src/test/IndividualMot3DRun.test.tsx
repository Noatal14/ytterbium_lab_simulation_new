import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type {
  AngledDonutParameters,
  IndividualMot3DApi,
  Mot3DFamily,
  Mot3DPreview,
  Mot3DRequest,
  SinglePassParameters,
} from "../api/clients/individualMot3D";
import { IndividualMot3DRun } from "../components/IndividualMot3DRun";
import { MOT_3D_INDIVIDUAL_SPECIFICATION_V1 as spec } from "../generated/mot3dIndividualSpec.v1";

const sourceId = `mot3d-source-${"a".repeat(32)}`;
const source = {
  id: sourceId,
  source_kind: "canonical_2d_campaign" as const,
  label: "October 2D-MOT campaign",
  ensemble_count: 20,
  available_particle_count: {
    pooled: 12_000,
    minimum_per_ensemble: 500,
    maximum_per_ensemble: 700,
  },
  source_qualification: "canonical_campaign_source" as const,
  result_suitability: "individual_only" as const,
  provenance: {},
};

function previewFor(request: Mot3DRequest): Mot3DPreview {
  const geometry = request.geometry_family === "angled_donut"
    ? {
        family: "angled_donut" as const,
        parameters: request.parameters as AngledDonutParameters,
        derived_parameters: {},
      }
    : {
        family: "single_pass" as const,
        parameters: request.parameters as SinglePassParameters,
        derived_parameters: {
          blue_detuning_gamma: -2.58,
          effective_slowing_z_offset_m: -0.044,
          effective_slowing_field_G: 12.5,
          reference_slowing_field_G: 10.25,
        },
      };
  return {
    preview_token: "review-token",
    expires_in_seconds: 300,
    plan: {
      run_id: "mot3d-browser",
      family: "mot_3d",
      source: {
        id: sourceId,
        kind: source.source_kind,
        qualification: source.source_qualification,
        fingerprint: "a".repeat(64),
        pooled_particle_count: source.available_particle_count.pooled,
      },
      selection: {
        algorithm: spec.sampling.algorithm,
        version: spec.sampling.version,
        seed: request.selection_seed,
        selected_count: request.particle_count,
        selected_identities_sha256: "b".repeat(64),
      },
      geometry,
      execution: {
        mode: request.execution_mode,
        particle_count: request.particle_count,
        simulation_seed: request.simulation_seed,
      },
      retention: { particle_states: request.retain_particle_states },
      suitability: "individual_only",
      output_disposition: request.retain_particle_states ? "retain_survivor_states" : "discard_survivor_states_after_summary",
      locked_settings: {
        ...spec.fixed_classification,
        sampling_algorithm: spec.sampling.algorithm,
        sampling_version: spec.sampling.version,
        workers: spec.workers_by_execution_mode[request.execution_mode],
      },
      lifecycle_state: "configured",
      laboratory_specification: spec.authority_references.laboratory_specification,
      numerical_policy: spec.authority_references.numerical_policy,
      plan_sha256: "c".repeat(64),
      execution_started: false,
      submitted_to_zeus: false,
    },
  };
}

function service(): IndividualMot3DApi {
  return {
    reset: vi.fn(),
    sources: vi.fn().mockResolvedValue([source]),
    preview: vi.fn().mockImplementation((request: Mot3DRequest) => Promise.resolve(previewFor(request))),
    confirm: vi.fn().mockResolvedValue({
      status: "created",
      run_id: "mot3d-browser",
      family: "mot_3d",
      path: "data/runs/mot_3d/mot3d-browser",
      lifecycle_state: "configured",
      execution_started: false,
      submitted_to_zeus: false,
    }),
    runs: vi.fn(),
    run: vi.fn(),
  } as unknown as IndividualMot3DApi;
}

async function waitForSource() {
  await screen.findByRole("option", { name: /October 2D-MOT campaign/ });
}

describe("IndividualMot3DRun", () => {
  it("uses a friendly source selector and execution-aware particle limits", async () => {
    const user = userEvent.setup();
    render(<IndividualMot3DRun api={service()} onBack={vi.fn()} />);
    await waitForSource();
    expect(screen.queryByText(/data\/particle_states/)).not.toBeInTheDocument();
    const particles = screen.getByRole("spinbutton", { name: /Particle count/ });
    expect(particles).toHaveAttribute("max", "1000");
    await user.click(screen.getByLabelText("Zeus"));
    expect(particles).toHaveAttribute("max", "12000");
  });

  it("reviews and creates an angled-donut record without starting execution", async () => {
    const user = userEvent.setup(), api = service();
    render(<IndividualMot3DRun api={api} onBack={vi.fn()} />);
    await waitForSource();
    await user.click(screen.getByRole("button", { name: "Validate setup" }));
    expect(await screen.findByRole("heading", { name: "Angled-donut parameters" })).toBeVisible();
    const request = vi.mocked(api.preview).mock.calls[0][0];
    expect(request.geometry_family).toBe("angled_donut");
    expect(request.parameters).toEqual(spec.defaults.angled_donut);
    await user.click(screen.getByRole("button", { name: "Create run record" }));
    expect(await screen.findByText("Run record created")).toBeVisible();
    expect(screen.getByText(/No simulation has started/)).toBeVisible();
    expect(api.confirm).toHaveBeenCalledTimes(1);
  });

  it("shows exact backend-derived single-pass values in review", async () => {
    const user = userEvent.setup(), api = service();
    render(<IndividualMot3DRun api={api} onBack={vi.fn()} />);
    await waitForSource();
    await user.click(screen.getByRole("radio", { name: /^Single pass/ }));
    await user.click(screen.getByRole("button", { name: "Validate setup" }));
    expect(await screen.findByRole("heading", { name: "Derived single-pass values" })).toBeVisible();
    expect(screen.getByText("-2.58 Γ")).toBeVisible();
    expect(screen.getByText("-44 mm")).toBeVisible();
    expect(screen.getByText("12.5 G")).toBeVisible();
    expect(screen.getByText("10.25 G")).toBeVisible();
    expect(vi.mocked(api.preview).mock.calls[0][0]).toMatchObject({
      geometry_family: "single_pass",
      parameters: spec.defaults.single_pass,
    });
  });

  it("drops a source response after unmount", async () => {
    let resolve!: (value: typeof source[]) => void;
    const api = service();
    vi.mocked(api.sources).mockReturnValue(new Promise((done) => { resolve = done; }));
    const view = render(<IndividualMot3DRun api={api} onBack={vi.fn()} />);
    view.unmount();
    resolve([source]);
    await waitFor(() => expect(api.sources).toHaveBeenCalledTimes(1));
  });

  it.each<Mot3DFamily>(["angled_donut", "single_pass"])("keeps the %s form within reviewed ranges", async (family) => {
    const user = userEvent.setup();
    render(<IndividualMot3DRun api={service()} onBack={vi.fn()} />);
    await waitForSource();
    if (family === "single_pass") await user.click(screen.getByRole("radio", { name: /^Single pass/ }));
    expect(screen.getByRole("button", { name: "Validate setup" })).toBeEnabled();
  });
});
