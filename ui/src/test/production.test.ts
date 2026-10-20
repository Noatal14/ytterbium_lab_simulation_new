import { afterEach, describe, expect, it, vi } from "vitest";
import success from "../../../tests/contracts/v1/workflow_api_success.json";
import {
  parseFinalizationPreview,
  parseFinalizationResult,
  parseFinalizationStatus,
  parseProductionPreview,
  parseProductionStatus,
  parseProductionSubmissionPreview,
  parseProductionSubmissionStatus,
} from "../api/schema/domain";
const data = (id: string) =>
  success.cases.find((row) => row.id === id)!.body.data as Record<
    string,
    unknown
  >;
describe("Production and finalization strict contracts", () => {
  it("accepts reviewed backend snapshots", () => {
    expect(
      parseProductionStatus(data("production-status")).validation.status,
    ).toBe("valid");
    expect(
      parseProductionPreview(data("production-preview")).job.task_count,
    ).toBe(20);
    expect(
      parseProductionSubmissionStatus(data("production-submit-status")).campaign
        .stage,
    ).toBe("production");
    expect(
      parseProductionSubmissionPreview(data("production-submit-preview")).stage
        .id,
    ).toBe("production");
    expect(
      parseFinalizationStatus(data("finalization-status")).validation
        .completed_ensembles,
    ).toBe(20);
    expect(
      parseFinalizationPreview(data("finalization-preview")).results,
    ).toHaveLength(1);
    expect(
      parseFinalizationResult(data("finalization-confirm")).results[0]
        .n_ensembles,
    ).toBe(20);
  });
  it("rejects stage, scheduler, resource, and sealed-design drift", () => {
    const status = data("production-status"),
      sensitivity = status.sensitivity as Record<string, unknown>,
      scheduler = sensitivity.scheduler as Record<string, unknown>;
    for (const patch of [
      { state: "surprise" },
      { task_count: 18 },
      { submission_nonce: "x".repeat(32) },
      { counts: { queued: 0, running: 0, held: 0, succeeded: 16, failed: 1 } },
    ])
      expect(() =>
        parseProductionStatus({
          ...status,
          sensitivity: {
            ...sensitivity,
            scheduler: { ...scheduler, ...patch },
          },
        }),
      ).toThrow();
    expect(() =>
      parseProductionPreview({
        ...data("production-preview"),
        job: { ...(data("production-preview").job as object), task_count: 19 },
      }),
    ).toThrow();
    expect(() =>
      parseProductionSubmissionPreview({
        ...data("production-submit-preview"),
        remote: {
          ...(data("production-submit-preview").remote as object),
          commit: "b".repeat(40),
        },
      }),
    ).toThrow();
    const final = data("finalization-preview"),
      rows = structuredClone(final.results) as Record<string, unknown>[];
    rows[0].n_ensembles = 19;
    expect(() =>
      parseFinalizationPreview({ ...final, results: rows }),
    ).toThrow();
    const rows2 = structuredClone(final.results) as Record<string, unknown>[],
      prediction = rows2[0].prediction as Record<string, unknown>;
    prediction.simulated_captured_atoms = 99;
    expect(() =>
      parseFinalizationPreview({ ...final, results: rows2 }),
    ).toThrow();
  });
  it("rejects extra fields and unsealed result suitability", () => {
    expect(() =>
      parseFinalizationStatus({ ...data("finalization-status"), secret: true }),
    ).toThrow();
    const final = data("finalization-confirm"),
      rows = structuredClone(final.results) as Record<string, unknown>[];
    rows[0].output_suitability = "individual_only";
    expect(() =>
      parseFinalizationResult({ ...final, results: rows }),
    ).toThrow();
    for (const mutation of [
      (row: Record<string, unknown>) => { row.robustness_status = "established"; },
      (row: Record<string, unknown>) => { row.warnings = ["looks_good"]; },
      (row: Record<string, unknown>) => {
        row.target_uncertainty_passes = false;
      },
    ]) {
      const changed = structuredClone(final.results) as Record<string, unknown>[];
      mutation(changed[0]);
      expect(() =>
        parseFinalizationResult({ ...final, results: changed }),
      ).toThrow();
    }
  });
});


afterEach(() => vi.unstubAllEnvs());
it.each([
  ["development", "eligible_as_3d_campaign_input", "acceptance_only"],
  ["ui-acceptance", "acceptance_only", "eligible_as_3d_campaign_input"],
])("keeps finalized %s results on their exact suitability boundary", (mode, expected, forbidden) => {
  vi.stubEnv("MODE",mode);
  for (const [id,parse] of [["finalization-preview",parseFinalizationPreview],["finalization-confirm",parseFinalizationResult]] as const) {
    const value = structuredClone(data(id));
    const results = value.results as Record<string,unknown>[];
    results[0].output_suitability = expected;
    expect(parse(value).results[0].output_suitability).toBe(expected);
    results[0].output_suitability = forbidden;
    expect(() => parse(value)).toThrow();
    delete results[0].output_suitability;
    expect(() => parse(value)).toThrow();
  }
});
