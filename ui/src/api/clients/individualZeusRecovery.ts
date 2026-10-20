import { exactKeys, isRecord } from "../http/envelope";

export class IndividualZeusApiError extends Error {
  constructor(
    public code: string,
    message: string,
  ) {
    super(message);
  }
}

const definitelyRejected = new Set([
  "confirmation_invalid",
  "confirmation_expired",
  "profile_invalid",
  "run_not_submittable",
  "run_evidence_changed",
  "too_many_pending_previews",
]);

export const individualZeusConfirmWasDefinitelyRejected = (cause: unknown) =>
  cause instanceof IndividualZeusApiError && definitelyRejected.has(cause.code);

export const individualZeusApiError = (error: {
  code: string;
  message: string;
}) => new IndividualZeusApiError(error.code, error.message);

export type IndividualZeusRecovery = {
  run_id: string;
  family: "zeeman" | "mot_2d" | "mot_3d";
  job_id: string;
  scheduler_state: "queued" | "running" | "held" | "succeeded" | "failed";
  exit_status: number | null;
  local_state:
    | "configured"
    | "validated"
    | "reviewed"
    | "queued"
    | "running"
    | "held"
    | "succeeded"
    | "failed"
    | "outcome_unknown"
    | "cancelled";
  read_only: true;
};

const schedulerStates = new Set([
  "queued",
  "running",
  "held",
  "succeeded",
  "failed",
]);
const localStates = new Set([
  "configured",
  "validated",
  "reviewed",
  "queued",
  "running",
  "succeeded",
  "failed",
  "outcome_unknown",
  "cancelled",
]);

export function parseIndividualZeusRecovery(
  value: unknown,
  expectedFamily: IndividualZeusRecovery["family"],
  expectedRunId: string,
): IndividualZeusRecovery {
  if (
    !isRecord(value) ||
    !exactKeys(value, [
      "run_id",
      "family",
      "job_id",
      "scheduler_state",
      "exit_status",
      "local_state",
      "read_only",
    ]) ||
    value.run_id !== expectedRunId ||
    value.family !== expectedFamily ||
    typeof value.job_id !== "string" ||
    !/^\d+\.zeus-master$/.test(value.job_id) ||
    !schedulerStates.has(String(value.scheduler_state)) ||
    (value.exit_status !== null && !Number.isInteger(value.exit_status)) ||
    !localStates.has(String(value.local_state)) ||
    value.read_only !== true
  ) {
    throw new Error("Invalid individual Zeus recovery response.");
  }
  return value as IndividualZeusRecovery;
}
