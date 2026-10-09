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

// These are synthesized only when a response cannot be verified locally. They
// are deliberately separate from server metadata even when the public code is
// also understood by the corresponding server domain.
export const synthesizedUncertainty = {
  smoke_submission: "submission_outcome_unknown",
  refinement_submission: "refinement_submission_outcome_unknown",
} as const;
