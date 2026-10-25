/** Component boundary only: real captured coordinator DTOs pass the real parsers.
 * API transport is mocked; no physical solver, SSH or scheduler runs here.
 */
import { StrictMode } from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import success from "../../../tests/contracts/v1/workflow_api_success.json";
import scientificCapture from "./fixtures/CampaignDetail.readonlyRecovery.v1.json";
import acceptanceCapture from "./fixtures/CampaignDetail.readonlyRecovery.acceptance.v1.json";
const contract = (id: string) =>
  structuredClone(success.cases.find((row) => row.id === id)!.body.data);
function recorded<T>(
  capture: { responses: { parser: string; method: string; value: unknown }[] },
  parser: (value: Record<string, unknown>) => T,
  name: string,
): T {
  const rows = capture.responses.filter(
    (row) => row.parser === name && row.method === "status",
  );
  expect(rows.length, name).toBeGreaterThan(0);
  return parser(structuredClone(rows.at(-1)!.value) as Record<string, unknown>);
}
afterEach(() => vi.unstubAllEnvs());
it.each([
  ["development", scientificCapture, false, "complete"],
  ["development", scientificCapture, false, "running"],
  ["development", scientificCapture, false, "error"],
  ["ui-acceptance", acceptanceCapture, false, "fresh"],
  ["development", scientificCapture, true, "complete"],
  ["ui-acceptance", acceptanceCapture, false, "complete"],
  ["ui-acceptance", acceptanceCapture, true, "complete"],
] as const)(
  "recovers a reloaded local Smoke campaign in %s through every completed stage automatically using only read-only status calls (historical uncertainty %s)",
  async (mode, capture, historicalUnknown, outcome) => {
    vi.stubEnv("MODE", mode);
    vi.resetModules();
    const domain = await import("../api/schema/domain");
    const { CampaignDetail } =
      await import("../features/campaign/CampaignDetail");
    const read = <T,>(
      parser: (value: Record<string, unknown>) => T,
      name: string,
    ) => recorded(capture, parser, name);
    const reads: string[] = [];
    const forbidden = vi.fn(async () => {
      throw new Error("Recovery must never preview, confirm or submit");
    });
    const operation = <T,>(name: string, value: T) => ({
      status: vi.fn(async () => {
        reads.push(name);
        return value;
      }),
      preview: forbidden,
      confirm: forbidden,
      reset: vi.fn(),
    });
    const smoke = read(domain.parseSmokeLifecycle, "parseSmokeLifecycle");
    const campaign = domain.parseCampaign({
      ...contract("campaign-detail"),
      id: smoke.campaign.id,
      name: smoke.campaign.name,
      ...(mode === "ui-acceptance"
        ? {
            kind: "mot_2d_ui_acceptance_v1",
            scientific_role: "acceptance-only",
          }
        : {}),
      path: capture.original_job_file.split("/jobs/")[0],
    });
    expect(campaign.stage).toBe("smoke");
    const lifecycle = operation("Smoke recovery", outcome === "running" ? { ...smoke, lifecycle: "running" as const } : smoke);
    if (outcome === "fresh") {
      const { SmokeLifecycleApiError } = await import("../api/clients/smoke");
      lifecycle.status.mockImplementation(async () => { reads.push("Smoke recovery"); throw new SmokeLifecycleApiError("smoke_not_submitted", "No recorded smoke job"); });
    }
    if (outcome === "error") lifecycle.status.mockImplementation(async () => { reads.push("Smoke recovery"); throw new Error("Controlled disconnected SSH"); });
    const screeningLifecycle = operation(
      "Screening status",
      read(domain.parseScreeningLifecycle, "parseScreeningLifecycle"),
    );
    const refinementSubmission = operation(
      "Refinement chain status",
      read(domain.parseRefinementChainStatus, "parseRefinementChainStatus"),
    );
    const refinementLifecycle = operation(
      "Refinement status",
      read(domain.parseRefinementLifecycle, "parseRefinementLifecycle"),
    );
    const confirmationValue=read(domain.parseConfirmationSubmissionStatus,"parseConfirmationSubmissionStatus");
    const confirmationSubmission = operation("Confirmation submission status", historicalUnknown ? domain.parseConfirmationSubmissionStatus({...confirmationValue,submission:{...confirmationValue.submission,status:"status_unknown"},next_action:"inspect_zeus"}) : confirmationValue);
    const sensitivity = operation(
      "Confirmation results",
      read(domain.parseSensitivityStatus, "parseSensitivityStatus"),
    );
    const sensitivityValue=read(domain.parseSensitivitySubmissionStatus,"parseSensitivitySubmissionStatus");
    const sensitivitySubmission = operation("Sensitivity submission status", historicalUnknown ? domain.parseSensitivitySubmissionStatus({...sensitivityValue,submission:{...sensitivityValue.submission,status:"running"},next_action:"wait"}) : sensitivityValue);
    const production = operation(
      "Sensitivity results",
      read(domain.parseProductionStatus, "parseProductionStatus"),
    );
    const productionSubmission = operation(
      "Production submission status",
      read(
        domain.parseProductionSubmissionStatus,
        "parseProductionSubmissionStatus",
      ),
    );
    const finalization = operation(
      "Final report status",
      read(domain.parseFinalizationStatus, "parseFinalizationStatus"),
    );
    const unused = operation("unexpected status", null);
    const snapshotValue = contract("zeus-snapshot") as unknown as {
      profile: Record<string, unknown>;
      remote: Record<string, unknown>;
    };
    snapshotValue.profile.project_directory =
      snapshotValue.remote.project_directory = capture.remote_project_directory;
    const snapshot = domain.parseZeusSnapshot(snapshotValue);
    render(
      <StrictMode><CampaignDetail
        campaign={campaign}
        zeusSnapshot={snapshot}
        onBack={vi.fn()}
        onConnectZeus={vi.fn()}
        onViewJobs={vi.fn()}
        transfer={unused}
        submission={unused}
        lifecycle={lifecycle}
        screeningSubmission={unused}
        screeningLifecycle={screeningLifecycle}
        refinementSubmission={refinementSubmission}
        refinementLifecycle={refinementLifecycle}
        confirmationSubmission={confirmationSubmission}
        sensitivity={sensitivity}
        sensitivitySubmission={sensitivitySubmission}
        production={production}
        productionSubmission={productionSubmission}
        finalization={finalization}
      /></StrictMode>,
    );
    if (outcome !== "complete") {
      await waitFor(() => expect(lifecycle.status).toHaveBeenCalledOnce());
      if (outcome === "error") await screen.findByText("Controlled disconnected SSH");
      else await waitFor(() => expect(screen.queryByText(/Restoring verified campaign status/)).not.toBeInTheDocument());
      if (outcome === "fresh") expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      expect(reads).toEqual(["Smoke recovery"]);
      expect(screen.queryByRole("heading", { name: "Sealed final results" })).not.toBeInTheDocument();
      expect(screeningLifecycle.status).not.toHaveBeenCalled();
      expect(forbidden).not.toHaveBeenCalled();
      return;
    }
    expect(
      await screen.findByRole("heading", { name: mode === "ui-acceptance" ? "TEST ONLY sealed results" : "Sealed final results" }, { timeout: 5000 }),
    ).toBeVisible();
    expect(within(document.querySelector('section[aria-labelledby="priority-heading"]') as HTMLElement).getByRole("heading",{name:"Final report is ready"})).toBeVisible();
    expect(reads).toEqual([
      "Smoke recovery",
      "Screening status",
      "Refinement chain status",
      "Refinement status",
      "Confirmation submission status",
      "Confirmation results",
      "Sensitivity submission status",
      "Sensitivity results",
      "Production submission status",
      "Final report status",
    ]);
    for (const api of [
      lifecycle,
      screeningLifecycle,
      refinementSubmission,
      refinementLifecycle,
      confirmationSubmission,
      sensitivity,
      sensitivitySubmission,
      production,
      productionSubmission,
      finalization,
    ]) {
      expect(api.status).toHaveBeenCalledExactlyOnceWith(
        campaign.id,
        snapshot.profile,
      );
    }
    const timeline=within(document.querySelector('section[aria-labelledby="timeline-heading"]') as HTMLElement);
    expect(timeline.getAllByText("Outputs verified on Zeus")).toHaveLength(6);
    expect(timeline.queryByText(/0 of 1/)).not.toBeInTheDocument();
    expect(forbidden).not.toHaveBeenCalled();
    expect(unused.status).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("button", { name: "Finalize campaign" }),
    ).not.toBeInTheDocument();

  },
);
