import { afterEach, describe, expect, it, vi } from "vitest";
import { createIndividualMot3DApi, type Mot3DRequest } from "../api/clients/individualMot3D";
import { MOT_3D_INDIVIDUAL_SPECIFICATION_V1 } from "../generated/mot3dIndividualSpec.v1";

const envelope = (data: unknown) => Promise.resolve(new Response(JSON.stringify({ api_version: 1, data }), { status: 200, headers: { "Content-Type": "application/json" } }));
const sourceId = `mot3d-source-${"a".repeat(32)}`;
const request: Mot3DRequest = {
  source_id: sourceId,
  geometry_family: "angled_donut",
  particle_count: 20,
  selection_seed: 1,
  simulation_seed: 2,
  parameters: {
    green_s0: 30, green_detuning_gamma: -25, green_waist_m: 0.0075,
    blue_s0: 1.5, blue_waist_m: 0.0075, magnetic_gradient_G_cm: 2.5,
    blue_detuning_gamma: -3, core_shell_split_radius_m: 0.0025,
  },
  retain_particle_states: false,
  execution_mode: "local",
};
const preview = () => ({
  preview_token: "preview-token", expires_in_seconds: 300,
  plan: {
    run_id: "mot3d-test", family: "mot_3d",
    source: { id: sourceId, kind: "canonical_2d_campaign", qualification: "canonical_campaign_source", fingerprint: "b".repeat(64), pooled_particle_count: 100 },
    selection: { algorithm: MOT_3D_INDIVIDUAL_SPECIFICATION_V1.sampling.algorithm, version: MOT_3D_INDIVIDUAL_SPECIFICATION_V1.sampling.version, seed: 1, selected_count: 20, selected_identities_sha256: "c".repeat(64) },
    geometry: { family: "angled_donut", parameters: { ...request.parameters } },
    execution: { mode: "local", particle_count: 20, simulation_seed: 2 },
    retention: { particle_states: false }, suitability: "individual_only",
    output_disposition: "discard_survivor_states_after_summary",
    locked_settings: {
      solver: MOT_3D_INDIVIDUAL_SPECIFICATION_V1.fixed_classification.solver,
      timestep_s: MOT_3D_INDIVIDUAL_SPECIFICATION_V1.fixed_classification.timestep_s,
      t_max_s: MOT_3D_INDIVIDUAL_SPECIFICATION_V1.fixed_classification.t_max_s,
      convergence_claim: MOT_3D_INDIVIDUAL_SPECIFICATION_V1.fixed_classification.convergence_claim,
      capture: { ...MOT_3D_INDIVIDUAL_SPECIFICATION_V1.fixed_classification.capture },
      sampling_algorithm: MOT_3D_INDIVIDUAL_SPECIFICATION_V1.sampling.algorithm,
      sampling_version: MOT_3D_INDIVIDUAL_SPECIFICATION_V1.sampling.version,
      workers: MOT_3D_INDIVIDUAL_SPECIFICATION_V1.workers_by_execution_mode.local,
    },
    lifecycle_state: "configured",
    laboratory_specification: { ...MOT_3D_INDIVIDUAL_SPECIFICATION_V1.authority_references.laboratory_specification },
    numerical_policy: { ...MOT_3D_INDIVIDUAL_SPECIFICATION_V1.authority_references.numerical_policy },
    plan_sha256: "d".repeat(64), execution_started: false, submitted_to_zeus: false,
  },
});
const created = { status: "created", run_id: "mot3d-test", family: "mot_3d", path: "data/runs/mot_3d/mot3d-test", lifecycle_state: "configured", execution_started: false, submitted_to_zeus: false };
const summary = (kind = "mot_3d") => ({
  id: `individual-run-${"e".repeat(24)}`, record_kind: "individual_simulation_run", run_kind: kind,
  display_name: kind === "mot_3d" ? "mot3d-test" : "zeeman-test", stage_semantics: "single-run-lifecycle", source: "local",
  queried_at: "2026-10-12T12:00:00+00:00", trust: "verified-package", scientific_role: "individual-only",
  record_state: "configured", integrity: "active", lifecycle: "configured", next_action: "none",
  created_at: "2026-10-12T12:00:00+00:00", updated_at: "2026-10-12T12:00:00+00:00",
  execution: { mode: "local", zeus_job_id: null }, retention: { particle_states_requested: false, status: "pending" },
  results: { availability: "not_ready", completed_at: null }, warnings: [],
});

afterEach(() => vi.unstubAllGlobals());

describe("individual 3D-MOT frontend contract", () => {
  it("exposes the reviewed versioned limits and independent horizon", () => {
    expect(MOT_3D_INDIVIDUAL_SPECIFICATION_V1.spec_version).toBe("mot-3d-individual-v1");
    expect(MOT_3D_INDIVIDUAL_SPECIFICATION_V1.particle_count.maximum_by_execution_mode).toEqual({ local: 1000, zeus: 50000 });
    expect(MOT_3D_INDIVIDUAL_SPECIFICATION_V1.fixed_classification).toMatchObject({ timestep_s: 10e-6, t_max_s: 0.1, convergence_claim: "not_established" });
  });

  it("accepts a verified canonical source without exposing paths", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(await envelope({
      contract_version: "mot-3d-individual-source-catalog-v1",
      sources: [{
        id: sourceId, source_kind: "canonical_2d_campaign", label: "campaign · s0 1.3", ensemble_count: 20,
        available_particle_count: { pooled: 100, minimum_per_ensemble: 5, maximum_per_ensemble: 5 },
        source_qualification: "canonical_campaign_source", result_suitability: "individual_only",
        provenance: { validation: "completed_canonical_2d_campaign", campaign_name: "campaign", s0: 1.3, ensemble_count: 20, campaign_sha256: "a".repeat(64), final_report_sha256: "b".repeat(64), fingerprint: "c".repeat(64) },
      }], invalid_count: 0, total: 1, truncated: false,
    })));
    const rows = await createIndividualMot3DApi(async () => "csrf").sources();
    expect(rows).toHaveLength(1);
    expect(JSON.stringify(rows)).not.toContain("data/particle_states");
  });

  it("rejects an extra source path at the trust boundary", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(await envelope({
      contract_version: "mot-3d-individual-source-catalog-v1",
      sources: [{ id: sourceId, source_kind: "canonical_2d_campaign", label: "campaign", ensemble_count: 1, available_particle_count: { pooled: 1, minimum_per_ensemble: 1, maximum_per_ensemble: 1 }, source_qualification: "canonical_campaign_source", result_suitability: "individual_only", provenance: {}, path: "secret" }],
      invalid_count: 0, total: 1, truncated: false,
    })));
    await expect(createIndividualMot3DApi(async () => "csrf").sources()).rejects.toThrow(/Invalid/);
  });

  it("binds confirmation to the exact reviewed request and deduplicates double clicks", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(await envelope(preview())).mockResolvedValue(await envelope(created));
    vi.stubGlobal("fetch", fetchMock);
    const api = createIndividualMot3DApi(async () => "csrf"), reviewed = await api.preview(request);
    const [first, second] = await Promise.all([api.confirm(reviewed.preview_token), api.confirm(reviewed.preview_token)]);
    expect(first).toEqual(second);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it.each([
    ["extra plan field", (row: ReturnType<typeof preview>) => Object.assign(row.plan, { path: "secret" })],
    ["wrong family parameters", (row: ReturnType<typeof preview>) => { (row.plan.geometry.parameters as unknown as Record<string, number>).blue_detuning_gamma = -7; }],
    ["local count over cap", (row: ReturnType<typeof preview>) => { row.plan.execution.particle_count = 1001; row.plan.selection.selected_count = 1001; row.plan.source.pooled_particle_count = 2000; }],
    ["contradictory retention", (row: ReturnType<typeof preview>) => { row.plan.retention.particle_states = true; }],
    ["changed sampling algorithm", (row: ReturnType<typeof preview>) => { row.plan.selection.algorithm = "other" as typeof row.plan.selection.algorithm; }],
    ["changed locked timestep", (row: ReturnType<typeof preview>) => { row.plan.locked_settings.timestep_s = 0.01 as typeof row.plan.locked_settings.timestep_s; }],
    ["omitted capture safeguard", (row: ReturnType<typeof preview>) => { delete (row.plan.locked_settings as unknown as Record<string, unknown>).capture; }],
    ["changed capture safeguard", (row: ReturnType<typeof preview>) => { row.plan.locked_settings.capture.capture_radius_m = 0.1 as typeof row.plan.locked_settings.capture.capture_radius_m; }],
    ["malformed laboratory specification", (row: ReturnType<typeof preview>) => { delete (row.plan.laboratory_specification as unknown as Record<string, unknown>).sha256; }],
    ["malformed numerical policy", (row: ReturnType<typeof preview>) => { Object.assign(row.plan.numerical_policy, { path: "private" }); }],
    ["changed laboratory authority", (row: ReturnType<typeof preview>) => { (row.plan.laboratory_specification as unknown as Record<string, unknown>).sha256 = "0".repeat(64); }],
    ["changed numerical authority", (row: ReturnType<typeof preview>) => { (row.plan.numerical_policy as unknown as Record<string, unknown>).version = "numerical-policy-v2"; }],
  ])("rejects %s", async (_label, mutate) => {
    const row = structuredClone(preview()); mutate(row);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(await envelope(row)));
    await expect(createIndividualMot3DApi(async () => "csrf").preview(request)).rejects.toThrow(/Invalid/);
  });

  it("suppresses an older preview response", async () => {
    let resolveFirst!: (response: Response) => void;
    const first = new Promise<Response>((resolve) => { resolveFirst = resolve; });
    vi.stubGlobal("fetch", vi.fn().mockReturnValueOnce(first).mockResolvedValueOnce(await envelope({ ...preview(), preview_token: "new" })));
    const api = createIndividualMot3DApi(async () => "csrf"), older = api.preview(request);
    await api.preview({ ...request, simulation_seed: 3 }).catch(() => undefined);
    resolveFirst(await envelope(preview()));
    await expect(older).rejects.toThrow(/stale/);
  });

  it("filters other run kinds before strict 3D decoding", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(await envelope({ runs: [summary("zeeman"), summary()], invalid_count: 0, total: 2, truncated: false })));
    const rows = await createIndividualMot3DApi(async () => "csrf").runs();
    expect(rows.map((row: { display_name: string }) => row.display_name)).toEqual(["mot3d-test"]);
  });

  it("rejects malformed 3D run summaries", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(await envelope({ runs: [{ ...summary(), secret: "path" }], invalid_count: 0, total: 1, truncated: false })));
    await expect(createIndividualMot3DApi(async () => "csrf").runs()).rejects.toThrow(/Invalid/);
  });
});
