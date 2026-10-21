import { serverErrorCatalog } from "../generated/errorCatalog.v1";

export type ServerErrorDomain = (typeof serverErrorCatalog)[number]["domain"];
export type ErrorSemantic = (typeof serverErrorCatalog)[number]["semantic"];

const byDomain = new Map<string, Map<string, ErrorSemantic>>();
for (const row of serverErrorCatalog) {
  const codes = byDomain.get(row.domain) ?? new Map<string, ErrorSemantic>();
  codes.set(row.code, row.semantic);
  byDomain.set(row.domain, codes);
}

export function errorHasSemantic(
  domain: ServerErrorDomain,
  code: unknown,
  semantic: ErrorSemantic,
): boolean {
  return typeof code === "string" && byDomain.get(domain)?.get(code) === semantic;
}

export function isKnownServerError(domain: ServerErrorDomain, code: unknown): boolean {
  return typeof code === "string" && byDomain.get(domain)?.has(code) === true;
}

export function requiresManualVerification(
  domain: ServerErrorDomain,
  code: unknown,
): boolean {
  if (!isKnownServerError(domain, code)) return true;
  const semantic = byDomain.get(domain)?.get(String(code));
  return semantic === "manual_verification" || semantic === "outcome_unknown";
}

// Confirmation can have changed remote state before this response error arrives.
// Read/status semantics remain unchanged; this guard is used only after confirm.
const confirmationPreflightCodes = new Set([
  "unsupported_query", "session_unavailable", "untrusted_origin", "invalid_campaign_id",
  "not_found", "method_not_allowed", "invalid_preview", "invalid_request_target",
  "untrusted_host", "invalid_session", "invalid_csrf",
]);
const confirmationFallbackCodes: Partial<Record<ServerErrorDomain, readonly string[]>> = {
  mot_3d_refinement_submission: ["mot_3d_refinement_submission_failed", "mot_3d_refinement_submission_unavailable"],
  mot_3d_closure_submission: ["mot_3d_closure_submission_failed", "mot_3d_closure_submission_unavailable"],
  mot_3d_closure_transition: ["mot_3d_closure_transition_failed", "mot_3d_closure_transition_unavailable"],
  mot_3d_finalist_submission: ["mot_3d_finalist_submission_failed", "mot_3d_finalist_submission_unavailable"],
  mot_3d_finalist_transition: ["mot_3d_finalist_transition_failed", "mot_3d_finalist_transition_unavailable"],
  mot_3d_final_input_submission: ["mot_3d_final_input_submission_failed", "mot_3d_final_input_submission_unavailable"],
  mot_3d_final_validation_submission: ["mot_3d_final_validation_submission_failed", "mot_3d_final_validation_submission_unavailable"],
  mot_3d_final_validation_transition: ["mot_3d_final_validation_transition_failed", "mot_3d_final_validation_transition_unavailable"],
  mot_3d_final_validation_completion: ["mot_3d_final_validation_completion_failed", "mot_3d_final_validation_completion_unavailable"],
};
export function confirmationRequiresManualVerification(domain: ServerErrorDomain, code: unknown): boolean {
  if (typeof code === "string" && confirmationPreflightCodes.has(code)) return false;
  return code === "remote_response_invalid" ||
    (typeof code === "string" && confirmationFallbackCodes[domain]?.includes(code) === true) ||
    requiresManualVerification(domain, code);
}

// Preserve proven pre-dispatch protocol rejections only on the confirm path.
// An unknown/internal server error still follows the existing domain adapter.
export function adaptConfirmationError<T extends Error & { code: string }>(
  error: { code: string; message: string },
  adapt: (error: { code: string; message: string }) => T,
  ErrorType: new (code: string, message: string) => T,
): T {
  if (confirmationPreflightCodes.has(error.code)) return new ErrorType(error.code, error.message);
  const adapted = adapt(error);
  const internalFailure = ["creation_failed", "inspection_failed", "source_inspection_failed"].includes(error.code);
  const domainFallback = Object.values(confirmationFallbackCodes).some(codes => codes.includes(adapted.code));
  return internalFailure || domainFallback
    ? new ErrorType(adapted.code, "The operation outcome is unknown. Check the current campaign status. Do not retry or submit again automatically.")
    : adapted;
}

// These are synthesized only when a response cannot be verified locally. They
// are deliberately separate from server metadata even when the public code is
// also understood by the corresponding server domain.
export const synthesizedUncertainty = {
  smoke_submission: "submission_outcome_unknown",
  refinement_submission: "refinement_submission_outcome_unknown",
  confirmation_submission: "confirmation_submission_outcome_unknown",
  sensitivity_submission: "sensitivity_submission_outcome_unknown",
  production_submission: "production_submission_outcome_unknown",
} as const;
