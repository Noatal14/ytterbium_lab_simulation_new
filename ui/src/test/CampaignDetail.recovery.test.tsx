/** Component boundary only: real captured coordinator DTOs pass the real parsers.
 * API transport is mocked; no physical solver, SSH or scheduler runs here.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
  ["development", scientificCapture],
  ["ui-acceptance", acceptanceCapture],
] as const)(
  "recovers a reloaded local Smoke campaign in %s through every completed stage using only read-only status calls",
  async (mode, capture) => {
    vi.stubEnv("MODE", mode);
    vi.resetModules();
    const domain = await import("../api/schema/domain");
    const { CampaignDetail } =
      await import("../features/campaign/CampaignDetail");
    const read = <T,>(
      parser: (value: Record<string, unknown>) => T,
      name: string,
    ) => recorded(capture, parser, name);
    const user = userEvent.setup();
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
    const lifecycle = operation("Smoke recovery", smoke);
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
    const confirmationSubmission = operation(
      "Confirmation submission status",
      read(
        domain.parseConfirmationSubmissionStatus,
        "parseConfirmationSubmissionStatus",
      ),
    );
    const sensitivity = operation(
      "Confirmation results",
      read(domain.parseSensitivityStatus, "parseSensitivityStatus"),
    );
    const sensitivitySubmission = operation(
      "Sensitivity submission status",
      read(
        domain.parseSensitivitySubmissionStatus,
        "parseSensitivitySubmissionStatus",
      ),
    );
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
      <CampaignDetail
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
      />,
    );
    async function click(label: string, scope?: string) {
      if (scope)
        await waitFor(() =>
          expect(
            document.querySelector(`section[aria-labelledby="${scope}"]`),
          ).not.toBeNull(),
        );
      const root = scope
        ? within(
            document.querySelector(
              `section[aria-labelledby="${scope}"]`,
            ) as HTMLElement,
          )
        : screen;
      await user.click(await root.findByRole("button", { name: label }));
    }
    await click("Recover submitted Zeus campaign");
    await click("Check Screening status");
    await click("Check chain status");
    await click("Check Refinement status");
    await click("Check Zeus status", "confirmation-submit-heading");
    await click("Check Confirmation results");
    await click("Check Zeus status", "sensitivity-heading");
    await click("Check Sensitivity results");
    await click("Check Zeus status", "production-heading");
    await click("Check Production results");
    expect(
      await screen.findByRole("heading", { name: "Sealed final results" }),
    ).toBeVisible();
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
    expect(forbidden).not.toHaveBeenCalled();
    expect(unused.status).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("button", { name: "Finalize campaign" }),
    ).not.toBeInTheDocument();
  },
);
