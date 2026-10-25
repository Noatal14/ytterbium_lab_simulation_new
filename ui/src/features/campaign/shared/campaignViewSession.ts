// View context only: never persist snapshots, credentials, previews or job actions.
const key = "mot-ui.open-2d-view.v1";
export type CampaignView = { id: string; username: string; project_directory: string };
export function readCampaignView(): CampaignView | null {
  try {
    const value = JSON.parse(sessionStorage.getItem(key) ?? "null");
    if (!value || typeof value !== "object" || Array.isArray(value) || typeof value.id !== "string" || Object.keys(value).sort().join() !== "id,project_directory,username" ||
      !/^mot_2d-[a-zA-Z0-9_-]{1,100}$/.test(value.id) ||
      typeof value.username !== "string" || !/^[a-z][a-z0-9._-]{0,63}$/.test(value.username) ||
      typeof value.project_directory !== "string" || !value.project_directory.startsWith(`/home/${value.username}/`) ||
      value.project_directory.length > 1024) return null;
    return value;
  } catch { return null; }
}
export function rememberCampaignView(view: CampaignView | null) {
  try {
    if (view) sessionStorage.setItem(key, JSON.stringify(view));
    else sessionStorage.removeItem(key);
  } catch { /* Storage can be disabled; explicit connection/open still works. */ }
}
