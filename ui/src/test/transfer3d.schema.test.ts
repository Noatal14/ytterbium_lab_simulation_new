import { afterEach, expect, it, vi } from "vitest";
import { parseTransferPreview, parseTransferResult } from "../api/schema/domain";
afterEach(() => vi.unstubAllEnvs());
function fixture(mode: string) {
  vi.stubEnv("MODE", mode);
  const project = `/home/tal.noa/ytterbium_lab_simulation_${mode === "ui-acceptance" ? "ui_acceptance" : "new"}`;
  const path = `data/optimization/mot_3d/${mode === "ui-acceptance" ? "ui_acceptance/" : ""}TESTONLY_3D_transfer`;
  return {preview_token: "review", expires_in_seconds: 300, campaign: {id: "mot_3d-id", family: "mot_3d", name: "3D transfer", path, git_commit: "a".repeat(40)}, destination: {host: "zeus.technion.ac.il", project_directory: project, campaign_directory: `${project}/${path}`}, artifacts: {ensemble_count: 20, total_count: 52, missing_count: 10, identical_count: 42, total_bytes: 1000, missing_bytes: 100}, effects: {copy_missing_only: true, overwrite_existing: false, submit_jobs: false, run_simulation: false}};
}
it.each(["development", "ui-acceptance"])("parses the exact 3D transfer registry in %s", mode => {
  const value = fixture(mode);
  expect(parseTransferPreview(value).artifacts.total_count).toBe(52);
  expect(parseTransferResult({status: "prepared", campaign_id: value.campaign.id, destination: value.destination.campaign_directory, transferred_count: 10, reused_identical_count: 42, bytes_transferred: 100, submitted_to_zeus: false, simulation_started: false}).transferred_count).toBe(10);
});
it.each(["family", "ensemble_count", "total_count", "missing_count", "traversal", "cross_mode", "destination", "submit"])("rejects mismatched 3D transfer %s", attack => {
  const value = fixture("ui-acceptance");
  if (attack === "family") value.campaign.family = "mot_2d";
  if (attack === "ensemble_count") value.artifacts.ensemble_count = 35;
  if (attack === "total_count") value.artifacts.total_count = 72;
  if (attack === "missing_count") value.artifacts.missing_count = 11;
  if (attack === "traversal") value.campaign.path += "/../foreign";
  if (attack === "cross_mode") value.campaign.path = value.campaign.path.replace("ui_acceptance/", "");
  if (attack === "destination") value.destination.campaign_directory += "_other";
  if (attack === "submit") value.effects.submit_jobs = true;
  expect(() => parseTransferPreview(value)).toThrow();
});
it("rejects a 2D-sized result and production destination for a 3D acceptance transfer", () => {
  const value = fixture("ui-acceptance");
  const result = {status: "prepared", campaign_id: value.campaign.id, destination: value.destination.campaign_directory, transferred_count: 10, reused_identical_count: 62, bytes_transferred: 100, submitted_to_zeus: false, simulation_started: false};
  expect(() => parseTransferResult(result)).toThrow();
  result.reused_identical_count = 42;
  result.destination = result.destination.replace("ytterbium_lab_simulation_ui_acceptance", "ytterbium_lab_simulation_new");
  expect(() => parseTransferResult(result)).toThrow();
});
