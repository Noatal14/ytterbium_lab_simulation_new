/** Shared checks for the existing selection-transition wire contracts.
 * Descriptors select actual wire names/counts; replies are never rewritten as another stage.
 */
import { MOT_3D_REFINEMENT_INVALID_REASONS } from "../../generated/mot3dRefinementTransitionSpec.v1";
import { boundedPrintable, exactKeys } from "../schema/common";
import {
  type Mot3DFamilyChain,
  isMot3DFamilyCanonicalPrefix,
  mot3DFamilyJobCount,
  parseMot3DFamilyChain,
} from "./mot3dFamilyChain";

type Descriptor = {
  stage: string;
  nextStage: string;
  prepared: string;
  openAction: string;
  resultFiles: number;
  selectionFiles: number;
  jobFiles: number;
  transferFiles: number;
  synchronizedFiles: number;
  createdFiles: number;
  synchronizeEffect: string;
  prepareEffect: string;
  submitEffect: string;
  previewExtraKeys: readonly string[];
};
export const REFINEMENT_TRANSITION = {
  stage: "refinement",
  nextStage: "closure",
  prepared: "closure_prepared",
  openAction: "open_closure",
  resultFiles: 200,
  selectionFiles: 2,
  jobFiles: 4,
  transferFiles: 208,
  synchronizedFiles: 201,
  createdFiles: 6,
  synchronizeEffect: "synchronize_refinement",
  prepareEffect: "prepare_closure",
  submitEffect: "submit_closure",
  previewExtraKeys: [],
} as const satisfies Descriptor;
export const FINALIST_TRANSITION = {
  stage: "finalist_selection",
  nextStage: "final_validation_input_generation",
  prepared: "final_validation_input_generation_prepared",
  openAction: "open_final_validation_input_generation",
  resultFiles: 44,
  selectionFiles: 1,
  jobFiles: 3,
  transferFiles: 50,
  synchronizedFiles: 45,
  createdFiles: 4,
  synchronizeEffect: "synchronize_finalist_selection",
  prepareEffect: "prepare_final_validation_inputs",
  submitEffect: "submit_final_validation_inputs",
  previewExtraKeys: ["winner_selection"],
} as const satisfies Descriptor;
const SHA40 = /^[0-9a-f]{40}$/;
const SHA256 = /^[0-9a-f]{64}$/;
export function transitionObject(
  value: unknown,
  keys: readonly string[],
): Record<string, unknown> {
  if (
    !value ||
    typeof value !== "object" ||
    Array.isArray(value) ||
    !exactKeys(value as Record<string, unknown>, [...keys])
  )
    throw new Error("Invalid 3D transition object.");
  return value as Record<string, unknown>;
}
function text(value: unknown, maximum = 256): string {
  if (!boundedPrintable(value, maximum) || value.length === 0)
    throw new Error("Invalid 3D transition text.");
  return value;
}
function hash(value: unknown, pattern = SHA256): string {
  if (typeof value !== "string" || !pattern.test(value))
    throw new Error("Invalid 3D transition digest.");
  return value;
}
function choice<T extends string>(value: unknown, allowed: readonly T[]): T {
  if (typeof value !== "string" || !allowed.includes(value as T))
    throw new Error("Invalid 3D transition state.");
  return value as T;
}
function count(value: unknown, maximum: number): number {
  if (
    typeof value !== "number" ||
    !Number.isInteger(value) ||
    value < 0 ||
    value > maximum
  )
    throw new Error("Invalid 3D transition count.");
  return value;
}
function synchronization(value: unknown) {
  const row = transitionObject(value, ["status", "receipt_sha256"]);
  if (row.status === "synchronized")
    return {
      status: "synchronized" as const,
      receipt_sha256: hash(row.receipt_sha256),
    };
  if (row.status !== "not_synchronized" || row.receipt_sha256 !== null)
    throw new Error("Invalid 3D transition synchronization.");
  return { status: "not_synchronized" as const, receipt_sha256: null };
}
const lifecycleStates = [
  "not_submitted",
  "submitted",
  "queued",
  "running",
  "held",
  "completed_failed",
  "status_unknown",
  "partial",
  "outcome_unknown",
  "completed_success_unvalidated",
  "ready_to_advance",
] as const;
type ParsedStatus<D extends Descriptor> = {
  source: "zeus";
  queried_at: string;
  campaign: { id: string; name: string; stage: D["stage"] | D["nextStage"] };
  evidence: {
    status: (typeof lifecycleStates)[number] | D["prepared"];
    chain: Mot3DFamilyChain;
  };
  scheduler: {
    expected_array_tasks: 6;
    expected_merge_jobs: 2;
    completed_array_tasks: number;
    completed_merge_jobs: number;
  };
  validation: {
    status: "not_started" | "valid" | "scientifically_invalid";
    result_artifacts: number;
    expected_result_artifacts: D["resultFiles"];
    reason_code: (typeof MOT_3D_REFINEMENT_INVALID_REASONS)[number] | null;
  };
  transition: { status: "not_prepared" | D["prepared"] };
  next_action:
    | "wait"
    | "review_transition"
    | "synchronize_results"
    | "inspect_zeus"
    | D["openAction"];
  local_sync: ReturnType<typeof synchronization>;
};
type ParsedPreview<D extends Descriptor> = {
  common: {
    preview_token: string;
    expires_in_seconds: 300;
    campaign: { id: string; name: string; git_commit: string };
    from_stage: D["stage"];
    to_stage: D["nextStage"];
    evidence: {
      result_artifacts: D["resultFiles"];
      expected_result_artifacts: D["resultFiles"];
      families: ["angled_donut", "single_pass"];
      evidence_sha256: string;
    };
    artifacts: {
      synchronize: { result_files: D["resultFiles"]; submission_receipts: 1 };
      create: {
        selection_files: D["selectionFiles"];
        job_files: D["jobFiles"];
      };
      update: ["campaign.json"];
      transfer_files: D["transferFiles"];
    };
  };
  winnerSelection: unknown;
};
type ParsedResult<D extends Descriptor> = {
  status: D["prepared"];
  campaign_id: string;
  stage: D["nextStage"];
  artifacts: {
    synchronized: D["synchronizedFiles"];
    created: D["createdFiles"];
    updated: 1;
    bundle_sha256: string;
  };
  submitted_to_zeus: false;
  simulation_started: false;
  local_sync: { status: "synchronized"; receipt_sha256: string };
};
export function parseSelectionTransitionStatus<D extends Descriptor>(
  value: unknown,
  d: D,
): ParsedStatus<D> {
  const row = transitionObject(value, [
    "source",
    "queried_at",
    "campaign",
    d.stage,
    "scheduler",
    "validation",
    "transition",
    "next_action",
    "local_sync",
  ]);
  const campaign = transitionObject(row.campaign, ["id", "name", "stage"]);
  const evidence = transitionObject(row[d.stage], ["status", "chain"]);
  const scheduler = transitionObject(row.scheduler, [
    "expected_array_tasks",
    "expected_merge_jobs",
    "completed_array_tasks",
    "completed_merge_jobs",
  ]);
  const validation = transitionObject(row.validation, [
    "status",
    "result_artifacts",
    "expected_result_artifacts",
    "reason_code",
  ]);
  const transition = transitionObject(row.transition, ["status"]);
  const local = synchronization(row.local_sync);
  const lifecycle = choice<(typeof lifecycleStates)[number] | D["prepared"]>(
    evidence.status,
    [...lifecycleStates, d.prepared],
  );
  const chain = parseMot3DFamilyChain(evidence.chain);
  const jobs = mot3DFamilyJobCount(chain);
  const validationStatus = choice(validation.status, [
    "not_started",
    "valid",
    "scientifically_invalid",
  ] as const);
  const valid = validationStatus === "valid",
    invalid = validationStatus === "scientifically_invalid";
  const chainOk =
    isMot3DFamilyCanonicalPrefix(chain) &&
    (lifecycle === "not_submitted"
      ? jobs === 0
      : lifecycle === "partial"
        ? jobs >= 1 && jobs <= 3
        : lifecycle === "outcome_unknown"
          ? valid
            ? jobs === 4
            : jobs <= 3
          : jobs === 4);
  const arrays = chain.families.filter((f) => f.array_job_id !== null).length;
  const merges = chain.families.filter((f) => f.merge_job_id !== null).length;
  const a = count(scheduler.completed_array_tasks, 6),
    m = count(scheduler.completed_merge_jobs, 2);
  const initial =
    ["not_submitted", "submitted"].includes(lifecycle) ||
    (lifecycle === "outcome_unknown" && !valid);
  const complete =
    ["completed_success_unvalidated", "ready_to_advance", d.prepared].includes(
      lifecycle,
    ) ||
    (lifecycle === "outcome_unknown" && valid);
  const countsOk =
    a <= arrays * 3 &&
    m <= merges &&
    (!initial || (a === 0 && m === 0)) &&
    (!complete || (a === 6 && m === 2)) &&
    (lifecycle !== "queued" || a !== 6 || m !== 2);
  const resultArtifacts = count(validation.result_artifacts, d.resultFiles);
  const reason = invalid
    ? choice(validation.reason_code, MOT_3D_REFINEMENT_INVALID_REASONS)
    : null;
  const validationOk =
    validation.expected_result_artifacts === d.resultFiles &&
    (valid
      ? resultArtifacts === d.resultFiles && validation.reason_code === null
      : invalid
        ? resultArtifacts === 0
        : resultArtifacts === 0 && validation.reason_code === null);
  const campaignStage = choice<D["stage"] | D["nextStage"]>(campaign.stage, [
    d.stage,
    d.nextStage,
  ]);
  const transitionStatus = choice<"not_prepared" | D["prepared"]>(
    transition.status,
    ["not_prepared", d.prepared],
  );
  const nextAction = choice<ParsedStatus<D>["next_action"]>(row.next_action, [
    "wait",
    "review_transition",
    "synchronize_results",
    d.openAction,
    "inspect_zeus",
  ]);
  const expected =
    lifecycle === d.prepared
      ? local.status === "synchronized"
        ? ["valid", d.prepared, d.openAction, d.nextStage, "synchronized"]
        : [
            "valid",
            d.prepared,
            "synchronize_results",
            d.stage,
            "not_synchronized",
          ]
      : lifecycle === "ready_to_advance"
        ? [
            "valid",
            "not_prepared",
            "review_transition",
            d.stage,
            "not_synchronized",
          ]
        : lifecycle === "completed_success_unvalidated"
          ? invalid
            ? [
                "scientifically_invalid",
                "not_prepared",
                "inspect_zeus",
                d.stage,
                "not_synchronized",
              ]
            : [
                "not_started",
                "not_prepared",
                "review_transition",
                d.stage,
                "not_synchronized",
              ]
          : lifecycle === "outcome_unknown" && valid
            ? [
                "valid",
                "not_prepared",
                "inspect_zeus",
                d.stage,
                "not_synchronized",
              ]
            : [
                "not_started",
                "not_prepared",
                ["submitted", "queued", "running"].includes(lifecycle)
                  ? "wait"
                  : "inspect_zeus",
                d.stage,
                "not_synchronized",
              ];
  const observed = [
    validationStatus,
    transitionStatus,
    nextAction,
    campaignStage,
    local.status,
  ];
  const queriedAt = text(row.queried_at);
  if (
    row.source !== "zeus" ||
    Number.isNaN(Date.parse(queriedAt)) ||
    !chainOk ||
    scheduler.expected_array_tasks !== 6 ||
    scheduler.expected_merge_jobs !== 2 ||
    !countsOk ||
    !validationOk ||
    !expected.every((item, index) => item === observed[index])
  )
    throw new Error("Invalid 3D transition status.");
  return {
    source: "zeus" as const,
    queried_at: queriedAt,
    campaign: {
      id: text(campaign.id, 512),
      name: text(campaign.name, 128),
      stage: campaignStage,
    },
    evidence: { status: lifecycle, chain },
    scheduler: {
      expected_array_tasks: 6 as const,
      expected_merge_jobs: 2 as const,
      completed_array_tasks: a,
      completed_merge_jobs: m,
    },
    validation: {
      status: validationStatus,
      result_artifacts: resultArtifacts,
      expected_result_artifacts: d.resultFiles,
      reason_code: reason,
    },
    transition: { status: transitionStatus },
    next_action: nextAction,
    local_sync: local,
  };
}
export function parseSelectionTransitionPreview<D extends Descriptor>(
  value: unknown,
  campaignId: string,
  d: D,
): ParsedPreview<D> {
  const row = transitionObject(value, [
    "preview_token",
    "expires_in_seconds",
    "campaign",
    "from_stage",
    "to_stage",
    d.stage,
    "artifacts",
    "effects",
    ...d.previewExtraKeys,
  ]);
  const campaign = transitionObject(row.campaign, ["id", "name", "git_commit"]);
  const evidence = transitionObject(row[d.stage], [
    "result_artifacts",
    "expected_result_artifacts",
    "families",
    "evidence_sha256",
  ]);
  const artifacts = transitionObject(row.artifacts, [
    "synchronize",
    "create",
    "update",
    "transfer_files",
  ]);
  const synchronize = transitionObject(artifacts.synchronize, [
    "result_files",
    "submission_receipts",
  ]);
  const create = transitionObject(artifacts.create, [
    "selection_files",
    "job_files",
  ]);
  const effects = transitionObject(row.effects, [
    d.synchronizeEffect,
    d.prepareEffect,
    d.submitEffect,
    "start_simulation",
    "overwrite_existing",
  ]);
  if (
    row.expires_in_seconds !== 300 ||
    campaign.id !== campaignId ||
    row.from_stage !== d.stage ||
    row.to_stage !== d.nextStage ||
    evidence.result_artifacts !== d.resultFiles ||
    evidence.expected_result_artifacts !== d.resultFiles ||
    JSON.stringify(evidence.families) !==
      JSON.stringify(["angled_donut", "single_pass"]) ||
    synchronize.result_files !== d.resultFiles ||
    synchronize.submission_receipts !== 1 ||
    create.selection_files !== d.selectionFiles ||
    create.job_files !== d.jobFiles ||
    JSON.stringify(artifacts.update) !== JSON.stringify(["campaign.json"]) ||
    artifacts.transfer_files !== d.transferFiles ||
    effects[d.synchronizeEffect] !== true ||
    effects[d.prepareEffect] !== true ||
    effects[d.submitEffect] !== false ||
    effects.start_simulation !== false ||
    effects.overwrite_existing !== false
  )
    throw new Error("Invalid 3D transition preview.");
  return {
    common: {
      preview_token: text(row.preview_token, 512),
      expires_in_seconds: 300 as const,
      campaign: {
        id: campaignId,
        name: text(campaign.name, 128),
        git_commit: hash(campaign.git_commit, SHA40),
      },
      from_stage: d.stage,
      to_stage: d.nextStage,
      evidence: {
        result_artifacts: d.resultFiles,
        expected_result_artifacts: d.resultFiles,
        families: ["angled_donut", "single_pass"] as [
          "angled_donut",
          "single_pass",
        ],
        evidence_sha256: hash(evidence.evidence_sha256),
      },
      artifacts: {
        synchronize: {
          result_files: d.resultFiles,
          submission_receipts: 1 as const,
        },
        create: { selection_files: d.selectionFiles, job_files: d.jobFiles },
        update: ["campaign.json"] as ["campaign.json"],
        transfer_files: d.transferFiles,
      },
    },
    // Extensions stay unknown until the stage-specific parser validates them.
    winnerSelection: row.winner_selection,
  };
}
export function parseSelectionTransitionResult<D extends Descriptor>(
  value: unknown,
  campaignId: string,
  d: D,
): ParsedResult<D> {
  const row = transitionObject(value, [
    "status",
    "campaign_id",
    "stage",
    "artifacts",
    "submitted_to_zeus",
    "simulation_started",
    "local_sync",
  ]);
  const artifacts = transitionObject(row.artifacts, [
    "synchronized",
    "created",
    "updated",
    "bundle_sha256",
  ]);
  const local = synchronization(row.local_sync);
  if (
    row.status !== d.prepared ||
    row.campaign_id !== campaignId ||
    row.stage !== d.nextStage ||
    artifacts.synchronized !== d.synchronizedFiles ||
    artifacts.created !== d.createdFiles ||
    artifacts.updated !== 1 ||
    row.submitted_to_zeus !== false ||
    row.simulation_started !== false ||
    local.status !== "synchronized"
  )
    throw new Error("Invalid 3D transition result.");
  return {
    status: d.prepared,
    campaign_id: campaignId,
    stage: d.nextStage,
    artifacts: {
      synchronized: d.synchronizedFiles,
      created: d.createdFiles,
      updated: 1 as const,
      bundle_sha256: hash(artifacts.bundle_sha256),
    },
    submitted_to_zeus: false as const,
    simulation_started: false as const,
    local_sync: {
      status: "synchronized" as const,
      receipt_sha256: hash(local.receipt_sha256),
    },
  };
}
