import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import success from "./teamContractFixture";
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
      if (suitability === "acceptance_only") {
        expect(retained).not.toHaveTextContent("eligible as validated 3D campaign input");
        expect(screen.queryByText(/unbiased/i)).not.toBeInTheDocument();
        expect(screen.queryByText("Scientific qualifications")).not.toBeInTheDocument();
        expect(screen.getByText("Acceptance diagnostics")).toBeVisible();
        expect(screen.getByText(/TEST ONLY diagnostics/)).toBeVisible();
      } else {
        expect(screen.getByText("Scientific qualifications")).toBeVisible();
        expect(screen.getAllByText(/unbiased/).length).toBeGreaterThan(0);
        expect(screen.queryByText("Acceptance diagnostics")).not.toBeInTheDocument();
      }
      expect(screen.getByRole("heading", { name: "10.000% conditional capture" })).toBeVisible();
      expect(screen.getByText("95% cluster-aware interval: 9.000%–11.000%")).toBeVisible();
      expect(screen.getByText(targetMet ? "Met" : "Not met")).toBeVisible();
      expect(screen.getByText("robust operating region not established")).toBeVisible();
      if (!targetMet) expect(screen.getByText("target 95 prediction half width not met")).toBeVisible();
      expect(noop).not.toHaveBeenCalled();
    };
    check();
    expect(screen.getByRole("heading", { name: suitability === "acceptance_only" ? "Finalize TEST ONLY results" : "Finalize this campaign" })).toBeVisible();
    // Rendering follows already-parsed authoritative rows, even if the frontend mode changes.
    vi.stubEnv("MODE", mode === "development" ? "ui-acceptance" : "development");
    view.rerender(<ProductionStage visible flow={flow} onViewJobs={noop} />);
    check();
    vi.stubEnv("MODE", mode);
    const complete = data("finalization-status");
    complete.campaign = { ...(complete.campaign as object), stage: "complete" };
    (complete.production as Record<string, unknown>).status = "campaign_complete";
    complete.next_action = "none";
    complete.results = preview.results;
    view.rerender(<ProductionStage visible flow={{ ...flow, finalization: { ...operation, state: "success", status: parseFinalizationStatus(complete) } }} onViewJobs={noop} />);
    expect(screen.getByRole("heading", { name: suitability === "acceptance_only" ? "TEST ONLY sealed results" : "Sealed final results" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Finalize campaign" })).not.toBeInTheDocument();
    check();
  });
  it("does not make a global scientific claim for defensively mixed parsed rows", () => {
    vi.stubEnv("MODE", "development");
    const scientific = parseFinalizationPreview(data("finalization-preview"));
    vi.stubEnv("MODE", "ui-acceptance");
    const acceptanceRaw = data("finalization-preview");
    const acceptanceRow = (acceptanceRaw.results as Record<string, unknown>[])[0];
    acceptanceRow.output_suitability = "acceptance_only";
    acceptanceRow.s0 = 1.4;
    (acceptanceRow.recommended_parameters as Record<string, unknown>).s0 = 1.4;
    (acceptanceRaw.campaign as Record<string, unknown>).s0_values = [1.4];
    (acceptanceRaw.artifacts as Record<string, unknown>).create = ["final_report.json", "production/s0_1p400000/summary.json"];
    const acceptance = parseFinalizationPreview(acceptanceRaw);
    // Each input row passed its real parser. This is a defensive renderer case;
    // the unchanged API contract still rejects mixed suitability in one response.
    const mixed = { ...scientific, results: [...scientific.results, ...acceptance.results] };
    expect(() => parseFinalizationPreview(mixed as unknown as Record<string, unknown>)).toThrow("Invalid finalization preview");
    const noop = vi.fn(), operation = { lastObservation: null, state: "idle", status: null, preview: null, result: null, error: "", refresh: noop, review: noop, confirm: noop, reset: noop };
    const flow = { preparation: operation, submission: { ...operation, state: "success" }, finalization: { ...operation, state: "review", preview: mixed } } as ReturnType<typeof useProductionController>;
    const view = render(<ProductionStage visible flow={flow} onViewJobs={noop} />);
    expect(screen.getByRole("heading", { name: "Finalize results including TEST ONLY outputs" })).toBeVisible();
    expect(screen.queryByText(/unbiased/)).not.toBeInTheDocument();
    const rows = screen.getAllByRole("article");
    expect(within(rows[0]).getByText("Scientific qualifications")).toBeVisible();
    expect(within(rows[0]).getByText(/eligible as validated 3D campaign input/)).toBeVisible();
    expect(within(rows[1]).getByText("Acceptance diagnostics")).toBeVisible();
    expect(within(rows[1]).getByText(/not eligible for scientific use/)).toBeVisible();
    view.rerender(<ProductionStage visible flow={{ ...flow, finalization: { ...operation, state: "success", result: { status: "campaign_complete", campaign_id: scientific.campaign.id, stage: "complete", results: mixed.results, submitted_to_zeus: false, simulation_started: false, local_sync: { status: "not_synchronized" } } } }} onViewJobs={noop} />);
    expect(screen.getByRole("heading", { name: "Sealed results — includes TEST ONLY outputs" })).toBeVisible();
    expect(screen.getByText(/no combined scientific performance claim is made/)).toBeVisible();
    expect(screen.queryByText(/unbiased/)).not.toBeInTheDocument();
    expect(noop).not.toHaveBeenCalled();
  });

  it.each(["diagnostic_only", "discarded"])("does not invent support for unsupported %s final campaign rows", unsupported => {
    const preview = data("finalization-preview");
    const row = (preview.results as Record<string, unknown>[])[0];
    if (unsupported === "diagnostic_only") row.output_suitability = unsupported;
    else row.retention = unsupported;
    expect(() => parseFinalizationPreview(preview)).toThrow("Invalid finalization preview");
  });
});
