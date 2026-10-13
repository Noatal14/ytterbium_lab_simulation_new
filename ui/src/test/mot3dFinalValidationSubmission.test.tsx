import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import success from "../../../tests/contracts/v1/workflow_api_success.json";
import {
  parseMot3DFinalValidationSubmissionPreview,
  parseMot3DFinalValidationSubmissionResult,
  parseMot3DFinalValidationSubmissionStatus,
} from "../api/clients/mot3dFinalValidationSubmission";
import { Mot3DCampaignFlow } from "../features/campaign/Mot3DCampaignFlow";
const data = (id: string) =>
  structuredClone(
    (
      success.cases.find((x) => x.id === id)!.body as {
        data: Record<string, unknown>;
      }
    ).data,
  );
const profile = {
  host: "zeus.technion.ac.il" as const,
  username: "tal.noa",
  project_directory: "/home/tal.noa/ytterbium_lab_simulation_new",
  authentication: "ssh-key-or-agent" as const,
};
const status = () =>
    parseMot3DFinalValidationSubmissionStatus(
      data("mot3d-final-validation-status"),
    ),
  preview = () =>
    parseMot3DFinalValidationSubmissionPreview(
      data("mot3d-final-validation-preview"),
      { campaignId: "campaign-id", profile },
    ),
  result = () =>
    parseMot3DFinalValidationSubmissionResult(
      data("mot3d-final-validation-confirm"),
      "campaign-id",
    );
const flow = (x: Record<string, unknown>) =>
  ({
    phase: "idle",
    status: null,
    preview: null,
    result: null,
    error: "",
    errorPhase: null,
    refresh: vi.fn(),
    review: vi.fn(),
    confirm: vi.fn(),
    reset: vi.fn(),
    ...x,
  }) as never;
const base = {
  stage: "final_validation",
  connected: true,
  discovery: {} as never,
  transition: {} as never,
  preliminary: {} as never,
  onConnectZeus: vi.fn(),
  onViewJobs: vi.fn(),
};
describe("Final Validation submission", () => {
  it("pins the native scientific and effects contract", () => {
    expect(status().validation.expected_candidates_per_family).toBe(1);
    expect(preview().science.dt_s).toBe(0.625e-6);
    expect(result().stage).toBe("final_validation");
    for (const mutate of [
      (v: any) => (v.science.dt_s = 1e-5),
      (v: any) => (v.science.input_ensembles = 19),
      (v: any) => (v.resources.merge.memory_gb = 4),
      (v: any) => (v.effects.submit_later_stages = true),
    ]) {
      const v = data("mot3d-final-validation-preview");
      mutate(v);
      expect(() =>
        parseMot3DFinalValidationSubmissionPreview(v, {
          campaignId: "campaign-id",
          profile,
        }),
      ).toThrow();
    }
  });
  it("renders explicit review and distinguishes scheduler completion", () => {
    const view = render(
      <Mot3DCampaignFlow
        {...base}
        finalValidation={flow({
          phase: "review",
          preview: preview(),
          status: status(),
        })}
      />,
    );
    expect(
      screen.getByRole("heading", { name: "Submit Final Validation" }),
    ).toHaveFocus();
    expect(screen.getByText("0.625 µs")).toBeVisible();
    const done = status();
    done.submission.status = "completed_success_unvalidated";
    view.rerender(
      <Mot3DCampaignFlow {...base} finalValidation={flow({ status: done })} />,
    );
    expect(screen.getByText(/not yet scientifically validated/)).toBeVisible();
    expect(screen.getByRole("status")).toHaveFocus();
    view.rerender(
      <Mot3DCampaignFlow
        {...base}
        finalValidation={flow({ phase: "blocked", error: "Outcome unknown" })}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(/Do not submit again/i);
    expect(screen.getByRole("alert")).toHaveFocus();
  });

  it("moves focus to the submitted success panel", () => {
    render(
      <Mot3DCampaignFlow
        {...base}
        finalValidation={flow({ phase: "success", result: result() })}
      />,
    );
    expect(screen.getByRole("status")).toHaveFocus();
  });
});
