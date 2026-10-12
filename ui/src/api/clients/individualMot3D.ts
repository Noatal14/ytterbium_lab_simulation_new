import { MOT_3D_INDIVIDUAL_SPECIFICATION_V1 as spec } from "../../generated/mot3dIndividualSpec.v1";
import { exactKeys, getData, isRecord, postData } from "../http/envelope";

export type Mot3DMode = "local" | "zeus";
export type Mot3DFamily = "angled_donut" | "single_pass";
type CommonParameters = {
  green_s0: number;
  green_detuning_gamma: number;
  green_waist_m: number;
  blue_s0: number;
  blue_waist_m: number;
  magnetic_gradient_G_cm: number;
};
export type AngledDonutParameters = CommonParameters & {
  blue_detuning_gamma: number;
  core_shell_split_radius_m: number;
};
export type SinglePassParameters = CommonParameters & {
  blue_detuning_anchor_gamma: number;
  blue_crossing_angle_deg: number;
  blue_crossing_z_offset_m: number;
};
export type SinglePassDerivedParameters = {
  blue_detuning_gamma: number;
  effective_slowing_z_offset_m: number;
  effective_slowing_field_G: number;
  reference_slowing_field_G: number;
};
type Mot3DRequestBase = {
  source_id: string;
  particle_count: number;
  selection_seed: number;
  simulation_seed: number;
  retain_particle_states: boolean;
  execution_mode: Mot3DMode;
};
export type Mot3DRequest = Mot3DRequestBase & (
  | { geometry_family: "angled_donut"; parameters: AngledDonutParameters }
  | { geometry_family: "single_pass"; parameters: SinglePassParameters }
);
type SpecificationReference = { version: string; sha256: string };
type LockedSettings = {
  solver: typeof spec.fixed_classification.solver;
  timestep_s: typeof spec.fixed_classification.timestep_s;
  t_max_s: typeof spec.fixed_classification.t_max_s;
  convergence_claim: typeof spec.fixed_classification.convergence_claim;
  capture: typeof spec.fixed_classification.capture;
  sampling_algorithm: typeof spec.sampling.algorithm;
  sampling_version: typeof spec.sampling.version;
  workers: number;
};
export type Mot3DSource = {
  id: string;
  source_kind: "canonical_2d_campaign" | "retained_individual_mot_2d";
  label: string;
  ensemble_count: number;
  available_particle_count: {
    pooled: number;
    minimum_per_ensemble: number;
    maximum_per_ensemble: number;
  };
  source_qualification: "canonical_campaign_source" | "verified_individual_result";
  result_suitability: "individual_only";
  provenance: Record<string, unknown>;
};
export type Mot3DPreview = {
  preview_token: string;
  expires_in_seconds: number;
  plan: {
    run_id: string;
    family: "mot_3d";
    source: { id: string; kind: Mot3DSource["source_kind"]; qualification: Mot3DSource["source_qualification"]; fingerprint: string; pooled_particle_count: number };
    selection: { algorithm: typeof spec.sampling.algorithm; version: typeof spec.sampling.version; seed: number; selected_count: number; selected_identities_sha256: string };
    geometry:
      | { family: "angled_donut"; parameters: AngledDonutParameters; derived_parameters: Record<never, never> }
      | { family: "single_pass"; parameters: SinglePassParameters; derived_parameters: SinglePassDerivedParameters };
    execution: { mode: Mot3DMode; particle_count: number; simulation_seed: number };
    retention: { particle_states: boolean };
    suitability: "individual_only";
    output_disposition: "retain_survivor_states" | "discard_survivor_states_after_summary";
    locked_settings: LockedSettings;
    lifecycle_state: "configured";
    laboratory_specification: SpecificationReference;
    numerical_policy: SpecificationReference;
    plan_sha256: string;
    execution_started: false;
    submitted_to_zeus: false;
  };
};
export type CreatedMot3DRun = {
  status: "created";
  run_id: string;
  family: "mot_3d";
  path: string;
  lifecycle_state: "configured";
  execution_started: false;
  submitted_to_zeus: false;
};
export type StartedLocalMot3DRun = {
  status: "queued";
  run_id: string;
  execution_mode: "local";
};
export type Mot3DRun = {
  id: string;
  display_name: string;
  record_state: string;
  lifecycle: string;
  next_action: string;
  execution: { mode: Mot3DMode; zeus_job_id: string | null };
  retention: { particle_states_requested: boolean; status: string };
  results: { availability: string; completed_at: string | null };
  metrics?: Mot3DResultMetrics | null;
  error?: { code: string; message: string } | null;
};
export type Mot3DResultProvenance = {
  git_revision: string;
  configuration_sha256: string;
  inputs_sha256: string;
  laboratory_spec_sha256: string;
  numerical_policy_sha256: string;
  admission_specification_sha256: string;
  source_id: string;
  source_fingerprint: string;
  selection_algorithm: typeof spec.sampling.algorithm;
  selection_version: typeof spec.sampling.version;
  selection_seed: number;
  simulation_seed: number;
  geometry_family: Mot3DFamily;
  solver: typeof spec.fixed_classification.solver;
  timestep_s: typeof spec.fixed_classification.timestep_s;
  t_max_s: typeof spec.fixed_classification.t_max_s;
  convergence_claim: typeof spec.fixed_classification.convergence_claim;
};
export type Mot3DResultMetrics = {
  n_input: number;
  usable_at_end_count: number;
  usable_at_end_fraction: number;
  residence_qualified_captured_count: number;
  residence_qualified_captured_fraction: number;
  elapsed_s: number;
  selection_sha256: string;
  provenance: Mot3DResultProvenance;
};

type CreationContext = { runId: string; request: Mot3DRequest; csrf: string; generation: number };
type Profile = { username: string; project_directory: string };
type ZeusContext = { runId: string; profile: Profile; submissionKey: string; csrf: string; generation: number };
// eslint-disable-next-line no-control-regex
const printable = (value: unknown, maximum = 512): value is string => typeof value === "string" && value.length > 0 && value.length <= maximum && !/[\u0000-\u001f\u007f]/.test(value);
const integer = (value: unknown): value is number => Number.isInteger(value);
const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
const hex64 = (value: unknown): value is string => typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
const sourceId = (value: unknown): value is string => typeof value === "string" && /^mot3d-source-[0-9a-f]{32}$/.test(value);
const privateRunId = (value: unknown): value is string => typeof value === "string" && /^mot3d-[a-z0-9-]{1,120}$/.test(value);
const publicRunId = (value: unknown): value is string => typeof value === "string" && /^individual-run-[0-9a-f]{24}$/.test(value);
const jobId = (value: unknown): value is string => typeof value === "string" && /^\d+\.zeus-master$/.test(value);
const invalid = (part: string): never => { throw new Error(`Invalid individual 3D-MOT ${part} response.`); };
const makeProfile = (username: string): Profile => ({ username, project_directory: `/home/${username}/ytterbium_lab_simulation_new` });
const sameProfile = (left: Profile, right: Profile) => left.username === right.username && left.project_directory === right.project_directory;

function parseSources(value: unknown): Mot3DSource[] {
  if (!isRecord(value) || !exactKeys(value, ["contract_version", "sources", "invalid_count", "total", "truncated"]) || value.contract_version !== "mot-3d-individual-source-catalog-v1" || !Array.isArray(value.sources) || !integer(value.invalid_count) || Number(value.invalid_count) < 0 || value.total !== value.sources.length || typeof value.truncated !== "boolean") invalid("source catalog");
  const catalog = value as Record<string, unknown>;
  return (catalog.sources as unknown[]).map((candidate: unknown) => {
    if (!isRecord(candidate) || !exactKeys(candidate, ["id", "source_kind", "label", "ensemble_count", "available_particle_count", "source_qualification", "result_suitability", "provenance"]) || !sourceId(candidate.id) || !printable(candidate.label, 256) || !integer(candidate.ensemble_count) || Number(candidate.ensemble_count) < 1 || candidate.result_suitability !== "individual_only" || !isRecord(candidate.available_particle_count) || !isRecord(candidate.provenance)) invalid("source catalog");
    const row = candidate as Record<string, unknown>, counts = row.available_particle_count as Record<string, unknown>;
    if (!exactKeys(counts, ["pooled", "minimum_per_ensemble", "maximum_per_ensemble"]) || ![counts.pooled, counts.minimum_per_ensemble, counts.maximum_per_ensemble].every(integer) || Number(counts.minimum_per_ensemble) < 1 || Number(counts.minimum_per_ensemble) > Number(counts.maximum_per_ensemble) || Number(counts.pooled) < Number(counts.maximum_per_ensemble)) invalid("source catalog");
    const provenance = row.provenance as Record<string, unknown>;
    if (row.source_kind === "canonical_2d_campaign") {
      if (row.source_qualification !== "canonical_campaign_source" || !exactKeys(provenance, ["validation", "campaign_name", "s0", "ensemble_count", "campaign_sha256", "final_report_sha256", "fingerprint"]) || provenance.validation !== "completed_canonical_2d_campaign" || !printable(provenance.campaign_name, 128) || !finite(provenance.s0) || provenance.ensemble_count !== row.ensemble_count || !hex64(provenance.campaign_sha256) || !hex64(provenance.final_report_sha256) || !hex64(provenance.fingerprint)) invalid("source catalog");
    } else if (row.source_kind === "retained_individual_mot_2d") {
      if (row.source_qualification !== "verified_individual_result" || !exactKeys(provenance, ["validation", "completed_at", "public_run_id", "scientific_summary", "fingerprint"]) || provenance.validation !== "verified_retained_individual_result" || !printable(provenance.completed_at) || !publicRunId(provenance.public_run_id) || !isRecord(provenance.scientific_summary) || !exactKeys(provenance.scientific_summary, ["s0", "detuning_gamma", "magnet_radius_m"]) || ![provenance.scientific_summary.s0, provenance.scientific_summary.detuning_gamma, provenance.scientific_summary.magnet_radius_m].every(finite) || !hex64(provenance.fingerprint)) invalid("source catalog");
    } else invalid("source catalog");
    return row as unknown as Mot3DSource;
  });
}

const commonParameterKeys = ["green_s0", "green_detuning_gamma", "green_waist_m", "blue_s0", "blue_waist_m", "magnetic_gradient_G_cm"];
function validParameters(family: Mot3DFamily, value: unknown): value is AngledDonutParameters | SinglePassParameters {
  if (!isRecord(value)) return false;
  const familyKeys = family === "angled_donut" ? ["blue_detuning_gamma", "core_shell_split_radius_m"] : ["blue_detuning_anchor_gamma", "blue_crossing_angle_deg", "blue_crossing_z_offset_m"];
  if (!exactKeys(value, [...commonParameterKeys, ...familyKeys])) return false;
  const controls = { ...spec.common_controls, ...spec.family_controls[family] } as Record<string, { minimum: number; maximum: number }>;
  return Object.entries(controls).every(([name, bounds]) => finite(value[name]) && Number(value[name]) >= bounds.minimum && Number(value[name]) <= bounds.maximum);
}

function sameParameters(family: Mot3DFamily, left: unknown, right: unknown): boolean {
  if (!validParameters(family, left) || !validParameters(family, right)) return false;
  const keys = [...commonParameterKeys, ...Object.keys(spec.family_controls[family])];
  const leftRecord = left as unknown as Record<string, number>, rightRecord = right as unknown as Record<string, number>;
  return keys.every((key) => leftRecord[key] === rightRecord[key]);
}

function validDerivedParameters(family: Mot3DFamily, value: unknown): boolean {
  if (!isRecord(value)) return false;
  if (family === "angled_donut") return exactKeys(value, []);
  return exactKeys(value, ["blue_detuning_gamma", "effective_slowing_z_offset_m", "effective_slowing_field_G", "reference_slowing_field_G"])
    && [value.blue_detuning_gamma, value.effective_slowing_z_offset_m, value.effective_slowing_field_G, value.reference_slowing_field_G].every(finite);
}

function validSpecificationReference(value: unknown, expected: SpecificationReference): value is SpecificationReference {
  return isRecord(value)
    && exactKeys(value, ["version", "sha256"])
    && value.version === expected.version
    && value.sha256 === expected.sha256;
}

function validLockedSettings(value: unknown, mode: Mot3DMode): value is LockedSettings {
  if (!isRecord(value) || !exactKeys(value, ["solver", "timestep_s", "t_max_s", "convergence_claim", "capture", "sampling_algorithm", "sampling_version", "workers"])) return false;
  if (!isRecord(value.capture) || !exactKeys(value.capture, ["capture_radius_m", "maximum_final_speed_m_s", "minimum_residence_time_s"])) return false;
  const fixed = spec.fixed_classification;
  return value.solver === fixed.solver
    && value.timestep_s === fixed.timestep_s
    && value.t_max_s === fixed.t_max_s
    && value.convergence_claim === fixed.convergence_claim
    && value.capture.capture_radius_m === fixed.capture.capture_radius_m
    && value.capture.maximum_final_speed_m_s === fixed.capture.maximum_final_speed_m_s
    && value.capture.minimum_residence_time_s === fixed.capture.minimum_residence_time_s
    && value.sampling_algorithm === spec.sampling.algorithm
    && value.sampling_version === spec.sampling.version
    && value.workers === spec.workers_by_execution_mode[mode];
}

function parsePreview(value: unknown): Mot3DPreview {
  if (!isRecord(value) || !exactKeys(value, ["preview_token", "expires_in_seconds", "plan"]) || !printable(value.preview_token) || !integer(value.expires_in_seconds) || Number(value.expires_in_seconds) <= 0 || !isRecord(value.plan)) invalid("review");
  const response = value as Record<string, unknown>, plan = response.plan as Record<string, unknown>;
  if (!exactKeys(plan, ["run_id", "family", "source", "selection", "geometry", "execution", "retention", "suitability", "output_disposition", "locked_settings", "lifecycle_state", "laboratory_specification", "numerical_policy", "plan_sha256", "execution_started", "submitted_to_zeus"]) || !privateRunId(plan.run_id) || plan.family !== "mot_3d" || !isRecord(plan.source) || !exactKeys(plan.source, ["id", "kind", "qualification", "fingerprint", "pooled_particle_count"]) || !isRecord(plan.selection) || !exactKeys(plan.selection, ["algorithm", "version", "seed", "selected_count", "selected_identities_sha256"]) || !isRecord(plan.geometry) || !exactKeys(plan.geometry, ["family", "parameters", "derived_parameters"]) || !isRecord(plan.execution) || !exactKeys(plan.execution, ["mode", "particle_count", "simulation_seed"]) || !isRecord(plan.retention) || !exactKeys(plan.retention, ["particle_states"]) || plan.suitability !== "individual_only" || !["retain_survivor_states", "discard_survivor_states_after_summary"].includes(String(plan.output_disposition)) || plan.lifecycle_state !== "configured" || !validSpecificationReference(plan.laboratory_specification, spec.authority_references.laboratory_specification) || !validSpecificationReference(plan.numerical_policy, spec.authority_references.numerical_policy) || !hex64(plan.plan_sha256) || plan.execution_started !== false || plan.submitted_to_zeus !== false) invalid("review");
  const source = plan.source as Record<string, unknown>, selection = plan.selection as Record<string, unknown>, geometry = plan.geometry as Record<string, unknown>, execution = plan.execution as Record<string, unknown>, retention = plan.retention as Record<string, unknown>;
  const family = geometry.family;
  const mode = execution.mode;
  const cap = mode === "local" ? spec.particle_count.maximum_by_execution_mode.local : mode === "zeus" ? spec.particle_count.maximum_by_execution_mode.zeus : 0;
  const sourcePair = (source.kind === "canonical_2d_campaign" && source.qualification === "canonical_campaign_source") || (source.kind === "retained_individual_mot_2d" && source.qualification === "verified_individual_result");
  if (!sourceId(source.id) || !sourcePair || !hex64(source.fingerprint) || !integer(source.pooled_particle_count) || Number(source.pooled_particle_count) < 1 || selection.algorithm !== spec.sampling.algorithm || selection.version !== spec.sampling.version || !integer(selection.seed) || Number(selection.seed) < spec.selection_seed.minimum || Number(selection.seed) > spec.selection_seed.maximum || !integer(selection.selected_count) || Number(selection.selected_count) < 1 || Number(selection.selected_count) > Number(source.pooled_particle_count) || !hex64(selection.selected_identities_sha256) || (family !== "angled_donut" && family !== "single_pass") || !validParameters(family, geometry.parameters) || !validDerivedParameters(family, geometry.derived_parameters) || cap === 0 || !validLockedSettings(plan.locked_settings, mode as Mot3DMode) || !integer(execution.particle_count) || Number(execution.particle_count) < spec.particle_count.minimum || Number(execution.particle_count) > cap || Number(execution.particle_count) > Number(source.pooled_particle_count) || selection.selected_count !== execution.particle_count || !integer(execution.simulation_seed) || Number(execution.simulation_seed) < spec.simulation_seed.minimum || Number(execution.simulation_seed) > spec.simulation_seed.maximum || typeof retention.particle_states !== "boolean" || retention.particle_states !== (plan.output_disposition === "retain_survivor_states")) invalid("review");
  return value as unknown as Mot3DPreview;
}

function parseCreated(value: unknown): CreatedMot3DRun {
  if (!isRecord(value) || !exactKeys(value, ["status", "run_id", "family", "path", "lifecycle_state", "execution_started", "submitted_to_zeus"]) || value.status !== "created" || !privateRunId(value.run_id) || value.family !== "mot_3d" || value.path !== `data/runs/mot_3d/${value.run_id}` || value.lifecycle_state !== "configured" || value.execution_started !== false || value.submitted_to_zeus !== false) invalid("creation");
  return value as unknown as CreatedMot3DRun;
}

function parseLocalStart(value: unknown): StartedLocalMot3DRun {
  if (!isRecord(value) || !exactKeys(value, ["status", "run_id", "execution_mode"]) || value.status !== "queued" || !privateRunId(value.run_id) || value.execution_mode !== "local") invalid("local start");
  return value as unknown as StartedLocalMot3DRun;
}

function parseZeusPreview(value: unknown) {
  if (!isRecord(value) || !exactKeys(value, ["preview_token", "expires_in_seconds", "run_id", "job", "package_sha256", "submission_key", "effects"]) || !printable(value.preview_token) || !integer(value.expires_in_seconds) || Number(value.expires_in_seconds) <= 0 || !privateRunId(value.run_id) || !hex64(value.package_sha256) || !hex64(value.submission_key) || !isRecord(value.job) || !exactKeys(value.job, ["kind", "array", "pbs_sha256"]) || value.job.kind !== "scalar" || value.job.array !== false || !hex64(value.job.pbs_sha256) || !isRecord(value.effects) || !exactKeys(value.effects, ["submit_one_job", "reconcile_existing_job", "cancel_job"]) || typeof value.effects.submit_one_job !== "boolean" || typeof value.effects.reconcile_existing_job !== "boolean" || value.effects.submit_one_job === value.effects.reconcile_existing_job || value.effects.cancel_job !== false) invalid("Zeus review");
  return value as unknown as { preview_token: string; run_id: string; submission_key: string; effects: { submit_one_job: boolean; reconcile_existing_job: boolean; cancel_job: false } };
}

function parseZeusResult(value: unknown) {
  if (!isRecord(value) || !exactKeys(value, ["status", "run_id", "job_id", "submission_key"]) || !["submitted", "reconciled"].includes(String(value.status)) || !privateRunId(value.run_id) || !jobId(value.job_id) || !hex64(value.submission_key)) invalid("Zeus submission");
  return value as unknown as { status: "submitted" | "reconciled"; run_id: string; job_id: string; submission_key: string };
}

function parseZeusRefresh(value: unknown) {
  if (!isRecord(value) || !exactKeys(value, ["state", "job_id"]) || !["queued", "running", "succeeded", "failed", "outcome_unknown", "cancelled"].includes(String(value.state)) || !jobId(value.job_id)) invalid("Zeus status");
  return value as { state: string; job_id: string };
}

const summaryKeys = ["id", "record_kind", "run_kind", "display_name", "stage_semantics", "source", "queried_at", "trust", "scientific_role", "record_state", "integrity", "lifecycle", "next_action", "created_at", "updated_at", "execution", "retention", "results", "warnings"];
function validMot3DResultProvenance(value: unknown): value is Mot3DResultProvenance {
  if (!isRecord(value) || !exactKeys(value, ["git_revision", "configuration_sha256", "inputs_sha256", "laboratory_spec_sha256", "numerical_policy_sha256", "admission_specification_sha256", "source_id", "source_fingerprint", "selection_algorithm", "selection_version", "selection_seed", "simulation_seed", "geometry_family", "solver", "timestep_s", "t_max_s", "convergence_claim"])) return false;
  return printable(value.git_revision)
    && [value.configuration_sha256, value.inputs_sha256, value.laboratory_spec_sha256, value.numerical_policy_sha256, value.admission_specification_sha256, value.source_fingerprint].every(hex64)
    && sourceId(value.source_id)
    && value.selection_algorithm === spec.sampling.algorithm
    && value.selection_version === spec.sampling.version
    && integer(value.selection_seed) && Number(value.selection_seed) >= spec.selection_seed.minimum && Number(value.selection_seed) <= spec.selection_seed.maximum
    && integer(value.simulation_seed) && Number(value.simulation_seed) >= spec.simulation_seed.minimum && Number(value.simulation_seed) <= spec.simulation_seed.maximum
    && (value.geometry_family === "angled_donut" || value.geometry_family === "single_pass")
    && value.solver === spec.fixed_classification.solver
    && value.timestep_s === spec.fixed_classification.timestep_s
    && value.t_max_s === spec.fixed_classification.t_max_s
    && value.convergence_claim === spec.fixed_classification.convergence_claim;
}

function validMot3DResultMetrics(value: unknown): value is Mot3DResultMetrics {
  if (!isRecord(value) || !exactKeys(value, ["n_input", "usable_at_end_count", "usable_at_end_fraction", "residence_qualified_captured_count", "residence_qualified_captured_fraction", "elapsed_s", "selection_sha256", "provenance"])) return false;
  const n = Number(value.n_input), usable = Number(value.usable_at_end_count), captured = Number(value.residence_qualified_captured_count);
  return integer(value.n_input) && n > 0
    && integer(value.usable_at_end_count) && integer(value.residence_qualified_captured_count)
    && 0 <= captured && captured <= usable && usable <= n
    && finite(value.usable_at_end_fraction) && value.usable_at_end_fraction === usable / n
    && finite(value.residence_qualified_captured_fraction) && value.residence_qualified_captured_fraction === captured / n
    && finite(value.elapsed_s) && value.elapsed_s >= 0
    && hex64(value.selection_sha256)
    && validMot3DResultProvenance(value.provenance);
}

function parseRun(value: unknown, detail = false): Mot3DRun {
  if (!isRecord(value) || !exactKeys(value, detail ? [...summaryKeys, "provenance", "configuration", "inputs", "artifacts", "metrics", "error"] : summaryKeys)) invalid("run");
  const row = value as Record<string, unknown>, execution = row.execution as Record<string, unknown>, retention = row.retention as Record<string, unknown>, results = row.results as Record<string, unknown>;
  if (!publicRunId(row.id) || row.record_kind !== "individual_simulation_run" || row.run_kind !== "mot_3d" || !privateRunId(row.display_name) || row.stage_semantics !== "single-run-lifecycle" || row.source !== "local" || !printable(row.queried_at) || row.trust !== "verified-package" || row.scientific_role !== "individual-only" || !printable(row.record_state) || !printable(row.integrity) || !printable(row.lifecycle) || !printable(row.next_action) || !printable(row.created_at) || !printable(row.updated_at) || !isRecord(execution) || !exactKeys(execution, ["mode", "zeus_job_id"]) || !["local", "zeus"].includes(String(execution.mode)) || (execution.zeus_job_id !== null && !jobId(execution.zeus_job_id)) || !isRecord(retention) || !exactKeys(retention, ["particle_states_requested", "status"]) || typeof retention.particle_states_requested !== "boolean" || !printable(retention.status) || !isRecord(results) || !exactKeys(results, ["availability", "completed_at"]) || !printable(results.availability) || (results.completed_at !== null && !printable(results.completed_at)) || !Array.isArray(row.warnings) || !row.warnings.every((item: unknown) => printable(item))) invalid("run");
  const state = String(row.record_state), lifecycle = String(row.lifecycle), integrity = String(row.integrity);
  const active = ["configured", "validated", "reviewed", "queued", "running"], terminal = ["failed", "outcome_unknown", "cancelled"];
  const expectedAction = ["queued", "running"].includes(state) ? "wait" : state === "outcome_unknown" ? "inspect_execution" : "none";
  if (lifecycle === "results_ready") {
    if (state !== "succeeded" || integrity !== "complete_verified" || row.next_action !== "view_results" || results.availability !== "verified" || !printable(results.completed_at) || !["retained", "not_retained"].includes(String(retention.status))) invalid("run lifecycle");
  } else if (lifecycle === "incomplete_publication") {
    if (state !== "running" || integrity !== "incomplete_publication" || row.next_action !== "wait" || results.availability !== "incomplete_publication" || retention.status !== "publication_pending") invalid("run lifecycle");
  } else if (lifecycle !== state || (!active.includes(state) && !terminal.includes(state)) || integrity !== (terminal.includes(state) ? "terminal_without_results" : "active") || row.next_action !== expectedAction || results.availability !== "not_ready" || retention.status !== "pending") invalid("run lifecycle");
  if ((execution.mode === "local" && execution.zeus_job_id !== null) || (execution.mode === "zeus" && ["queued", "running", "succeeded", "failed"].includes(state) && !jobId(execution.zeus_job_id))) invalid("run execution");
  if (detail) {
    const provenance = row.provenance, configuration = row.configuration, inputs = row.inputs;
    if (!isRecord(provenance) || !exactKeys(provenance, ["git_revision", "configuration_sha256", "inputs_sha256", "laboratory_spec", "numerical_policy"]) || !printable(provenance.git_revision) || !hex64(provenance.configuration_sha256) || !hex64(provenance.inputs_sha256) || !isRecord(provenance.laboratory_spec) || !isRecord(provenance.numerical_policy) || !isRecord(configuration) || !exactKeys(configuration, ["status", "resolved"]) || configuration.status !== "complete" || !isRecord(configuration.resolved) || !isRecord(inputs) || !exactKeys(inputs, ["status", "artifacts"]) || inputs.status !== "complete" || !Array.isArray(inputs.artifacts) || !Array.isArray(row.artifacts) || (lifecycle === "results_ready" ? !validMot3DResultMetrics(row.metrics) : row.metrics !== null) || (row.error !== null && (!isRecord(row.error) || !exactKeys(row.error, ["code", "message"]) || !printable(row.error.code) || !printable(row.error.message)))) invalid("run detail");
  }
  return value as unknown as Mot3DRun;
}

export function createIndividualMot3DApi(session: () => Promise<string>) {
  let generation = 0, previewSequence = 0, zeusSequence = 0, readSequence = 0;
  const reviews = new Map<string, CreationContext>();
  const confirmations = new Map<string, Promise<CreatedMot3DRun>>();
  const confirmed = new Map<string, CreatedMot3DRun>();
  const localStarts = new Map<string, Promise<StartedLocalMot3DRun>>();
  const zeusReviews = new Map<string, ZeusContext>();
  const zeusResults = new Map<string, ReturnType<typeof parseZeusResult>>();
  const zeusConfirmations = new Map<string, Promise<ReturnType<typeof parseZeusResult>>>();
  const jobs = new Map<string, { profile: Profile; jobId: string; submissionKey: string }>();
  const refreshes = new Map<string, number>();
  return {
    reset() { generation++; previewSequence++; zeusSequence++; readSequence++; reviews.clear(); confirmations.clear(); confirmed.clear(); localStarts.clear(); zeusReviews.clear(); zeusResults.clear(); zeusConfirmations.clear(); jobs.clear(); refreshes.clear(); },
    async sources() { return parseSources(await getData("/api/v1/individual-runs/mot-3d/sources")); },
    async preview(request: Mot3DRequest) {
      const currentGeneration = generation, sequence = ++previewSequence, csrf = await session();
      const row = parsePreview(await postData("/api/v1/individual-runs/mot-3d/preview", request, csrf));
      if (currentGeneration !== generation || sequence !== previewSequence) throw new Error("The 3D-MOT review is stale.");
      const plan = row.plan;
      if (plan.source.id !== request.source_id || plan.geometry.family !== request.geometry_family || plan.execution.mode !== request.execution_mode || plan.execution.particle_count !== request.particle_count || plan.execution.simulation_seed !== request.simulation_seed || plan.selection.seed !== request.selection_seed || !sameParameters(request.geometry_family, plan.geometry.parameters, request.parameters) || plan.retention.particle_states !== request.retain_particle_states) throw new Error("The review did not match the request.");
      reviews.set(row.preview_token, { runId: plan.run_id, request: structuredClone(request), csrf, generation: currentGeneration });
      return row;
    },
    async confirm(token: string) {
      const completed = confirmed.get(token); if (completed) return completed;
      const existing = confirmations.get(token); if (existing) return existing;
      const context = reviews.get(token); if (!context) throw new Error("The review is no longer active.");
      reviews.delete(token);
      const task = (async () => {
        const row = parseCreated(await postData("/api/v1/individual-runs/mot-3d/confirm", { preview_token: token }, context.csrf));
        if (context.generation !== generation || row.run_id !== context.runId) throw new Error("The creation response is stale or mismatched.");
        confirmed.set(token, row); return row;
      })();
      confirmations.set(token, task);
      try { return await task; } finally { confirmations.delete(token); }
    },
    async startLocal(id: string) {
      if (!privateRunId(id)) throw new Error("The run identifier is invalid.");
      const existing = localStarts.get(id); if (existing) return existing;
      const currentGeneration = generation;
      const task = (async () => {
        const row = parseLocalStart(await postData("/api/v1/individual-runs/mot-3d/local/start", { run_id: id }, await session()));
        if (currentGeneration !== generation || row.run_id !== id) throw new Error("The queued run is stale or mismatched.");
        return row;
      })();
      localStarts.set(id, task);
      try { return await task; } finally { localStarts.delete(id); }
    },
    async previewZeus(id: string, username: string) {
      if (!privateRunId(id)) throw new Error("The run identifier is invalid.");
      const currentGeneration = generation, sequence = ++zeusSequence, profile = makeProfile(username), csrf = await session();
      const row = parseZeusPreview(await postData("/api/v1/individual-runs/mot-3d/zeus/preview", { run_id: id, profile }, csrf));
      if (currentGeneration !== generation || sequence !== zeusSequence) throw new Error("The Zeus review is stale.");
      if (row.run_id !== id) throw new Error("The Zeus review did not match the selected run.");
      zeusReviews.set(row.preview_token, { runId: id, profile, submissionKey: row.submission_key, csrf, generation: currentGeneration });
      return row;
    },
    async confirmZeus(token: string) {
      const completed = zeusResults.get(token); if (completed) return completed;
      const pending = zeusConfirmations.get(token); if (pending) return pending;
      const context = zeusReviews.get(token); if (!context) throw new Error("The Zeus review is no longer active.");
      zeusReviews.delete(token);
      const task = (async () => {
        const row = parseZeusResult(await postData("/api/v1/individual-runs/mot-3d/zeus/confirm", { preview_token: token }, context.csrf));
        if (context.generation !== generation) throw new Error("The Zeus submission response is stale.");
        if (row.run_id !== context.runId || row.submission_key !== context.submissionKey) throw new Error("The Zeus submission did not match the reviewed job.");
        const existing = jobs.get(row.run_id);
        if (existing && (existing.jobId !== row.job_id || existing.submissionKey !== row.submission_key || !sameProfile(existing.profile, context.profile))) throw new Error("The Zeus job identity changed unexpectedly.");
        jobs.set(row.run_id, { profile: context.profile, jobId: row.job_id, submissionKey: row.submission_key });
        zeusResults.set(token, row); return row;
      })();
      zeusConfirmations.set(token, task);
      try { return await task; } finally { zeusConfirmations.delete(token); }
    },
    async refreshZeus(id: string, username: string) {
      const context = jobs.get(id);
      if (!context) throw new Error("The Zeus job identity is unavailable. Review the original submission before checking status.");
      const profile = makeProfile(username);
      if (!sameProfile(profile, context.profile)) throw new Error("The Zeus connection profile does not match the submitted job.");
      const currentGeneration = generation, sequence = (refreshes.get(id) ?? 0) + 1; refreshes.set(id, sequence);
      const row = parseZeusRefresh(await postData("/api/v1/individual-runs/mot-3d/zeus/refresh", { run_id: id, profile }, await session()));
      if (currentGeneration !== generation || refreshes.get(id) !== sequence) throw new Error("The Zeus status response is stale.");
      if (row.job_id !== context.jobId) throw new Error("The Zeus status did not match the submitted job.");
      return row;
    },
    async runs() {
      const currentGeneration = generation, sequence = ++readSequence;
      const value = await getData("/api/v1/individual-runs");
      if (currentGeneration !== generation || sequence !== readSequence) throw new Error("The run list is stale.");
      if (!isRecord(value) || !exactKeys(value, ["runs", "invalid_count", "total", "truncated"]) || !Array.isArray(value.runs) || !integer(value.invalid_count) || Number(value.invalid_count) < 0 || value.total !== value.runs.length || typeof value.truncated !== "boolean") invalid("run list");
      const catalog = value as Record<string, unknown>;
      return (catalog.runs as unknown[]).filter((row: unknown) => isRecord(row) && row.run_kind === "mot_3d").map((row: unknown) => parseRun(row));
    },
    async run(id: string) {
      if (!publicRunId(id)) throw new Error("The run identifier is invalid.");
      const currentGeneration = generation, sequence = ++readSequence;
      const row = parseRun(await getData(`/api/v1/individual-runs/${encodeURIComponent(id)}`), true);
      if (currentGeneration !== generation || sequence !== readSequence || row.id !== id) throw new Error("The run detail is stale or mismatched.");
      return row;
    },
  };
}

export type IndividualMot3DApi = ReturnType<typeof createIndividualMot3DApi>;
