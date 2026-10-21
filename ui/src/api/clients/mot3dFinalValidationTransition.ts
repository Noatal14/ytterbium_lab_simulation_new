import { adaptConfirmationError, isKnownServerError,
  confirmationRequiresManualVerification, } from "../errorSemantics";
import { postData } from "../http/envelope";
import { exactKeys } from "../schema/common";
import type { ZeusSnapshot } from "../schema/domain";
import { creationApi } from "./campaign";
type Profile = ZeusSnapshot["profile"];
const domain = "mot_3d_final_validation_transition" as const,
  hex64 = /^[0-9a-f]{64}$/,
  id = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/,
  token = /^[A-Za-z0-9_-]{1,256}$/,
  array = /^\d+\[\]\.zeus-master$/,
  scalar = /^\d+\.zeus-master$/;
const invalidReasons = [
  "artifact_registry_mismatch",
  "artifact_too_large",
  "malformed_json",
  "manifest_mismatch",
  "submission_mismatch",
  "input_metadata_mismatch",
  "input_array_invalid",
  "input_manifest_mismatch",
];
const object = (v: unknown, keys: string[], message: string) => {
  if (
    !v ||
    typeof v !== "object" ||
    Array.isArray(v) ||
    !exactKeys(v as Record<string, unknown>, keys)
  )
    throw new Error(message);
  return v as Record<string, unknown>;
};
const chain = (value: unknown) => {
  const c = object(
      value,
      ["dependency", "jobs"],
      "Invalid final-validation transition chain.",
    ),
    ids = ["zeeman", "mot_2d", "freeze"];
  if (
    c.dependency !== "afterok linear chain" ||
    !Array.isArray(c.jobs) ||
    c.jobs.length !== 3
  )
    throw new Error("Invalid final-validation transition chain.");
  const jobs = c.jobs.map((v, i) => {
    const row = object(
      v,
      ["id", "job_id"],
      "Invalid final-validation transition chain.",
    );
    if (
      row.id !== ids[i] ||
      typeof row.job_id !== "string" ||
      !(i < 2 ? array : scalar).test(row.job_id)
    )
      throw new Error("Invalid final-validation transition chain.");
    return row as { id: "zeeman" | "mot_2d" | "freeze"; job_id: string };
  });
  const numeric = jobs.map((x) => x.job_id.split(/[.[\]]/, 1)[0]);
  if (new Set(numeric).size !== 3)
    throw new Error("Invalid final-validation transition chain.");
  return { dependency: "afterok linear chain" as const, jobs };
};
export class Mot3DFinalValidationTransitionApiError extends Error {
  constructor(
    public code: string,
    message: string,
  ) {
    super(message);
  }
}
const adapt = (e: { code: string; message: string }) =>
  new Mot3DFinalValidationTransitionApiError(
    isKnownServerError(domain, e.code)
      ? e.code
      : "mot_3d_final_validation_transition_failed",
    isKnownServerError(domain, e.code)
      ? e.message
      : "Final-validation preparation could not be verified.",
  );
export const finalValidationTransitionIsUncertain = (e: unknown) =>
  e instanceof Mot3DFinalValidationTransitionApiError &&
  (confirmationRequiresManualVerification(domain, e.code) ||
    e.code.includes("outcome_unknown"));
export function parseMot3DFinalValidationTransitionStatus(value: unknown) {
  const r = object(
      value,
      [
        "source",
        "queried_at",
        "campaign",
        "final_validation_input_generation",
        "scheduler",
        "validation",
        "transition",
        "next_action",
        "local_sync",
      ],
      "Invalid final-validation transition status.",
    ),
    campaign = object(
      r.campaign,
      ["id", "name", "stage"],
      "Invalid final-validation transition status.",
    ),
    stage = object(
      r.final_validation_input_generation,
      ["status", "chain"],
      "Invalid final-validation transition status.",
    ),
    scheduler = object(
      r.scheduler,
      [
        "completed_array_tasks",
        "expected_array_tasks",
        "completed_scalar_jobs",
        "expected_scalar_jobs",
      ],
      "Invalid final-validation transition status.",
    ),
    validation = object(
      r.validation,
      [
        "status",
        "result_artifacts",
        "expected_result_artifacts",
        "reason_code",
      ],
      "Invalid final-validation transition status.",
    ),
    transition = object(
      r.transition,
      ["status"],
      "Invalid final-validation transition status.",
    ),
    sync = object(
      r.local_sync,
      ["status", "receipt_sha256"],
      "Invalid final-validation transition status.",
    );
  const lifecycle = stage.status,
    prepared = lifecycle === "final_validation_prepared",
    valid = validation.status === "valid",
    invalid = validation.status === "scientifically_invalid",
    terminal = [
      "completed_success_unvalidated",
      "ready_to_advance",
      "outcome_unknown",
      "final_validation_prepared",
    ].includes(String(lifecycle));
  if (
    r.source !== "zeus" ||
    typeof r.queried_at !== "string" ||
    !Number.isFinite(Date.parse(r.queried_at)) ||
    typeof campaign.id !== "string" ||
    !id.test(campaign.id) ||
    typeof campaign.name !== "string" ||
    !campaign.name ||
    campaign.name.length > 160 ||
    typeof campaign.stage !== "string" ||
    !["final_validation_input_generation", "final_validation"].includes(
      campaign.stage,
    ) ||
    typeof lifecycle !== "string" ||
    ![
      "queued",
      "running",
      "held",
      "completed_failed",
      "status_unknown",
      "completed_success_unvalidated",
      "ready_to_advance",
      "outcome_unknown",
      "final_validation_prepared",
    ].includes(lifecycle) ||
    typeof validation.status !== "string" ||
    !["not_started", "valid", "scientifically_invalid"].includes(
      validation.status,
    ) ||
    !Number.isInteger(scheduler.completed_array_tasks) ||
    !Number.isInteger(scheduler.completed_scalar_jobs) ||
    scheduler.expected_array_tasks !== 40 ||
    scheduler.expected_scalar_jobs !== 1 ||
    Number(scheduler.completed_array_tasks) < 0 ||
    Number(scheduler.completed_array_tasks) > 40 ||
    Number(scheduler.completed_scalar_jobs) < 0 ||
    Number(scheduler.completed_scalar_jobs) > 1 ||
    (terminal &&
      (scheduler.completed_array_tasks !== 40 ||
        scheduler.completed_scalar_jobs !== 1)) ||
    validation.expected_result_artifacts !== 101 ||
    validation.result_artifacts !== (valid ? 101 : 0) ||
    valid !==
      [
        "ready_to_advance",
        "outcome_unknown",
        "final_validation_prepared",
      ].includes(lifecycle) ||
    (invalid &&
      (lifecycle !== "completed_success_unvalidated" ||
        typeof validation.reason_code !== "string" ||
        !invalidReasons.includes(validation.reason_code))) ||
    (!invalid && validation.reason_code !== null) ||
    (!valid && !invalid && validation.status !== "not_started") ||
    transition.status !==
      (prepared ? "final_validation_prepared" : "not_prepared") ||
    sync.status !==
      (campaign.stage === "final_validation"
        ? "synchronized"
        : "not_synchronized") ||
    (campaign.stage === "final_validation" && !prepared) ||
    sync.receipt_sha256 !==
      (sync.status === "synchronized" ? sync.receipt_sha256 : null) ||
    (sync.status === "synchronized" &&
      (typeof sync.receipt_sha256 !== "string" ||
        !hex64.test(sync.receipt_sha256)))
  )
    throw new Error("Invalid final-validation transition status.");
  chain(stage.chain);
  const expectedAction = prepared
    ? sync.status === "synchronized"
      ? "open_final_validation"
      : "synchronize_results"
    : invalid ||
        [
          "held",
          "completed_failed",
          "status_unknown",
          "outcome_unknown",
        ].includes(lifecycle)
      ? "inspect_zeus"
      : ["ready_to_advance", "completed_success_unvalidated"].includes(
            lifecycle,
          )
        ? "review_transition"
        : "wait";
  if (r.next_action !== expectedAction)
    throw new Error("Invalid final-validation transition status.");
  return r as {
    source: "zeus";
    queried_at: string;
    campaign: {
      id: string;
      name: string;
      stage: "final_validation_input_generation" | "final_validation";
    };
    final_validation_input_generation: {
      status: string;
      chain: ReturnType<typeof chain>;
    };
    scheduler: {
      completed_array_tasks: number;
      expected_array_tasks: 40;
      completed_scalar_jobs: number;
      expected_scalar_jobs: 1;
    };
    validation: {
      status: "not_started" | "valid" | "scientifically_invalid";
      result_artifacts: number;
      expected_result_artifacts: 101;
      reason_code: string | null;
    };
    transition: { status: "not_prepared" | "final_validation_prepared" };
    next_action:
      | "wait"
      | "review_transition"
      | "synchronize_results"
      | "open_final_validation"
      | "inspect_zeus";
    local_sync: {
      status: "not_synchronized" | "synchronized";
      receipt_sha256: string | null;
    };
  };
}
export function parseMot3DFinalValidationTransitionPreview(
  value: unknown,
  expected: { campaignId: string; commit: string },
) {
  const r = object(
      value,
      [
        "preview_token",
        "expires_in_seconds",
        "campaign",
        "from_stage",
        "to_stage",
        "final_validation_input_generation",
        "artifacts",
        "effects",
      ],
      "Invalid final-validation transition review.",
    ),
    campaign = object(
      r.campaign,
      ["id", "name", "git_commit"],
      "Invalid final-validation transition review.",
    ),
    stage = object(
      r.final_validation_input_generation,
      [
        "result_artifacts",
        "expected_result_artifacts",
        "families",
        "evidence_sha256",
      ],
      "Invalid final-validation transition review.",
    ),
    art = object(
      r.artifacts,
      ["synchronize", "create", "update", "transfer_files"],
      "Invalid final-validation transition review.",
    ),
    sync = object(
      art.synchronize,
      ["result_files", "submission_receipts"],
      "Invalid final-validation transition review.",
    ),
    create = object(
      art.create,
      ["selection_files", "job_files"],
      "Invalid final-validation transition review.",
    ),
    effects = object(
      r.effects,
      [
        "synchronize_final_validation_inputs",
        "prepare_final_validation",
        "submit_final_validation",
        "start_simulation",
        "overwrite_existing",
      ],
      "Invalid final-validation transition review.",
    );
  if (
    typeof r.preview_token !== "string" ||
    !token.test(r.preview_token) ||
    r.expires_in_seconds !== 300 ||
    campaign.id !== expected.campaignId ||
    typeof campaign.name !== "string" ||
    !campaign.name ||
    typeof campaign.git_commit !== "string" ||
    !/^[0-9a-f]{40}$/.test(campaign.git_commit) ||
    campaign.git_commit !== expected.commit ||
    r.from_stage !== "final_validation_input_generation" ||
    r.to_stage !== "final_validation" ||
    stage.result_artifacts !== 101 ||
    stage.expected_result_artifacts !== 101 ||
    JSON.stringify(stage.families) !==
      JSON.stringify(["angled_donut", "single_pass"]) ||
    typeof stage.evidence_sha256 !== "string" ||
    !hex64.test(stage.evidence_sha256) ||
    sync.result_files !== 101 ||
    sync.submission_receipts !== 1 ||
    create.selection_files !== 0 ||
    create.job_files !== 4 ||
    JSON.stringify(art.update) !== JSON.stringify(["campaign.json"]) ||
    art.transfer_files !== 107 ||
    effects.synchronize_final_validation_inputs !== true ||
    effects.prepare_final_validation !== true ||
    effects.submit_final_validation !== false ||
    effects.start_simulation !== false ||
    effects.overwrite_existing !== false
  )
    throw new Error("Invalid final-validation transition review.");
  return r as {
    preview_token: string;
    expires_in_seconds: 300;
    campaign: { id: string; name: string; git_commit: string };
    from_stage: "final_validation_input_generation";
    to_stage: "final_validation";
    final_validation_input_generation: {
      result_artifacts: 101;
      expected_result_artifacts: 101;
      families: ["angled_donut", "single_pass"];
      evidence_sha256: string;
    };
    artifacts: {
      synchronize: { result_files: 101; submission_receipts: 1 };
      create: { selection_files: 0; job_files: 4 };
      update: ["campaign.json"];
      transfer_files: 107;
    };
    effects: {
      synchronize_final_validation_inputs: true;
      prepare_final_validation: true;
      submit_final_validation: false;
      start_simulation: false;
      overwrite_existing: false;
    };
  };
}
export function parseMot3DFinalValidationTransitionResult(
  value: unknown,
  campaignId: string,
) {
  const r = object(
      value,
      [
        "status",
        "campaign_id",
        "stage",
        "artifacts",
        "submitted_to_zeus",
        "simulation_started",
        "local_sync",
      ],
      "Invalid final-validation transition result.",
    ),
    art = object(
      r.artifacts,
      ["synchronized", "created", "updated", "bundle_sha256"],
      "Invalid final-validation transition result.",
    ),
    sync = object(
      r.local_sync,
      ["status", "receipt_sha256"],
      "Invalid final-validation transition result.",
    );
  if (
    r.status !== "final_validation_prepared" ||
    r.campaign_id !== campaignId ||
    r.stage !== "final_validation" ||
    art.synchronized !== 102 ||
    art.created !== 4 ||
    art.updated !== 1 ||
    typeof art.bundle_sha256 !== "string" ||
    !hex64.test(art.bundle_sha256) ||
    r.submitted_to_zeus !== false ||
    r.simulation_started !== false ||
    sync.status !== "synchronized" ||
    typeof sync.receipt_sha256 !== "string" ||
    !hex64.test(sync.receipt_sha256)
  )
    throw new Error("Invalid final-validation transition result.");
  return r as {
    status: "final_validation_prepared";
    campaign_id: string;
    stage: "final_validation";
    artifacts: {
      synchronized: 102;
      created: 4;
      updated: 1;
      bundle_sha256: string;
    };
    submitted_to_zeus: false;
    simulation_started: false;
    local_sync: { status: "synchronized"; receipt_sha256: string };
  };
}
export function createMot3DFinalValidationTransitionApi(
  session: () => Promise<string>,
) {
  let generation = 0;
  const contexts = new Map<
      string,
      { campaignId: string; csrf: string; generation: number }
    >(),
    body = (campaign_id: string, p: Profile) => ({
      campaign_id,
      username: p.username,
      project_directory: p.project_directory,
    });
  return {
    async status(campaignId: string, p: Profile) {
      const g = generation,
        v = parseMot3DFinalValidationTransitionStatus(
          await postData(
            "/api/v1/zeus/mot-3d/final-validation-transition/status",
            body(campaignId, p),
            await session(),
            adapt,
          ),
        );
      if (g !== generation || v.campaign.id !== campaignId)
        throw new Error("Final-validation transition status is stale.");
      return v;
    },
    async preview(campaignId: string, p: Profile, commit: string) {
      const g = generation,
        csrf = await session(),
        v = parseMot3DFinalValidationTransitionPreview(
          await postData(
            "/api/v1/zeus/mot-3d/final-validation-transition/preview",
            body(campaignId, p),
            csrf,
            adapt,
          ),
          { campaignId, commit },
        );
      if (g !== generation)
        throw new Error("Final-validation transition review is stale.");
      contexts.set(v.preview_token, { campaignId, csrf, generation: g });
      return v;
    },
    async confirm(t: string) {
      const c = contexts.get(t);
      if (!c) throw new Error("Review is no longer active.");
      contexts.delete(t);
      try {
        const v = parseMot3DFinalValidationTransitionResult(
          await postData(
            "/api/v1/zeus/mot-3d/final-validation-transition/confirm",
            { preview_token: t },
            c.csrf,
            (error) => adaptConfirmationError(error, adapt, Mot3DFinalValidationTransitionApiError),
          ),
          c.campaignId,
        );
        if (c.generation !== generation) throw new Error("stale");
        return v;
      } catch (e) {
        if (e instanceof Mot3DFinalValidationTransitionApiError) throw e;
        throw new Mot3DFinalValidationTransitionApiError(
          "transition_outcome_unknown",
          "The transition outcome could not be verified. Do not retry.",
        );
      }
    },
    reset() {
      generation += 1;
      contexts.clear();
    },
  };
}
export type Mot3DFinalValidationTransitionApi = ReturnType<
  typeof createMot3DFinalValidationTransitionApi
>;
export const mot3DFinalValidationTransitionApi =
  createMot3DFinalValidationTransitionApi(() => creationApi.session());
