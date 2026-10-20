import {
  isIndividualZeusResources,
  type IndividualZeusResources,
} from "./individualZeusResources";
import { zeusProjectDirectory } from "../zeusEnvironment";
import { exactKeys, getData, isRecord, postData } from "../http/envelope";
import { ZEEMAN_INDIVIDUAL_SPECIFICATION_V1 as spec } from "../../generated/zeemanIndividualSpec.v1";
import {
  individualZeusApiError,
  parseIndividualZeusRecovery,
} from "./individualZeusRecovery";

export type ZeemanMode = "local" | "zeus";
export type ZeemanRequest = {
  zeeman_s0?: number;
  zeeman_detuning_gamma?: number;
  particle_count: number;
  seed: number;
  mot_2d_s0: number;
  mot_2d_detuning_gamma: number;
  mot_2d_magnet_radius_m: number;
  npools: number;
  retain_particle_states: boolean;
  execution_mode: ZeemanMode;
};
type Plan = {
  zeeman_s0: number;
  zeeman_detuning_gamma: number;
  run_id: string;
  family: "zeeman";
  execution_mode: ZeemanMode;
  particle_count: number;
  seed: number;
  mot_2d_s0: number;
  mot_2d_detuning_gamma: number;
  mot_2d_magnet_radius_m: number;
  npools: number;
  retain_particle_states: boolean;
  suitability: "individual_only";
  output_disposition:
    "retain_survivor_states" | "discard_survivor_states_after_summary";
  locked_settings: Record<string, unknown>;
  resolved_configuration: Record<string, unknown>;
  lifecycle_state: "configured";
  laboratory_specification: Record<string, unknown>;
  numerical_policy: Record<string, unknown>;
  plan_sha256: string;
  execution_started: false;
  submitted_to_zeus: false;
};
export type ZeemanPreview = {
  preview_token: string;
  expires_in_seconds: number;
  plan: Plan;
};
export type CreatedZeemanRun = {
  status: "created";
  run_id: string;
  family: "zeeman";
  path: string;
  lifecycle_state: "configured";
  execution_started: false;
  submitted_to_zeus: false;
};
export type RunProgress = {
  completed_particles: number;
  total_particles: number;
  fraction: number;
  runtime_s: number;
};
export function isRunProgress(value: unknown): value is RunProgress {
  return (
    isRecord(value) &&
    exactKeys(value, [
      "completed_particles",
      "total_particles",
      "fraction",
      "runtime_s",
    ]) &&
    integer(value.completed_particles) &&
    integer(value.total_particles) &&
    Number(value.total_particles) > 0 &&
    Number(value.completed_particles) >= 0 &&
    Number(value.completed_particles) <= Number(value.total_particles) &&
    typeof value.fraction === "number" &&
    Number.isFinite(value.fraction) &&
    value.fraction >= 0 &&
    value.fraction <= 1 &&
    typeof value.runtime_s === "number" &&
    Number.isFinite(value.runtime_s) &&
    value.runtime_s >= 0
  );
}
export type IndividualRun = {
  id: string;
  display_name: string;
  record_state: string;
  lifecycle: string;
  next_action: string;
  execution: {
    mode: ZeemanMode;
    zeus_job_id: string | null;
    progress?: RunProgress | null;
  };
  retention: { particle_states_requested: boolean; status: string };
  results: { availability: string; completed_at: string | null };
  metrics?: Record<string, number> | null;
  error?: { code: string; message: string } | null;
};
type Profile = { username: string; project_directory: string };
type CreationContext = {
  runId: string;
  mode: ZeemanMode;
  request: ZeemanRequest;
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

// Control characters are never accepted at this API trust boundary.
// eslint-disable-next-line no-control-regex
const printable = (value: unknown, maximum = 512): value is string =>
  typeof value === "string" &&
  value.length > 0 &&
  value.length <= maximum &&
  !/[\u0000-\u001f\u007f]/.test(value);
const integer = (value: unknown): value is number => Number.isInteger(value);
const hex64 = (value: unknown): value is string =>
  typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
const canonicalJob = (value: unknown): value is string =>
  typeof value === "string" && /^\d+\.zeus-master$/.test(value);
const runId = (value: unknown): value is string =>
  typeof value === "string" && /^zeeman-[a-z0-9-]{1,120}$/.test(value);
const publicRunId = (value: unknown): value is string =>
  typeof value === "string" && /^individual-run-[0-9a-f]{24}$/.test(value);
const sameProfile = (left: Profile, right: Profile) =>
  left.username === right.username &&
  left.project_directory === right.project_directory;
const makeProfile = (username: string): Profile => ({
  username,
  project_directory: zeusProjectDirectory(username),
});
function invalid(label: string): never {
  throw new Error(`Invalid individual Zeeman ${label} response.`);
}

function parsePreview(value: Record<string, unknown>): ZeemanPreview {
  if (
    !exactKeys(value, ["preview_token", "expires_in_seconds", "plan"]) ||
    !printable(value.preview_token) ||
    !integer(value.expires_in_seconds) ||
    Number(value.expires_in_seconds) <= 0 ||
    !isRecord(value.plan)
  )
    invalid("review");
  const plan = value.plan;
  const keys = [
    "zeeman_s0",
    "zeeman_detuning_gamma",
    "run_id",
    "family",
    "execution_mode",
    "particle_count",
    "seed",
    "mot_2d_s0",
    "mot_2d_detuning_gamma",
    "mot_2d_magnet_radius_m",
    "npools",
    "retain_particle_states",
    "suitability",
    "output_disposition",
    "locked_settings",
    "resolved_configuration",
    "lifecycle_state",
    "laboratory_specification",
    "numerical_policy",
    "plan_sha256",
    "execution_started",
    "submitted_to_zeus",
  ];
  const mode = plan.execution_mode;
  const workersValid =
    integer(plan.npools) &&
    (mode === "local"
      ? Number(plan.npools) >= spec.worker_policy.local.minimum &&
        Number(plan.npools) <= spec.worker_policy.local.maximum
      : plan.npools === spec.worker_policy.zeus.fixed);
  const controlsValid =
    typeof plan.mot_2d_s0 === "number" &&
    plan.mot_2d_s0 >= spec.mot_2d_controls.s0.minimum &&
    plan.mot_2d_s0 <= spec.mot_2d_controls.s0.maximum &&
    typeof plan.mot_2d_detuning_gamma === "number" &&
    plan.mot_2d_detuning_gamma >= spec.mot_2d_controls.detuning_gamma.minimum &&
    plan.mot_2d_detuning_gamma <= spec.mot_2d_controls.detuning_gamma.maximum &&
    typeof plan.mot_2d_magnet_radius_m === "number" &&
    plan.mot_2d_magnet_radius_m >=
      spec.mot_2d_controls.magnet_radius_m.minimum &&
    plan.mot_2d_magnet_radius_m <= spec.mot_2d_controls.magnet_radius_m.maximum;
  if (
    !exactKeys(plan, keys) ||
    !runId(plan.run_id) ||
    plan.family !== "zeeman" ||
    (mode !== "local" && mode !== "zeus") ||
    !integer(plan.particle_count) ||
    Number(plan.particle_count) < spec.particle_count.minimum ||
    Number(plan.particle_count) >
      (mode === "local"
        ? spec.particle_count.maximum_by_execution_mode.local
        : spec.particle_count.maximum_by_execution_mode.zeus) ||
    !integer(plan.seed) ||
    Number(plan.seed) < spec.seed.minimum ||
    Number(plan.seed) > spec.seed.maximum ||
    !workersValid ||
    !controlsValid ||
    typeof plan.zeeman_s0 !== "number" ||
    !Number.isFinite(plan.zeeman_s0) ||
    plan.zeeman_s0 < 0 ||
    typeof plan.zeeman_detuning_gamma !== "number" ||
    !Number.isFinite(plan.zeeman_detuning_gamma) ||
    typeof plan.retain_particle_states !== "boolean" ||
    plan.suitability !== "individual_only" ||
    ![
      "retain_survivor_states",
      "discard_survivor_states_after_summary",
    ].includes(String(plan.output_disposition)) ||
    !isRecord(plan.locked_settings) ||
    !isRecord(plan.resolved_configuration) ||
    !isRecord(plan.laboratory_specification) ||
    !isRecord(plan.numerical_policy) ||
    plan.lifecycle_state !== "configured" ||
    !hex64(plan.plan_sha256) ||
    plan.execution_started !== false ||
    plan.submitted_to_zeus !== false
  )
    invalid("review");
  if (
    (plan.retain_particle_states === true) !==
    (plan.output_disposition === "retain_survivor_states")
  )
    invalid("review");
  return value as unknown as ZeemanPreview;
}

function parseCreated(value: Record<string, unknown>): CreatedZeemanRun {
  if (
    !exactKeys(value, [
      "status",
      "run_id",
      "family",
      "path",
      "lifecycle_state",
      "execution_started",
      "submitted_to_zeus",
    ]) ||
    value.status !== "created" ||
    !runId(value.run_id) ||
    value.family !== "zeeman" ||
    value.path !== `data/runs/zeeman/${value.run_id}` ||
    value.lifecycle_state !== "configured" ||
    value.execution_started !== false ||
    value.submitted_to_zeus !== false
  )
    invalid("creation");
  return value as unknown as CreatedZeemanRun;
}

function parseLocalStart(value: Record<string, unknown>) {
  if (
    !exactKeys(value, ["status", "run_id", "execution_mode"]) ||
    value.status !== "queued" ||
    !runId(value.run_id) ||
    value.execution_mode !== "local"
  )
    invalid("local start");
  return value as unknown as {
    status: "queued";
    run_id: string;
    execution_mode: "local";
  };
}

function parseZeusPreview(value: Record<string, unknown>) {
  const job = value.job;
  const effects = value.effects;
  if (
    !exactKeys(value, [
      "preview_token",
      "expires_in_seconds",
      "run_id",
      "job",
      "package_sha256",
      "submission_key",
      "effects",
    ]) ||
    !printable(value.preview_token) ||
    !integer(value.expires_in_seconds) ||
    Number(value.expires_in_seconds) <= 0 ||
    !runId(value.run_id) ||
    !isRecord(job) ||
    !exactKeys(job, ["kind", "array", "pbs_sha256", "resources"]) ||
    job.kind !== "scalar" ||
    job.array !== false ||
    !hex64(job.pbs_sha256) ||
    !isIndividualZeusResources(job.resources) ||
    !hex64(value.package_sha256) ||
    !hex64(value.submission_key) ||
    !isRecord(effects) ||
    !exactKeys(effects, [
      "submit_one_job",
      "reconcile_existing_job",
      "cancel_job",
    ]) ||
    typeof effects.submit_one_job !== "boolean" ||
    typeof effects.reconcile_existing_job !== "boolean" ||
    effects.submit_one_job === effects.reconcile_existing_job ||
    effects.cancel_job !== false
  )
    invalid("Zeus review");
  return value as unknown as {
    preview_token: string;
    expires_in_seconds: number;
    run_id: string;
    job: {
      kind: "scalar";
      array: false;
      pbs_sha256: string;
      resources: IndividualZeusResources;
    };
    package_sha256: string;
    submission_key: string;
    effects: {
      submit_one_job: boolean;
      reconcile_existing_job: boolean;
      cancel_job: false;
    };
  };
}

function parseZeusResult(value: Record<string, unknown>) {
  if (
    !exactKeys(value, ["status", "run_id", "job_id", "submission_key"]) ||
    value.status !== "submitted" ||
    !runId(value.run_id) ||
    !canonicalJob(value.job_id) ||
    !hex64(value.submission_key)
  )
    invalid("Zeus submission");
  return value as unknown as {
    status: "submitted";
    run_id: string;
    job_id: string;
    submission_key: string;
  };
}

function parseZeusRefresh(value: Record<string, unknown>) {
  const states = [
    "queued",
    "held",
    "running",
    "succeeded",
    "failed",
    "outcome_unknown",
    "cancelled",
  ];
  if (
    !exactKeys(value, ["state", "job_id"]) ||
    !states.includes(String(value.state)) ||
    !canonicalJob(value.job_id)
  )
    invalid("Zeus status");
  return value as unknown as { state: string; job_id: string };
}

const runKeys = [
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
function parseRun(value: unknown, detail = false): IndividualRun {
  if (
    !isRecord(value) ||
    !exactKeys(
      value,
      detail
        ? [
            ...runKeys,
            "provenance",
            "configuration",
            "inputs",
            "artifacts",
            "metrics",
            "error",
          ]
        : runKeys,
    )
  )
    invalid("run");
  const execution = value.execution;
  const retention = value.retention;
  const results = value.results;
  if (isRecord(execution) && execution.progress === undefined)
    execution.progress = null;
  const progress = isRecord(execution) ? execution.progress : null;
  if (progress !== null && !isRunProgress(progress)) invalid("run progress");
  if (
    !publicRunId(value.id) ||
    value.record_kind !== "individual_simulation_run" ||
    value.run_kind !== "zeeman" ||
    !runId(value.display_name) ||
    value.stage_semantics !== "single-run-lifecycle" ||
    value.source !== "local" ||
    !printable(value.queried_at) ||
    value.trust !== "verified-package" ||
    value.scientific_role !== "individual-only" ||
    !printable(value.record_state) ||
    !printable(value.integrity) ||
    !printable(value.lifecycle) ||
    !printable(value.next_action) ||
    !printable(value.created_at) ||
    !printable(value.updated_at) ||
    !isRecord(execution) ||
    !exactKeys(execution, ["mode", "zeus_job_id", "progress"]) ||
    !["local", "zeus"].includes(String(execution.mode)) ||
    (execution.zeus_job_id !== null && !canonicalJob(execution.zeus_job_id)) ||
    !isRecord(retention) ||
    !exactKeys(retention, ["particle_states_requested", "status"]) ||
    typeof retention.particle_states_requested !== "boolean" ||
    !printable(retention.status) ||
    !isRecord(results) ||
    !exactKeys(results, ["availability", "completed_at"]) ||
    !printable(results.availability) ||
    (results.completed_at !== null && !printable(results.completed_at)) ||
    !Array.isArray(value.warnings) ||
    !value.warnings.every((item) => printable(item))
  )
    invalid("run");
  const state = String(value.record_state);
  const lifecycle = String(value.lifecycle);
  const integrity = String(value.integrity);
  const active = ["configured", "validated", "reviewed", "queued", "running"];
  const terminal = ["failed", "outcome_unknown", "cancelled"];
  const expectedAction = ["queued", "running"].includes(state)
    ? "wait"
    : state === "outcome_unknown"
      ? "inspect_execution"
      : "none";
  if (lifecycle === "results_ready") {
    if (
      state !== "succeeded" ||
      integrity !== "complete_verified" ||
      value.next_action !== "view_results" ||
      results.availability !== "verified" ||
      !printable(results.completed_at) ||
      !["retained", "not_retained"].includes(String(retention.status))
    )
      invalid("run lifecycle");
  } else if (lifecycle === "incomplete_publication") {
    if (
      state !== "running" ||
      integrity !== "incomplete_publication" ||
      value.next_action !== "wait" ||
      results.availability !== "incomplete_publication" ||
      retention.status !== "publication_pending"
    )
      invalid("run lifecycle");
  } else if (
    lifecycle !== state ||
    (!active.includes(state) && !terminal.includes(state)) ||
    integrity !==
      (terminal.includes(state) ? "terminal_without_results" : "active") ||
    value.next_action !== expectedAction ||
    results.availability !== "not_ready" ||
    retention.status !== "pending"
  )
    invalid("run lifecycle");
  if (
    (execution.mode === "local" && execution.zeus_job_id !== null) ||
    (execution.mode === "zeus" &&
      ["queued", "running", "succeeded", "failed"].includes(state) &&
      !canonicalJob(execution.zeus_job_id))
  )
    invalid("run execution");
  if (detail) {
    const provenance = value.provenance;
    const configuration = value.configuration;
    const inputs = value.inputs;
    if (
      !isRecord(provenance) ||
      !exactKeys(provenance, [
        "git_revision",
        "configuration_sha256",
        "inputs_sha256",
        "laboratory_spec",
        "numerical_policy",
      ]) ||
      !printable(provenance.git_revision) ||
      !hex64(provenance.configuration_sha256) ||
      !hex64(provenance.inputs_sha256) ||
      !isRecord(provenance.laboratory_spec) ||
      !isRecord(provenance.numerical_policy) ||
      !isRecord(configuration) ||
      !exactKeys(configuration, ["status", "resolved"]) ||
      configuration.status !== "complete" ||
      !isRecord(configuration.resolved) ||
      !isRecord(inputs) ||
      !exactKeys(inputs, ["status", "artifacts"]) ||
      inputs.status !== "complete" ||
      !Array.isArray(inputs.artifacts) ||
      !Array.isArray(value.artifacts) ||
      (value.metrics !== null &&
        (!isRecord(value.metrics) ||
          !Object.values(value.metrics).every(
            (item) => typeof item === "number" && Number.isFinite(item),
          ))) ||
      (value.error !== null &&
        (!isRecord(value.error) ||
          !exactKeys(value.error, ["code", "message"]) ||
          !printable(value.error.code) ||
          !printable(value.error.message)))
    )
      invalid("run detail");
  }
  return value as unknown as IndividualRun;
}

export function createIndividualZeemanApi(session: () => Promise<string>) {
  let generation = 0;
  let creationReviewSequence = 0;
  let zeusReviewSequence = 0;
  const creation = new Map<string, CreationContext>();
  const creationResults = new Map<string, CreatedZeemanRun>();
  const creationPending = new Map<string, Promise<CreatedZeemanRun>>();
  const zeus = new Map<string, ZeusContext>();
  const zeusResults = new Map<string, ReturnType<typeof parseZeusResult>>();
  const zeusPending = new Map<
    string,
    Promise<ReturnType<typeof parseZeusResult>>
  >();
  const jobs = new Map<
    string,
    { profile: Profile; submissionKey?: string; jobId: string }
  >();
  const localStarts = new Map<
    string,
    Promise<ReturnType<typeof parseLocalStart>>
  >();
  const localStartResults = new Map<
    string,
    ReturnType<typeof parseLocalStart>
  >();
  const refreshSequence = new Map<string, number>();
  return {
    reset() {
      generation += 1;
      creationReviewSequence += 1;
      zeusReviewSequence += 1;
      creation.clear();
      creationResults.clear();
      creationPending.clear();
      zeus.clear();
      zeusResults.clear();
      zeusPending.clear();
      jobs.clear();
      localStarts.clear();
      localStartResults.clear();
      refreshSequence.clear();
    },
    async preview(request: ZeemanRequest) {
      const current = generation;
      const review = ++creationReviewSequence;
      const csrf = await session();
      const result = parsePreview(
        await postData("/api/v1/individual-runs/zeeman/preview", request, csrf),
      );
      if (current !== generation || review !== creationReviewSequence)
        throw new Error("The individual Zeeman review is stale.");
      if (
        result.plan.zeeman_s0 !==
          (request.zeeman_s0 ?? spec.laser_controls.s0.default) ||
        result.plan.zeeman_detuning_gamma !==
          (request.zeeman_detuning_gamma ??
            spec.laser_controls.detuning_gamma.default) ||
        result.plan.execution_mode !== request.execution_mode ||
        result.plan.particle_count !== request.particle_count ||
        result.plan.seed !== request.seed ||
        result.plan.mot_2d_s0 !== request.mot_2d_s0 ||
        result.plan.mot_2d_detuning_gamma !== request.mot_2d_detuning_gamma ||
        result.plan.mot_2d_magnet_radius_m !== request.mot_2d_magnet_radius_m ||
        result.plan.npools !== request.npools ||
        result.plan.retain_particle_states !== request.retain_particle_states
      )
        throw new Error(
          "The individual Zeeman review did not match the requested run.",
        );
      creation.set(result.preview_token, {
        runId: result.plan.run_id,
        mode: request.execution_mode,
        request: { ...request },
        csrf,
        generation: current,
      });
      return result;
    },
    async confirm(previewToken: string) {
      const prior = creationResults.get(previewToken);
      if (prior) return prior;
      const pending = creationPending.get(previewToken);
      if (pending) return pending;
      const context = creation.get(previewToken);
      if (!context)
        throw new Error("The individual Zeeman review is no longer active.");
      creation.delete(previewToken);
      const task = (async () => {
        const row = parseCreated(
          await postData(
            "/api/v1/individual-runs/zeeman/confirm",
            { preview_token: previewToken },
            context.csrf,
          ),
        );
        if (context.generation !== generation)
          throw new Error("The individual Zeeman creation response is stale.");
        if (row.run_id !== context.runId)
          throw new Error("The created run did not match the reviewed run.");
        creationResults.set(previewToken, row);
        return row;
      })();
      creationPending.set(previewToken, task);
      try {
        return await task;
      } finally {
        creationPending.delete(previewToken);
      }
    },
    async startLocal(runId: string) {
      const completed = localStartResults.get(runId);
      if (completed) return completed;
      const existing = localStarts.get(runId);
      if (existing) return existing;
      const current = generation;
      const task = (async () => {
        const row = parseLocalStart(
          await postData(
            "/api/v1/individual-runs/zeeman/local/start",
            { run_id: runId },
            await session(),
          ),
        );
        if (current !== generation)
          throw new Error("The local start response is stale.");
        if (row.run_id !== runId)
          throw new Error("The queued run did not match the selected run.");
        localStartResults.set(runId, row);
        return row;
      })();
      localStarts.set(runId, task);
      try {
        return await task;
      } finally {
        if (localStarts.get(runId) === task) localStarts.delete(runId);
      }
    },
    async previewZeus(runId: string, username: string) {
      const current = generation;
      const review = ++zeusReviewSequence;
      const requested = makeProfile(username);
      const csrf = await session();
      const row = parseZeusPreview(
        await postData(
          "/api/v1/individual-runs/zeeman/zeus/preview",
          { run_id: runId, profile: requested },
          csrf,
        ),
      );
      if (current !== generation || review !== zeusReviewSequence)
        throw new Error("The Zeus review is stale.");
      if (row.run_id !== runId)
        throw new Error("The Zeus review did not match the selected run.");
      zeus.set(row.preview_token, {
        runId,
        profile: requested,
        submissionKey: row.submission_key,
        csrf,
        generation: current,
      });
      return row;
    },
    async confirmZeus(previewToken: string) {
      const prior = zeusResults.get(previewToken);
      if (prior) return prior;
      const pending = zeusPending.get(previewToken);
      if (pending) return pending;
      const context = zeus.get(previewToken);
      if (!context) throw new Error("The Zeus review is no longer active.");
      zeus.delete(previewToken);
      const task = (async () => {
        const row = parseZeusResult(
          await postData(
            "/api/v1/individual-runs/zeeman/zeus/confirm",
            { preview_token: previewToken },
            context.csrf,
            individualZeusApiError,
          ),
        );
        if (context.generation !== generation)
          throw new Error("The Zeus submission response is stale.");
        if (
          row.run_id !== context.runId ||
          row.submission_key !== context.submissionKey
        )
          throw new Error(
            "The Zeus submission did not match the reviewed job.",
          );
        const existing = jobs.get(row.run_id);
        if (
          existing &&
          (existing.jobId !== row.job_id ||
            existing.submissionKey !== row.submission_key ||
            !sameProfile(existing.profile, context.profile))
        )
          throw new Error("The Zeus job identity changed unexpectedly.");
        jobs.set(row.run_id, {
          profile: context.profile,
          submissionKey: row.submission_key,
          jobId: row.job_id,
        });
        zeusResults.set(previewToken, row);
        return row;
      })();
      zeusPending.set(previewToken, task);
      try {
        return await task;
      } finally {
        zeusPending.delete(previewToken);
      }
    },
    async recoverZeus(runId: string, username: string) {
      const profile = makeProfile(username);
      const activeGeneration = generation;
      const row = parseIndividualZeusRecovery(
        await postData(
          "/api/v1/individual-runs/zeeman/zeus/recover",
          { run_id: runId, profile },
          await session(),
        ),
        "zeeman",
        runId,
      );
      if (activeGeneration !== generation)
        throw new Error("The Zeus recovery response is stale.");
      jobs.set(runId, { profile, jobId: row.job_id });
      return row;
    },
    async refreshZeus(runId: string, username: string) {
      const requested = makeProfile(username);
      const binding = jobs.get(runId);
      if (!binding || !sameProfile(binding.profile, requested))
        throw new Error("The Zeus profile does not match the submitted run.");
      const activeGeneration = generation;
      const current = (refreshSequence.get(runId) ?? 0) + 1;
      refreshSequence.set(runId, current);
      const row = parseZeusRefresh(
        await postData(
          "/api/v1/individual-runs/zeeman/zeus/refresh",
          { run_id: runId, profile: requested },
          await session(),
        ),
      );
      if (
        activeGeneration !== generation ||
        current !== refreshSequence.get(runId)
      )
        throw new Error("The Zeus status response is stale.");
      if (row.job_id !== binding.jobId)
        throw new Error("The Zeus status did not match the submitted job.");
      return row;
    },
    async catalog() {
      const value = await getData("/api/v1/individual-runs");
      if (
        !isRecord(value) ||
        !exactKeys(value, ["runs", "invalid_count", "total", "truncated"]) ||
        !Array.isArray(value.runs) ||
        !integer(value.invalid_count) ||
        Number(value.invalid_count) < 0 ||
        value.total !== value.runs.length ||
        typeof value.truncated !== "boolean"
      )
        invalid("run list");
      return {
        runs: value.runs
          .filter((row) => isRecord(row) && row.run_kind === "zeeman")
          .map((row) => parseRun(row)),
        invalid_count: Number(value.invalid_count),
        total: Number(value.total),
        truncated: value.truncated as boolean,
      };
    },
    async runs(): Promise<IndividualRun[]> {
      const value = await getData("/api/v1/individual-runs");
      if (
        !isRecord(value) ||
        !exactKeys(value, ["runs", "invalid_count", "total", "truncated"]) ||
        !Array.isArray(value.runs) ||
        !integer(value.invalid_count) ||
        Number(value.invalid_count) < 0 ||
        value.total !== value.runs.length ||
        typeof value.truncated !== "boolean"
      )
        invalid("run list");
      return value.runs
        .filter((row) => isRecord(row) && row.run_kind === "zeeman")
        .map((row) => parseRun(row));
    },
    async run(publicId: string): Promise<IndividualRun> {
      const row = parseRun(
        await getData(
          `/api/v1/individual-runs/${encodeURIComponent(publicId)}`,
        ),
        true,
      );
      if (row.id !== publicId)
        throw new Error("The run detail did not match the selected run.");
      return row;
    },
  };
}
type IndividualZeemanImplementation = ReturnType<
  typeof createIndividualZeemanApi
>;
export type IndividualZeemanApi = Omit<
  IndividualZeemanImplementation,
  "catalog" | "recoverZeus"
> & {
  catalog?: IndividualZeemanImplementation["catalog"];
  recoverZeus?: IndividualZeemanImplementation["recoverZeus"];
};
