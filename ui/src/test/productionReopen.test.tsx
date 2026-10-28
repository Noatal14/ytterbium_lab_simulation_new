import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import success from "./teamContractFixture";
import { parseFinalizationResult, parseFinalizationStatus, parseProductionSubmissionStatus } from "../api/schema/domain";
import { ProductionStage } from "../features/campaign/ProductionStage";
import type { useProductionController } from "../features/campaign/controllers/useProductionController";
const data = (id: string) => structuredClone(success.cases.find(row => row.id === id)!.body.data) as Record<string, unknown>;
function completeStatus() {
  const value = data("finalization-status");
  value.campaign = { ...(value.campaign as object), stage: "complete" };
  const production = value.production as Record<string, unknown>;
  production.status = "campaign_complete";
  value.next_action = "none";
  value.results = data("finalization-confirm").results;
  return value;
}
afterEach(() => vi.unstubAllEnvs());
describe("reopening sealed final results", () => {
  it("keeps valid zero-capture results distinct from missing output artifacts", () => {
    const value = completeStatus();
    const row = (value.results as Record<string, unknown>[])[0];
    row.total_survivors = 0;
    const prediction = row.prediction as Record<string, unknown>;
    for (const key of ["simulated_captured_atoms", "pooled_conditional_efficiency", "expected_captured_atoms", "predicted_95_half_width_fraction", "predicted_95_half_width_percentage_points", "binomial_mean_variance", "empirical_between_ensemble_mean_variance", "selected_mean_variance", "future_counting_variance"]) prediction[key] = 0;
    prediction.predicted_95_interval_fraction = [0, 0];
    prediction.predicted_95_captured_atoms_interval = [0, 0];
    const status = parseFinalizationStatus(value);
    expect(status.validation).toMatchObject({ status: "valid", completed_ensembles: 20, expected_ensembles: 20 });
    expect(status.results?.[0].total_input).toBeGreaterThan(0);
    const noop = vi.fn();
    const operation = { lastObservation: null, state: "idle", status: null, preview: null, result: null, error: "", refresh: noop, review: noop, confirm: noop, reset: noop };
    const flow = { collection: operation, preparation: operation, submission: { ...operation, state: "success", status: parseProductionSubmissionStatus(data("production-submit-status")) }, finalization: { ...operation, state: "success", status } } as ReturnType<typeof useProductionController>;
    render(<ProductionStage visible flow={flow} onViewJobs={noop} />);
    expect(screen.getByRole("heading", { name: "Sealed final results" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "0.000% conditional capture" })).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Finalize campaign" })).not.toBeInTheDocument();
    expect(noop).not.toHaveBeenCalled();
  });
  it.each([["development", "eligible_as_3d_campaign_input", "acceptance_only"], ["ui-acceptance", "acceptance_only", "eligible_as_3d_campaign_input"]])("reopens %s results only within the authenticated suitability boundary", (mode, allowed, forbidden) => {
    vi.stubEnv("MODE", mode);
    const value = completeStatus();
    const row = (value.results as Record<string, unknown>[])[0];
    row.output_suitability = allowed;
    expect(parseFinalizationStatus(value).results?.[0].output_suitability).toBe(allowed);
    row.output_suitability = forbidden;
    expect(() => parseFinalizationStatus(value)).toThrow();
  });
  it("requires complete, strict, mode-appropriate report rows on the read-only status", () => {
    const value = completeStatus();
    expect(parseFinalizationStatus(value).results).toHaveLength(1);
    for (const results of [undefined, [], [...value.results as unknown[], ...value.results as unknown[]], [{ ...(value.results as object[])[0], output_suitability: "acceptance_only" }]]) {
      const altered = { ...value, results };
      if (results === undefined) delete altered.results;
      expect(() => parseFinalizationStatus(altered)).toThrow();
    }
    expect(() => parseFinalizationStatus({ ...data("finalization-status"), results: value.results })).toThrow();
  });
  it("renders freshly verified completed results without another preview or confirm and retires them on error", () => {
    const noop = vi.fn();
    const operation = { lastObservation: null, state: "idle", status: null, preview: null, result: null, error: "", refresh: noop, review: noop, confirm: noop, reset: noop };
    const flow = {
      collection: operation, preparation: operation,
      submission: { ...operation, state: "success", status: parseProductionSubmissionStatus(data("production-submit-status")) },
      finalization: { ...operation, state: "success", status: parseFinalizationStatus(completeStatus()) },
    } as ReturnType<typeof useProductionController>;
    const view = render(<ProductionStage visible flow={flow} onViewJobs={noop} />);
    expect(screen.getByRole("heading", { name: "Sealed final results" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Finalize campaign" })).not.toBeInTheDocument();
    expect(noop).not.toHaveBeenCalled();
    view.rerender(<ProductionStage visible flow={{ ...flow, finalization: { ...flow.finalization, state: "idle", error: "Disconnected; results could not be reverified." } }} onViewJobs={noop} />);
    expect(screen.queryByRole("heading", { name: "Sealed final results" })).not.toBeInTheDocument();
    expect(screen.getByText("Disconnected; results could not be reverified.")).toBeVisible();
    expect(noop).not.toHaveBeenCalled();
  });
});

it("retires a retained successful result when the next artifact observation is invalid", () => {
  const noop=vi.fn();
  const operation={lastObservation:null,state:"idle",status:null,preview:null,result:null,error:"",refresh:noop,review:noop,confirm:noop,reset:noop};
  const flow={collection:operation,preparation:operation,submission:{...operation,state:"success",status:parseProductionSubmissionStatus(data("production-submit-status"))},finalization:{...operation,state:"success",result:parseFinalizationResult(data("finalization-confirm"))}} as ReturnType<typeof useProductionController>;
  const view=render(<ProductionStage visible flow={flow} onViewJobs={noop}/>);
  expect(screen.getByRole("heading",{name:"Sealed final results"})).toBeVisible();
  const invalid=data("finalization-status");(invalid.production as Record<string,unknown>).status="outputs_invalid";invalid.validation={status:"invalid",completed_ensembles:0,expected_ensembles:20};invalid.next_action="wait";
  view.rerender(<ProductionStage visible flow={{...flow,finalization:{...flow.finalization,state:"terminal",status:parseFinalizationStatus(invalid)}}} onViewJobs={noop}/>);
  expect(screen.queryByRole("heading",{name:"Sealed final results"})).not.toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveTextContent("Sealed Production outputs failed validation");
  expect(screen.getByRole("button",{name:"Check current status"})).toBeEnabled();
  expect(noop).not.toHaveBeenCalled();
});
