import { describe, expect, it } from "vitest";
import captured from "./fixtures/c56-closure-queued-partial-status.json";
import { parsePreliminaryCheckStatus } from "../api/clients/mot3dPreliminaryCheck";
import { parseMot3DPreliminaryTransitionStatus } from "../api/clients/mot3dPreliminaryTransition";
import { parseMot3DRefinementSubmissionStatus } from "../api/clients/mot3dRefinementSubmission";
import { parseMot3DRefinementTransitionStatus } from "../api/clients/mot3dRefinementTransition";
import { parseMot3DClosureSubmissionStatus } from "../api/clients/mot3dClosureSubmission";
import { parseMot3DClosureTransitionStatus } from "../api/clients/mot3dClosureTransition";
import { parseMot3DFinalistSubmissionStatus } from "../api/clients/mot3dFinalistSubmission";
import { parseMot3DFinalistTransitionStatus } from "../api/clients/mot3dFinalistTransition";
import { parseMot3DFinalValidationSubmissionStatus } from "../api/clients/mot3dFinalValidationSubmission";
type Row = Record<string, unknown>;
const child = (r: Row, key: string) => r[key] as Row;
const cases = [
  { label: "Preliminary submission", parse: parsePreliminaryCheckStatus, stage: "preliminary_check", kind: "submission", candidates: 12 },
  { label: "Preliminary transition", parse: parseMot3DPreliminaryTransitionStatus, stage: "preliminary_check", kind: "preliminary", artifacts: 152 },
  { label: "Refinement submission", parse: parseMot3DRefinementSubmissionStatus, stage: "refinement", kind: "submission", candidates: 16 },
  { label: "Refinement transition", parse: parseMot3DRefinementTransitionStatus, stage: "refinement", kind: "refinement", artifacts: 200 },
  { label: "Closure submission", parse: parseMot3DClosureSubmissionStatus, stage: "closure", kind: "submission", candidates: 16 },
  { label: "Closure transition", parse: parseMot3DClosureTransitionStatus, stage: "closure", kind: "closure", artifacts: 200 },
  { label: "Finalist submission", parse: parseMot3DFinalistSubmissionStatus, stage: "finalist_selection", kind: "submission", candidates: 3 },
  { label: "Finalist transition", parse: parseMot3DFinalistTransitionStatus, stage: "finalist_selection", kind: "finalist_selection", artifacts: 44 },
  { label: "Final Validation submission", parse: parseMot3DFinalValidationSubmissionStatus, stage: "final_validation", kind: "submission", candidates: 1 },
];
function payload(c: typeof cases[number]): Row {
  const r = structuredClone(captured) as Row;
  child(r, "campaign").stage = c.stage;
  const chain = child(r, "closure"); delete r.closure; r[c.kind] = chain;
  if (c.kind === "submission") {
    delete r.transition;
    r.validation = { status: "not_started", expected_candidates_per_family: c.candidates, expected_recoil_seeds_per_candidate: 3 };
    r.local_sync = c.stage === "preliminary_check" ? { status: "not_synchronized" } : { status: "synchronized", receipt_sha256: "a".repeat(64) };
  } else child(r, "validation").expected_result_artifacts = c.artifacts;
  return r;
}
describe("queued family chains retain completed progress", () => {
  it("accepts the genuine C56 Closure response without changing its evidence", () => {
    expect(parseMot3DClosureTransitionStatus(captured)).toEqual(captured);
    expect(captured.scheduler).toMatchObject({ completed_array_tasks: 6, completed_merge_jobs: 1 });
  });
  it.each(cases)("$label accepts bounded unfinished queued progress and still waits", (c) => {
    for (const [a, m] of [[0, 0], [3, 0], [3, 1], [5, 1], [6, 0], [6, 1]]) {
      const r = payload(c); Object.assign(child(r, "scheduler"), { completed_array_tasks: a, completed_merge_jobs: m });
      expect(c.parse(r)).toMatchObject({ next_action: "wait", scheduler: { completed_array_tasks: a, completed_merge_jobs: m } });
    }
  });
  it.each(cases)("$label rejects completed queued chains, impossible bounds and ready claims", (c) => {
    for (const [a, m] of [[6, 2], [7, 1], [-1, 0], [3.5, 0], [0, 3], [true, 0], [false, 0], ["3", 0], [null, 0], [3, true], [3, false], [3, "1"], [3, null]]) {
      const r = payload(c); Object.assign(child(r, "scheduler"), { completed_array_tasks: a, completed_merge_jobs: m }); expect(() => c.parse(r)).toThrow();
    }
    const ready = payload(c); ready.next_action = "review_transition"; expect(() => c.parse(ready)).toThrow();
    const extra = payload(c); extra.unexpected = true; expect(() => c.parse(extra)).toThrow();
    const submitted = payload(c); child(submitted, c.kind).status = "submitted"; expect(() => c.parse(submitted)).toThrow();
  });
  it.each(cases)("$label keeps exact family identity and four-job chain guards", (c) => {
    const r = payload(c); const families = child(r, c.kind).chain as { families: Array<Record<string, unknown>> };
    families.families[1].array_job_id = null; expect(() => c.parse(r)).toThrow();
    const wrong = payload(c); const other = child(wrong, c.kind).chain as { families: Array<Record<string, unknown>> };
    other.families[0].id = "foreign"; expect(() => c.parse(wrong)).toThrow();
  });
});
