import {
  isIndividualZeusResources,
  type IndividualZeusResources,
} from "./individualZeusResources";
import { zeusProjectDirectory } from "../zeusEnvironment";
import { exactKeys, getData, isRecord, postData } from "../http/envelope";
import { isRunProgress, type RunProgress } from "./individualZeeman";
import {
  individualZeusApiError,
  parseIndividualZeusRecovery,
} from "./individualZeusRecovery";

export type Mot2DMode = "local" | "zeus";
export type Mot2DSource = {
  id: string;
  source_kind: string;
  label: string;
  ensemble_count: number;
  available_particle_count: {
    pooled: number;
    minimum_per_ensemble: number;
    maximum_per_ensemble: number;
  };
  source_qualification: string;
  result_suitability: "individual_only";
  provenance: Record<string, unknown>;
};
export type Mot2DRequest = {
  source_id: string;
  particle_count: number;
  selection_seed: number;
  mot_seed: number;
  s0: number;
  detuning_gamma: number;
  magnet_radius_m: number;
  npools: number;
  retain_particle_states: boolean;
  execution_mode: Mot2DMode;
};
export type Mot2DPreview = {
  preview_token: string;
  expires_in_seconds: number;
  plan: {
    run_id: string;
    family: "mot_2d";
    source: {
      id: string;
      kind: string;
      qualification: string;
      fingerprint: string;
      pooled_particle_count: number;
    };
    selection: {
      algorithm: string;
      version: string;
      seed: number;
      selected_count: number;
      selected_identities_sha256: string;
    };
    controls: { s0: number; detuning_gamma: number; magnet_radius_m: number };
    execution: { mode: Mot2DMode; particle_count: number; mot_seed: number };
    retention: { particle_states: boolean };
    suitability: "individual_only";
    output_disposition: string;
    locked_settings: Record<string, unknown>;
    lifecycle_state: "configured";
    laboratory_specification: Record<string, unknown>;
    numerical_policy: Record<string, unknown>;
    plan_sha256: string;
    execution_started: false;
    submitted_to_zeus: false;
  };
};
export type Mot2DRun = {
  id: string;
  display_name: string;
  record_state: string;
  lifecycle: string;
  execution: {
    mode: Mot2DMode;
    zeus_job_id: string | null;
    progress?: RunProgress | null;
  };
  retention: { particle_states_requested: boolean; status: string };
  results: { availability: string; completed_at: string | null };
  metrics?: {
    n_input: number;
    n_survivors: number;
    conditional_efficiency: number;
    elapsed_s: number;
    selection_sha256: string;
    provenance: Record<string, unknown>;
  } | null;
  provenance?: Record<string, unknown>;
};
type Profile = { username: string; project_directory: string };
type CreationContext = {
  runId: string;
  request: Mot2DRequest;
  csrf: string;
  generation: number;
};
type ZeusContext = {
  runId: string;
  profile: Profile;
  submissionKey: string;
  csrf: string;
  generation: number;
};
// Control characters are rejected at the response trust boundary.
const printable = (v: unknown, n = 512): v is string =>
  typeof v === "string" &&
  v.length > 0 &&
  v.length <= n &&
  // eslint-disable-next-line no-control-regex
  !/[\u0000-\u001f\u007f]/.test(v);
const integer = (v: unknown): v is number => Number.isInteger(v);
const hex64 = (v: unknown): v is string =>
  typeof v === "string" && /^[0-9a-f]{64}$/.test(v);
const runId = (v: unknown): v is string =>
  typeof v === "string" && /^mot2d-[a-z0-9-]{1,120}$/.test(v);
const jobId = (v: unknown): v is string =>
  typeof v === "string" && /^\d+\.zeus-master$/.test(v);
const publicRunId = (v: unknown): v is string =>
  typeof v === "string" && /^individual-run-[0-9a-f]{24}$/.test(v);
const sameProfile = (a: Profile, b: Profile) =>
  a.username === b.username && a.project_directory === b.project_directory;
const invalid = (part: string): never => {
  throw new Error(`Invalid individual 2D-MOT ${part} response.`);
};
const makeProfile = (username: string): Profile => ({
  username,
  project_directory: zeusProjectDirectory(username),
});

function parseSources(v: unknown): Mot2DSource[] {
  if (!isRecord(v)) invalid("source catalog");
  const value = v as Record<string, unknown>;
  if (
    !exactKeys(value, [
      "contract_version",
      "sources",
      "invalid_count",
      "total",
      "truncated",
    ]) ||
    value.contract_version !== "mot-2d-individual-source-catalog-v1" ||
    !Array.isArray(value.sources) ||
    !integer(value.invalid_count) ||
    Number(value.invalid_count) < 0 ||
    typeof value.truncated !== "boolean" ||
    value.total !== value.sources.length
  )
    invalid("source catalog");
  const rows = value.sources as unknown[];
  return rows.map((candidate: unknown) => {
    if (!isRecord(candidate)) invalid("source catalog");
    const row = candidate as Record<string, unknown>;
    if (
      !exactKeys(row, [
        "id",
        "source_kind",
        "label",
        "ensemble_count",
        "available_particle_count",
        "source_qualification",
        "result_suitability",
        "provenance",
      ]) ||
      !/^mot2d-source-[0-9a-f]{32}$/.test(String(row.id)) ||
      !printable(row.label, 80) ||
      !integer(row.ensemble_count) ||
      Number(row.ensemble_count) < 1 ||
      row.result_suitability !== "individual_only" ||
      !isRecord(row.available_particle_count) ||
      !isRecord(row.provenance)
    )
      invalid("source catalog");
    const counts = row.available_particle_count as Record<string, unknown>,
      provenance = row.provenance as Record<string, unknown>;
    if (
      !exactKeys(counts, [
        "pooled",
        "minimum_per_ensemble",
        "maximum_per_ensemble",
      ]) ||
      ![
        counts.pooled,
        counts.minimum_per_ensemble,
        counts.maximum_per_ensemble,
      ].every(integer) ||
      Number(counts.minimum_per_ensemble) < 1 ||
      Number(counts.minimum_per_ensemble) >
        Number(counts.maximum_per_ensemble) ||
      Number(counts.pooled) < Number(counts.maximum_per_ensemble)
    )
      invalid("source catalog");
    if (row.source_kind === "canonical_folder") {
      if (
        !["canonical_campaign_source", "verified_individual_folder"].includes(
          String(row.source_qualification),
        ) ||
        !exactKeys(provenance, ["validation", "profile", "fingerprint"]) ||
        ![
          "canonical_zeeman_folder",
          "verified_individual_zeeman_folder",
        ].includes(String(provenance.validation)) ||
        !printable(provenance.profile) ||
        !hex64(provenance.fingerprint)
      )
        invalid("source catalog");
    } else if (row.source_kind === "retained_individual_zeeman") {
      if (
        row.source_qualification !== "verified_individual_result" ||
        !exactKeys(provenance, [
          "validation",
          "completed_at",
          "public_run_id",
          "scientific_summary",
          "fingerprint",
        ]) ||
        provenance.validation !== "verified_retained_individual_result" ||
        !printable(provenance.completed_at) ||
        !publicRunId(provenance.public_run_id) ||
        !isRecord(provenance.scientific_summary) ||
        !hex64(provenance.fingerprint)
      )
        invalid("source catalog");
    } else invalid("source catalog");
    return row as unknown as Mot2DSource;
  });
}
function parsePreview(v: unknown): Mot2DPreview {
  if (!isRecord(v)) invalid("review");
  const value = v as Record<string, unknown>;
  if (
    !exactKeys(value, ["preview_token", "expires_in_seconds", "plan"]) ||
    !printable(value.preview_token) ||
    !integer(value.expires_in_seconds) ||
    Number(value.expires_in_seconds) <= 0 ||
    !isRecord(value.plan)
  )
    invalid("review");
  const p = value.plan as Record<string, unknown>;
  if (
    !exactKeys(p, [
      "run_id",
      "family",
      "source",
      "selection",
      "controls",
      "execution",
      "retention",
      "suitability",
      "output_disposition",
      "locked_settings",
      "lifecycle_state",
      "laboratory_specification",
      "numerical_policy",
      "plan_sha256",
      "execution_started",
      "submitted_to_zeus",
    ]) ||
    !runId(p.run_id) ||
    p.family !== "mot_2d" ||
    !isRecord(p.source) ||
    !exactKeys(p.source, [
      "id",
      "kind",
      "qualification",
      "fingerprint",
      "pooled_particle_count",
    ]) ||
    !isRecord(p.selection) ||
    !exactKeys(p.selection, [
      "algorithm",
      "version",
      "seed",
      "selected_count",
      "selected_identities_sha256",
    ]) ||
    !isRecord(p.controls) ||
    !exactKeys(p.controls, ["s0", "detuning_gamma", "magnet_radius_m"]) ||
    !isRecord(p.execution) ||
    !exactKeys(p.execution, ["mode", "particle_count", "mot_seed"]) ||
    !isRecord(p.retention) ||
    !exactKeys(p.retention, ["particle_states"]) ||
    p.suitability !== "individual_only" ||
    ![
      "retain_survivor_states",
      "discard_survivor_states_after_summary",
    ].includes(String(p.output_disposition)) ||
    !isRecord(p.locked_settings) ||
    !isRecord(p.laboratory_specification) ||
    !isRecord(p.numerical_policy) ||
    p.lifecycle_state !== "configured" ||
    !hex64(p.plan_sha256) ||
    p.execution_started !== false ||
    p.submitted_to_zeus !== false
  )
    invalid("review");
  const source = p.source as Record<string, unknown>,
    selection = p.selection as Record<string, unknown>,
    controls = p.controls as Record<string, unknown>,
    execution = p.execution as Record<string, unknown>,
    retention = p.retention as Record<string, unknown>;
  const sourcePair =
    (source.kind === "canonical_folder" &&
      ["canonical_campaign_source", "verified_individual_folder"].includes(
        String(source.qualification),
      )) ||
    (source.kind === "retained_individual_zeeman" &&
      source.qualification === "verified_individual_result");
  const mode = String(execution.mode);
  const modeCap = mode === "local" ? 1000 : mode === "zeus" ? 50000 : 0;
  if (
    !/^mot2d-source-[0-9a-f]{32}$/.test(String(source.id)) ||
    !sourcePair ||
    !hex64(source.fingerprint) ||
    !integer(source.pooled_particle_count) ||
    Number(source.pooled_particle_count) < 1 ||
    !printable(selection.algorithm) ||
    !printable(selection.version) ||
    !integer(selection.seed) ||
    Number(selection.seed) < 0 ||
    Number(selection.seed) > 4294967295 ||
    !integer(selection.selected_count) ||
    Number(selection.selected_count) < 1 ||
    Number(selection.selected_count) > Number(source.pooled_particle_count) ||
    !hex64(selection.selected_identities_sha256) ||
    ![controls.s0, controls.detuning_gamma, controls.magnet_radius_m].every(
      (v) => typeof v === "number" && Number.isFinite(v),
    ) ||
    modeCap === 0 ||
    !integer(execution.particle_count) ||
    Number(execution.particle_count) < 1 ||
    Number(execution.particle_count) > modeCap ||
    Number(execution.particle_count) > Number(source.pooled_particle_count) ||
    selection.selected_count !== execution.particle_count ||
    !integer(execution.mot_seed) ||
    Number(execution.mot_seed) < 0 ||
    Number(execution.mot_seed) > 4294967295 ||
    typeof retention.particle_states !== "boolean" ||
    retention.particle_states !==
      (p.output_disposition === "retain_survivor_states")
  )
    invalid("review");
  return value as unknown as Mot2DPreview;
}
function parseCreated(v: unknown) {
  if (
    !isRecord(v) ||
    !exactKeys(v, [
      "status",
      "run_id",
      "family",
      "path",
      "lifecycle_state",
      "execution_started",
      "submitted_to_zeus",
    ]) ||
    v.status !== "created" ||
    !runId(v.run_id) ||
    v.family !== "mot_2d" ||
    v.path !== `data/runs/mot_2d/${v.run_id}` ||
    v.lifecycle_state !== "configured" ||
    v.execution_started !== false ||
    v.submitted_to_zeus !== false
  )
    invalid("creation");
  return v as { status: "created"; run_id: string };
}
function parseLocal(v: unknown) {
  if (
    !isRecord(v) ||
    !exactKeys(v, ["status", "run_id", "execution_mode"]) ||
    v.status !== "queued" ||
    !runId(v.run_id) ||
    v.execution_mode !== "local"
  )
    invalid("local start");
  return v as { status: "queued"; run_id: string };
}
function parseZeusPreview(v: unknown) {
  if (
    !isRecord(v) ||
    !exactKeys(v, [
      "preview_token",
      "expires_in_seconds",
      "run_id",
      "job",
      "package_sha256",
      "submission_key",
      "effects",
    ]) ||
    !printable(v.preview_token) ||
    !integer(v.expires_in_seconds) ||
    Number(v.expires_in_seconds) <= 0 ||
    !runId(v.run_id) ||
    !hex64(v.package_sha256) ||
    !hex64(v.submission_key) ||
    !isRecord(v.job) ||
    !exactKeys(v.job, ["kind", "array", "pbs_sha256", "resources"]) ||
    v.job.kind !== "scalar" ||
    v.job.array !== false ||
    !hex64(v.job.pbs_sha256) ||
    !isIndividualZeusResources(v.job.resources) ||
    !isRecord(v.effects) ||
    !exactKeys(v.effects, [
      "submit_one_job",
      "reconcile_existing_job",
      "cancel_job",
    ]) ||
    typeof v.effects.submit_one_job !== "boolean" ||
    typeof v.effects.reconcile_existing_job !== "boolean" ||
    v.effects.submit_one_job === v.effects.reconcile_existing_job ||
    v.effects.cancel_job !== false
  )
    invalid("Zeus review");
  return v as {
    preview_token: string;
    run_id: string;
    submission_key: string;
    job: { resources: IndividualZeusResources };
    effects: {
      submit_one_job: boolean;
      reconcile_existing_job: boolean;
      cancel_job: false;
    };
  };
}
function parseZeusResult(v: unknown) {
  if (
    !isRecord(v) ||
    !exactKeys(v, ["status", "run_id", "job_id", "submission_key"]) ||
    v.status !== "submitted" ||
    !runId(v.run_id) ||
    !jobId(v.job_id) ||
    !hex64(v.submission_key)
  )
    invalid("Zeus submission");
  return v as {
    status: "submitted";
    run_id: string;
    job_id: string;
    submission_key: string;
  };
}
function parseZeusRefresh(v: unknown) {
  if (
    !isRecord(v) ||
    !exactKeys(v, ["state", "job_id"]) ||
    ![
      "queued",
      "held",
      "running",
      "succeeded",
      "failed",
      "outcome_unknown",
      "cancelled",
    ].includes(String(v.state)) ||
    !jobId(v.job_id)
  )
    invalid("Zeus status");
  return v as { state: string; job_id: string };
}
const summaryKeys = [
  "id",
  "record_kind",
  "run_kind",
  "display_name",
  "stage_semantics",
  "source",
  "queried_at",
  "trust",
  "scientific_role",
  "record_state",
  "integrity",
  "lifecycle",
  "next_action",
  "created_at",
  "updated_at",
  "execution",
  "retention",
  "results",
  "warnings",
];
function validMetrics(value: unknown): boolean {
  if (
    !isRecord(value) ||
    !exactKeys(value, [
      "n_input",
      "n_survivors",
      "conditional_efficiency",
      "elapsed_s",
      "selection_sha256",
      "provenance",
    ]) ||
    !integer(value.n_input) ||
    !integer(value.n_survivors) ||
    Number(value.n_input) < 1 ||
    Number(value.n_survivors) < 0 ||
    Number(value.n_survivors) > Number(value.n_input) ||
    typeof value.conditional_efficiency !== "number" ||
    value.conditional_efficiency !==
      Number(value.n_survivors) / Number(value.n_input) ||
    typeof value.elapsed_s !== "number" ||
    !Number.isFinite(value.elapsed_s) ||
    value.elapsed_s < 0 ||
    !hex64(value.selection_sha256) ||
    !isRecord(value.provenance)
  )
    return false;
  return true;
}
function parseRun(raw: unknown, detail = false): Mot2DRun {
  if (!isRecord(raw)) invalid("run");
  const v = raw as Record<string, unknown>;
  if (
    !exactKeys(
      v,
      detail
        ? [
            ...summaryKeys,
            "provenance",
            "configuration",
            "inputs",
            "artifacts",
            "metrics",
            "error",
          ]
        : summaryKeys,
    )
  )
    invalid("run");
  const execution = v.execution,
    retention = v.retention,
    results = v.results;
  if (isRecord(execution) && execution.progress === undefined)
    execution.progress = null;
  if (
    !publicRunId(v.id) ||
    v.record_kind !== "individual_simulation_run" ||
    v.run_kind !== "mot_2d" ||
    !runId(v.display_name) ||
    v.stage_semantics !== "single-run-lifecycle" ||
    v.source !== "local" ||
    !printable(v.queried_at) ||
    v.trust !== "verified-package" ||
    v.scientific_role !== "individual-only" ||
    !printable(v.record_state) ||
    !printable(v.integrity) ||
    !printable(v.lifecycle) ||
    !printable(v.next_action) ||
    !printable(v.created_at) ||
    !printable(v.updated_at) ||
    !isRecord(execution) ||
    !exactKeys(execution, ["mode", "zeus_job_id", "progress"]) ||
    (execution.progress !== null && !isRunProgress(execution.progress)) ||
    !["local", "zeus"].includes(String(execution.mode)) ||
    (execution.zeus_job_id !== null && !jobId(execution.zeus_job_id)) ||
    !isRecord(retention) ||
    !exactKeys(retention, ["particle_states_requested", "status"]) ||
    typeof retention.particle_states_requested !== "boolean" ||
    !printable(retention.status) ||
    !isRecord(results) ||
    !exactKeys(results, ["availability", "completed_at"]) ||
    !printable(results.availability) ||
    (results.completed_at !== null && !printable(results.completed_at)) ||
    !Array.isArray(v.warnings) ||
    !v.warnings.every((x) => printable(x))
  )
    invalid("run");
  const checkedExecution = execution as Record<string, unknown>;
  const checkedRetention = retention as Record<string, unknown>;
  const checkedResults = results as Record<string, unknown>;
  const state = String(v.record_state),
    lifecycle = String(v.lifecycle),
    integrity = String(v.integrity),
    terminal = ["failed", "outcome_unknown", "cancelled"],
    active = ["configured", "validated", "reviewed", "queued", "running"];
  const expected = ["queued", "running"].includes(state)
    ? "wait"
    : state === "outcome_unknown"
      ? "inspect_execution"
      : "none";
  if (lifecycle === "results_ready") {
    if (
      state !== "succeeded" ||
      integrity !== "complete_verified" ||
      v.next_action !== "view_results" ||
      checkedResults.availability !== "verified" ||
      !printable(checkedResults.completed_at) ||
      !["retained", "not_retained"].includes(String(checkedRetention.status))
    )
      invalid("run lifecycle");
  } else if (lifecycle === "incomplete_publication") {
    if (
      state !== "running" ||
      integrity !== "incomplete_publication" ||
      v.next_action !== "wait" ||
      checkedResults.availability !== "incomplete_publication" ||
      checkedRetention.status !== "publication_pending"
    )
      invalid("run lifecycle");
  } else if (
    lifecycle !== state ||
    (!active.includes(state) && !terminal.includes(state)) ||
    integrity !==
      (terminal.includes(state) ? "terminal_without_results" : "active") ||
    v.next_action !== expected ||
    checkedResults.availability !== "not_ready" ||
    checkedRetention.status !== "pending"
  )
    invalid("run lifecycle");
  if (
    (checkedExecution.mode === "local" &&
      checkedExecution.zeus_job_id !== null) ||
    (checkedExecution.mode === "zeus" &&
      ["queued", "running", "succeeded", "failed"].includes(state) &&
      !jobId(checkedExecution.zeus_job_id))
  )
    invalid("run execution");
  if (detail) {
    if (
      !isRecord(v.provenance) ||
      !exactKeys(v.provenance, [
        "git_revision",
        "configuration_sha256",
        "inputs_sha256",
        "laboratory_spec",
        "numerical_policy",
      ]) ||
      !printable(v.provenance.git_revision) ||
      !hex64(v.provenance.configuration_sha256) ||
      !hex64(v.provenance.inputs_sha256) ||
      !isRecord(v.provenance.laboratory_spec) ||
      !isRecord(v.provenance.numerical_policy) ||
      !isRecord(v.configuration) ||
      !exactKeys(v.configuration, ["status", "resolved"]) ||
      v.configuration.status !== "complete" ||
      !isRecord(v.configuration.resolved) ||
      !isRecord(v.inputs) ||
      !exactKeys(v.inputs, ["status", "artifacts"]) ||
      v.inputs.status !== "complete" ||
      !Array.isArray(v.inputs.artifacts) ||
      !Array.isArray(v.artifacts) ||
      (v.metrics !== null && !validMetrics(v.metrics)) ||
      (v.error !== null &&
        (!isRecord(v.error) ||
          !exactKeys(v.error, ["code", "message"]) ||
          !printable(v.error.code) ||
          !printable(v.error.message)))
    )
      invalid("run detail");
  }
  return v as unknown as Mot2DRun;
}

export function createIndividualMot2DApi(session: () => Promise<string>) {
  let generation = 0,
    sequence = 0,
    zsequence = 0,
    readSequence = 0;
  const reviews = new Map<string, CreationContext>(),
    confirmationResults = new Map<string, ReturnType<typeof parseCreated>>(),
    confirmations = new Map<string, Promise<ReturnType<typeof parseCreated>>>(),
    localStarts = new Map<string, Promise<ReturnType<typeof parseLocal>>>(),
    localStartResults = new Map<string, ReturnType<typeof parseLocal>>(),
    zreviews = new Map<string, ZeusContext>(),
    zresults = new Map<string, ReturnType<typeof parseZeusResult>>(),
    zconfirms = new Map<string, Promise<ReturnType<typeof parseZeusResult>>>(),
    jobs = new Map<
      string,
      { profile: Profile; jobId: string; submissionKey?: string }
    >(),
    refreshes = new Map<string, number>();
  return {
    reset() {
      generation++;
      sequence++;
      zsequence++;
      readSequence++;
      reviews.clear();
      confirmationResults.clear();
      confirmations.clear();
      localStarts.clear();
      localStartResults.clear();
      zreviews.clear();
      zresults.clear();
      zconfirms.clear();
      jobs.clear();
      refreshes.clear();
    },
    async sources() {
      return parseSources(
        await getData("/api/v1/individual-runs/mot-2d/sources"),
      );
    },
    async preview(request: Mot2DRequest) {
      const g = generation,
        s = ++sequence,
        csrf = await session(),
        row = parsePreview(
          await postData(
            "/api/v1/individual-runs/mot-2d/preview",
            request,
            csrf,
          ),
        );
      if (g !== generation || s !== sequence)
        throw new Error("The 2D-MOT review is stale.");
      if (
        row.plan.source.id !== request.source_id ||
        row.plan.execution.mode !== request.execution_mode ||
        row.plan.execution.particle_count !== request.particle_count ||
        row.plan.execution.mot_seed !== request.mot_seed ||
        row.plan.selection.seed !== request.selection_seed ||
        row.plan.controls.s0 !== request.s0 ||
        row.plan.controls.detuning_gamma !== request.detuning_gamma ||
        row.plan.controls.magnet_radius_m !== request.magnet_radius_m ||
        row.plan.locked_settings.workers !== request.npools ||
        row.plan.retention.particle_states !== request.retain_particle_states
      )
        throw new Error("The review did not match the request.");
      reviews.set(row.preview_token, {
        runId: row.plan.run_id,
        request: { ...request },
        csrf,
        generation: g,
      });
      return row;
    },
    async confirm(token: string) {
      const result = confirmationResults.get(token);
      if (result) return result;
      const old = confirmations.get(token);
      if (old) return old;
      const c = reviews.get(token);
      if (!c) throw new Error("The review is no longer active.");
      reviews.delete(token);
      const task = (async () => {
        const row = parseCreated(
          await postData(
            "/api/v1/individual-runs/mot-2d/confirm",
            { preview_token: token },
            c.csrf,
          ),
        );
        if (c.generation !== generation || row.run_id !== c.runId)
          throw new Error("The creation response is stale or mismatched.");
        confirmationResults.set(token, row);
        return row;
      })();
      confirmations.set(token, task);
      try {
        return await task;
      } finally {
        confirmations.delete(token);
      }
    },
    async startLocal(id: string) {
      const completed = localStartResults.get(id);
      if (completed) return completed;
      const old = localStarts.get(id);
      if (old) return old;
      const g = generation,
        task = (async () => {
          const row = parseLocal(
            await postData(
              "/api/v1/individual-runs/mot-2d/local/start",
              { run_id: id },
              await session(),
            ),
          );
          if (g !== generation || row.run_id !== id)
            throw new Error("The queued run is stale or mismatched.");
          localStartResults.set(id, row);
          return row;
        })();
      localStarts.set(id, task);
      try {
        return await task;
      } finally {
        if (localStarts.get(id) === task) localStarts.delete(id);
      }
    },
    async previewZeus(id: string, username: string) {
      const g = generation,
        s = ++zsequence,
        requested = makeProfile(username),
        csrf = await session(),
        row = parseZeusPreview(
          await postData(
            "/api/v1/individual-runs/mot-2d/zeus/preview",
            { run_id: id, profile: requested },
            csrf,
          ),
        );
      if (g !== generation || s !== zsequence)
        throw new Error("The Zeus review is stale.");
      if (row.run_id !== id) throw new Error("The Zeus review did not match.");
      zreviews.set(row.preview_token, {
        runId: id,
        profile: requested,
        submissionKey: row.submission_key,
        csrf,
        generation: g,
      });
      return row;
    },
    async confirmZeus(token: string) {
      const result = zresults.get(token);
      if (result) return result;
      const old = zconfirms.get(token);
      if (old) return old;
      const c = zreviews.get(token);
      if (!c) throw new Error("The Zeus review is no longer active.");
      zreviews.delete(token);
      const task = (async () => {
        const row = parseZeusResult(
          await postData(
            "/api/v1/individual-runs/mot-2d/zeus/confirm",
            { preview_token: token },
            c.csrf,
            individualZeusApiError,
          ),
        );
        if (
          c.generation !== generation ||
          row.run_id !== c.runId ||
          row.submission_key !== c.submissionKey
        )
          throw new Error("The Zeus result is stale or mismatched.");
        const prior = jobs.get(row.run_id);
        if (
          prior &&
          (prior.jobId !== row.job_id ||
            prior.submissionKey !== row.submission_key ||
            !sameProfile(prior.profile, c.profile))
        )
          throw new Error("The Zeus job identity changed unexpectedly.");
        jobs.set(row.run_id, {
          profile: c.profile,
          jobId: row.job_id,
          submissionKey: row.submission_key,
        });
        zresults.set(token, row);
        return row;
      })();
      zconfirms.set(token, task);
      try {
        return await task;
      } finally {
        zconfirms.delete(token);
      }
    },
    async refreshZeus(id: string, username: string) {
      const binding = jobs.get(id),
        requested = makeProfile(username);
      if (!binding || !sameProfile(binding.profile, requested))
        throw new Error("The Zeus profile does not match.");
      const g = generation,
        s = (refreshes.get(id) ?? 0) + 1;
      refreshes.set(id, s);
      const row = parseZeusRefresh(
        await postData(
          "/api/v1/individual-runs/mot-2d/zeus/refresh",
          { run_id: id, profile: requested },
          await session(),
        ),
      );
      if (
        g !== generation ||
        s !== refreshes.get(id) ||
        row.job_id !== binding.jobId
      )
        throw new Error("The Zeus status is stale or mismatched.");
      return row;
    },
    async recoverZeus(id: string, username: string) {
      const profile = makeProfile(username),
        activeGeneration = generation;
      const row = parseIndividualZeusRecovery(
        await postData(
          "/api/v1/individual-runs/mot-2d/zeus/recover",
          { run_id: id, profile },
          await session(),
        ),
        "mot_2d",
        id,
      );
      if (activeGeneration !== generation)
        throw new Error("The Zeus recovery response is stale.");
      jobs.set(id, { profile, jobId: row.job_id });
      return row;
    },
    async runs() {
      const activeGeneration = generation,
        current = ++readSequence;
      const raw = await getData("/api/v1/individual-runs");
      if (activeGeneration !== generation || current !== readSequence)
        throw new Error("The run list response is stale.");
      if (!isRecord(raw)) invalid("run list");
      const value = raw as Record<string, unknown>;
      if (
        !exactKeys(value, ["runs", "invalid_count", "total", "truncated"]) ||
        !Array.isArray(value.runs) ||
        !integer(value.invalid_count) ||
        Number(value.invalid_count) < 0 ||
        value.total !== value.runs.length ||
        typeof value.truncated !== "boolean"
      )
        invalid("run list");
      const rows = value.runs as unknown[];
      return rows
        .filter((row) => isRecord(row) && row.run_kind === "mot_2d")
        .map((row) => parseRun(row));
    },
    async catalog() {
      const raw = await getData("/api/v1/individual-runs");
      if (
        !isRecord(raw) ||
        !exactKeys(raw, ["runs", "invalid_count", "total", "truncated"]) ||
        !Array.isArray(raw.runs) ||
        !integer(raw.invalid_count) ||
        Number(raw.invalid_count) < 0 ||
        raw.total !== raw.runs.length ||
        typeof raw.truncated !== "boolean"
      )
        invalid("run list");
      const value = raw as Record<string, unknown>;
      return {
        runs: (value.runs as unknown[])
          .filter((row) => isRecord(row) && row.run_kind === "mot_2d")
          .map((row) => parseRun(row)),
        invalid_count: Number(value.invalid_count),
        total: Number(value.total),
        truncated: value.truncated as boolean,
      };
    },
    async run(publicId: string) {
      const activeGeneration = generation,
        current = ++readSequence;
      const row = parseRun(
        await getData(
          `/api/v1/individual-runs/${encodeURIComponent(publicId)}`,
        ),
        true,
      );
      if (activeGeneration !== generation || current !== readSequence)
        throw new Error("The run detail response is stale.");
      if (row.id !== publicId) throw new Error("The run detail did not match.");
      return row;
    },
  };
}
type IndividualMot2DImplementation = ReturnType<
  typeof createIndividualMot2DApi
>;
export type IndividualMot2DApi = Omit<
  IndividualMot2DImplementation,
  "catalog" | "recoverZeus"
> & {
  catalog?: IndividualMot2DImplementation["catalog"];
  recoverZeus?: IndividualMot2DImplementation["recoverZeus"];
};
