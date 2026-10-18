/** A fixed isolated target, never an arbitrary remote path. */
export function zeusTestMode(): boolean { return import.meta.env.MODE === "zeus-test"; }
export function zeusProjectDirectory(username: string): string {
  return `/home/${username}/${zeusTestMode() ? "ytterbium_lab_simulation_ui_test" : "ytterbium_lab_simulation_new"}`;
}
