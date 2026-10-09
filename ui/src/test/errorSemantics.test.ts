import { describe, expect, it } from "vitest";

import backendCatalog from "../../../tests/contracts/v1/workflow_api_error_catalog.json";
import {
  errorHasSemantic,
  isKnownServerError,
  requiresManualVerification,
  synthesizedUncertainty,
  type ServerErrorDomain,
} from "../api/errorSemantics";
import { serverErrorCatalog } from "../generated/errorCatalog.v1";

describe("generated frontend error semantics", () => {
  it("contains every backend domain/code without copying server messages", () => {
    const expected = new Set(
      backendCatalog.cases
        .filter((row) => row.case !== "<fallback>")
        .map((row) => `${row.domain}:${row.code}`),
    );
    const observed = new Set(serverErrorCatalog.map((row) => `${row.domain}:${row.code}`));
    expect(observed).toEqual(expected);
    expect(JSON.stringify(serverErrorCatalog)).not.toContain("message");
  });

  it("keeps domain-specific safety meanings and fails closed across domains", () => {
    expect(errorHasSemantic("smoke_submission", "already_submitted", "manual_verification")).toBe(true);
    expect(errorHasSemantic("smoke_submission", "submission_record_invalid", "manual_verification")).toBe(true);
    expect(errorHasSemantic("smoke_transition", "confirmation_expired", "fresh_review")).toBe(true);
    expect(errorHasSemantic("screen_submission", "screening_submission_outcome_unknown", "outcome_unknown")).toBe(true);
    expect(errorHasSemantic("refinement_transition", "refinement_already_prepared", "already_prepared")).toBe(true);
    expect(errorHasSemantic("confirmation_transition", "transition_conflict", "manual_verification")).toBe(true);

    expect(isKnownServerError("smoke_submission", "confirmation_expired")).toBe(true);
    expect(isKnownServerError("screen_submission", "already_submitted")).toBe(false);
    expect(requiresManualVerification("screen_submission", "already_submitted")).toBe(true);
    expect(requiresManualVerification("confirmation_transition", "internal_secret_code")).toBe(true);
    expect(requiresManualVerification("smoke_transition", "request_invalid")).toBe(false);
  });

  it("marks synthesized uncertainty separately from server metadata", () => {
    expect(synthesizedUncertainty).toEqual({
      smoke_submission: "submission_outcome_unknown",
      refinement_submission: "refinement_submission_outcome_unknown",
    });
    for (const [domain, code] of Object.entries(synthesizedUncertainty)) {
      expect(isKnownServerError(domain as ServerErrorDomain, code)).toBe(true);
      expect(errorHasSemantic(domain as ServerErrorDomain, code, "outcome_unknown")).toBe(true);
    }
  });
});
