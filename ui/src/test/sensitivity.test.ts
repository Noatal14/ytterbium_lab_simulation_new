import { describe, expect, it } from "vitest";
import success from "../../../tests/contracts/v1/workflow_api_success.json";
import {
  parseSensitivityPreview,
  parseSensitivityStatus,
  parseSensitivitySubmissionPreview,
  parseSensitivitySubmissionStatus,
} from "../api/schema/domain";
const data = (id: string) =>
  success.cases.find((row) => row.id === id)!.body.data as Record<
    string,
    unknown
  >;
describe("Sensitivity strict response contracts", () => {
  it("accepts the reviewed backend snapshots", () => {
    expect(
      parseSensitivityStatus(data("sensitivity-status")).validation.status,
    ).toBe("valid");
    expect(parseSensitivityPreview(data("sensitivity-preview")).job.file).toBe(
      "jobs/05_sensitivity.pbs",
    );
    expect(
      parseSensitivitySubmissionStatus(data("sensitivity-submit-status"))
        .campaign.stage,
    ).toBe("sensitivity");
    expect(
      parseSensitivitySubmissionPreview(data("sensitivity-submit-preview"))
        .stage.id,
    ).toBe("sensitivity");
  });
  it("rejects extra fields and inconsistent identities", () => {
    expect(() =>
      parseSensitivityStatus({ ...data("sensitivity-status"), secret: true }),
    ).toThrow();
    expect(() =>
      parseSensitivityPreview({
        ...data("sensitivity-preview"),
        campaign: {
          ...(data("sensitivity-preview").campaign as object),
          id: "other",
        },
        secret: true,
      }),
    ).toThrow();
    expect(() =>
      parseSensitivitySubmissionStatus({
        ...data("sensitivity-submit-status"),
        campaign: {
          ...(data("sensitivity-submit-status").campaign as object),
          stage: "confirmation",
        },
      }),
    ).toThrow();
    expect(() =>
      parseSensitivitySubmissionPreview({
        ...data("sensitivity-submit-preview"),
        remote: {
          ...(data("sensitivity-submit-preview").remote as object),
          commit: "b".repeat(40),
        },
      }),
    ).toThrow();
  });
  it("rejects scheduler, nonce, count, and held-out design drift", () => {
    const status = data("sensitivity-status"),
      confirmation = status.confirmation as Record<string, unknown>,
      scheduler = confirmation.scheduler as Record<string, unknown>;
    for (const patch of [
      { state: "surprise" },
      { submission_nonce: "x".repeat(32) },
      { task_count: 1001 },
      { counts: { queued: 5, running: 0, held: 0, succeeded: 0, failed: 0 } },
    ])
      expect(() =>
        parseSensitivityStatus({
          ...status,
          confirmation: {
            ...confirmation,
            scheduler: { ...scheduler, ...patch },
          },
        }),
      ).toThrow();
    const preview = data("sensitivity-preview"),
      held = preview.confirmation as Record<string, unknown>;
    expect(() =>
      parseSensitivityPreview({
        ...preview,
        confirmation: { ...held, expected_points: 6, completed_points: 6 },
      }),
    ).toThrow();
    expect(() =>
      parseSensitivitySubmissionPreview({
        ...data("sensitivity-submit-preview"),
        job: {
          ...(data("sensitivity-submit-preview").job as object),
          task_count: 1001,
        },
      }),
    ).toThrow();
  });
});

it("preserves the actual clamped and deduplicated sensitivity task count in both reviews", () => {
  // A boundary winner legitimately yields16 instead of the maximum17 tasks.
  // The backend proves the frozen registry; the UI must display that count.
  for (const [id, parse] of [["sensitivity-preview", parseSensitivityPreview], ["sensitivity-submit-preview", parseSensitivitySubmissionPreview]] as const) {
    const value = structuredClone(data(id));
    (value.job as Record<string, unknown>).task_count = 16;
    expect(parse(value).job.task_count).toBe(16);
    for (const task_count of [0, -1, 1.5, 1001]) {
      expect(() => parse({ ...value, job: { ...(value.job as object), task_count } })).toThrow();
    }
  }
});
