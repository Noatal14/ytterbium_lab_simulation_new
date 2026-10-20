/** A fixed isolated target, never an arbitrary remote path. */
export function zeusTestMode(): boolean { return import.meta.env.MODE === "zeus-test"; }
export function campaignAcceptanceMode(): boolean { return import.meta.env.MODE === "ui-acceptance"; }
export function zeusProjectDirectory(username: string): string {
  return `/home/${username}/${campaignAcceptanceMode() ? "ytterbium_lab_simulation_ui_acceptance" : zeusTestMode() ? "ytterbium_lab_simulation_ui_test" : "ytterbium_lab_simulation_new"}`;
}

export function isCampaignProjectDirectory(value: unknown): boolean {
  if (typeof value !== "string") return false;
  const match = /^\/home\/([A-Za-z][A-Za-z0-9._-]{0,31})\/[^/]+$/.exec(value);
  return match !== null && value === zeusProjectDirectory(match[1]);
}
