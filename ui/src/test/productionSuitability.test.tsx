import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import success from "../../../tests/contracts/v1/workflow_api_success.json";
import { parseFinalizationPreview, parseFinalizationStatus, parseProductionSubmissionStatus } from "../api/schema/domain";
import { ProductionStage } from "../features/campaign/ProductionStage";
import type { useProductionController } from "../features/campaign/controllers/useProductionController";
const data = (id: string) => structuredClone(success.cases.find(row => row.id === id)!.body.data) as Record<string, unknown>;
afterEach(() => vi.unstubAllEnvs());
describe("authoritative retained-output suitability", () => {
  it.each([
    ["development", "eligible_as_3d_campaign_input", true],
    ["development", "eligible_as_3d_campaign_input", false],
    ["ui-acceptance", "acceptance_only", true],
    ["ui-acceptance", "acceptance_only", false],
  ] as const)("renders %s suitability with target uncertainty %s in review and after reopen", (mode, suitability, targetMet) => {
    vi.stubEnv("MODE", mode);
    const preview = data("finalization-preview");
    const row = (preview.results as Record<string, unknown>[])[0];
    row.output_suitability = suitability;
    row.target_uncertainty_passes = targetMet;
    row.warnings = ["robust_operating_region_not_established", "epsilon_near_optimality_not_established", ...(!targetMet ? ["target_95_prediction_half_width_not_met"] : [])];
    const parsedPreview = parseFinalizationPreview(preview);
    const noop = vi.fn();
    const operation = { lastObservation: null, state: "idle", status: null, preview: null, result: null, error: "", refresh: noop, review: noop, confirm: noop, reset: noop };
    const flow = {
      preparation: operation,
      submission: { ...operation, state: "success", status: parseProductionSubmissionStatus(data("production-submit-status")) },
      finalization: { ...operation, state: "review", preview: parsedPreview },
    } as ReturnType<typeof useProductionController>;
    const view = render(<ProductionStage visible flow={flow} onViewJobs={noop} />);
    const check = () => {
      const retained = screen.getByText("Retained outputs:").parentElement!;
      expect(retained).toHaveTextContent(suitability === "acceptance_only" ? "TEST ONLY acceptance testing; not eligible for scientific use." : "eligible as validated 3D campaign input.");
      if (suitability === "acceptance_only") expect(retained).not.toHaveTextContent("eligible as validated 3D campaign input");
      expect(screen.getByText(targetMet ? "Met" : "Not met")).toBeVisible();
      expect(screen.getByText("robust operating region not established")).toBeVisible();
      if (!targetMet) expect(screen.getByText("target 95 prediction half width not met")).toBeVisible();
      expect(noop).not.toHaveBeenCalled();
    };
    check();
    const complete = data("finalization-status");
    complete.campaign = { ...(complete.campaign as object), stage: "complete" };
    (complete.production as Record<string, unknown>).status = "campaign_complete";
    complete.next_action = "none";
    complete.results = preview.results;
    view.rerender(<ProductionStage visible flow={{ ...flow, finalization: { ...operation, state: "success", status: parseFinalizationStatus(complete) } }} onViewJobs={noop} />);
    expect(screen.getByRole("heading", { name: "Sealed final results" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Finalize campaign" })).not.toBeInTheDocument();
    check();
  });
  it.each(["diagnostic_only", "discarded"])("does not invent support for unsupported %s final campaign rows", unsupported => {
    const preview = data("finalization-preview");
    const row = (preview.results as Record<string, unknown>[])[0];
    if (unsupported === "diagnostic_only") row.output_suitability = unsupported;
    else row.retention = unsupported;
    expect(() => parseFinalizationPreview(preview)).toThrow("Invalid finalization preview");
  });
});
