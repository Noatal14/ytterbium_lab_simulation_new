/** A fixed isolated target, never an arbitrary remote path. */
export function zeusTestMode(): boolean { return import.meta.env.MODE === "zeus-test"; }
export function campaignAcceptanceMode(): boolean { return import.meta.env.MODE === "ui-acceptance"; }
export function zeusProjectDirectory(username: string): string {
  const configured = import.meta.env.VITE_ZEUS_CHECKOUT;
  if (configured && !["ytterbium_lab_simulation_new", "ytterbium_lab_simulation_ui_test"].includes(configured)) {
    throw new Error("Unsupported Zeus checkout configuration.");
  }
  const checkout = campaignAcceptanceMode() ? "ytterbium_lab_simulation_ui_acceptance"
    : zeusTestMode() ? "ytterbium_lab_simulation_ui_test"
    : configured || "ytterbium_lab_simulation_new";
  return `/home/${username}/${checkout}`;
}

export function isCampaignProjectDirectory(value: unknown): boolean {
  if (typeof value !== "string") return false;
  const match = /^\/home\/([A-Za-z][A-Za-z0-9._-]{0,31})\/[^/]+$/.exec(value);
  return match !== null && value === zeusProjectDirectory(match[1]);
}

export function campaignExecutionCheckout(): string | undefined {
  const project = zeusProjectDirectory("deployment");
  return project.endsWith("/ytterbium_lab_simulation_ui_test")
    ? "ytterbium_lab_simulation_ui_test" : undefined;
}
