import deployments from "../../../workflow_api/specifications/deployments_v1.json";

/** Normal launches use the personal-account team deployment. Tests stay explicit. */
export function zeusTestMode(): boolean { return import.meta.env.MODE === "zeus-test"; }
export function campaignAcceptanceMode(): boolean { return import.meta.env.MODE === "ui-acceptance"; }
function checkout(): string {
  const configured = import.meta.env.VITE_ZEUS_CHECKOUT;
  if (configured && ![deployments.team.checkout, deployments.historical.checkout, deployments.test.checkout].includes(configured)) {
    throw new Error("Unsupported Zeus checkout configuration.");
  }
  return campaignAcceptanceMode() ? deployments.acceptance.checkout
    : zeusTestMode() ? deployments.test.checkout
    : configured || deployments.team.checkout;
}
export function zeusProjectDirectory(username: string): string {
  return `/home/${username}/${checkout()}`;
}
export function isCampaignProjectDirectory(value: unknown): boolean {
  if (typeof value !== "string") return false;
  const match = /^\/home\/([A-Za-z][A-Za-z0-9._-]{0,31})\/[^/]+$/.exec(value);
  return match !== null && value === zeusProjectDirectory(match[1]);
}
export function campaignExecutionCheckout(): string | undefined {
  const selected = checkout();
  return [deployments.team.checkout, deployments.test.checkout].includes(selected) ? selected : undefined;
}
