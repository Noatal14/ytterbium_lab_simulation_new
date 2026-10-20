import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import success from "../../../tests/contracts/v1/workflow_api_success.json";
import { parseFinalizationStatus, parseProductionSubmissionStatus } from "../api/schema/domain";
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
    const operation = { state: "idle", status: null, preview: null, result: null, error: "", refresh: noop, review: noop, confirm: noop, reset: noop };
    const flow = {
      preparation: operation,
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
