import { useMemo } from "react";
import {
  finalValidationTransitionIsUncertain,
  type Mot3DFinalValidationTransitionApi,
} from "../../../api/clients/mot3dFinalValidationTransition";
import type { ZeusSnapshot } from "../../../api/schema/domain";
import { useGuardedStageController } from "../shared/useGuardedStageController";
const ids = new WeakMap<object, number>();
let next = 1;
const apiId = (api: object) => {
  const old = ids.get(api);
  if (old) return old;
  const value = next++;
  ids.set(api, value);
  return value;
};
export function useMot3DFinalValidationTransitionController({
  campaignId,
  snapshot,
  enabled,
  api,
}: {
  campaignId: string;
  snapshot: ZeusSnapshot | null;
  enabled: boolean;
  api: Mot3DFinalValidationTransitionApi;
}) {
  const p = snapshot?.profile,
    commit = snapshot?.remote?.git_commit,
    operations = useMemo(
      () => ({
        status: () => api.status(campaignId, p!),
        preview: () => api.preview(campaignId, p!, commit!),
        confirm: (
          v: Awaited<ReturnType<Mot3DFinalValidationTransitionApi["preview"]>>,
        ) => api.confirm(v.preview_token),
        reset: () => api.reset(),
      }),
      [api, campaignId, p, commit],
    );
  return useGuardedStageController({
    enabled: enabled && Boolean(p && commit),
    contextKey: `${campaignId}:${enabled}:${p?.host ?? ""}:${p?.authentication ?? ""}:${p?.username ?? ""}:${p?.project_directory ?? ""}:${commit ?? ""}:${apiId(api)}`,
    operations,
    stateForStatus: (s) =>
      ["review_transition", "synchronize_results"].includes(s.next_action)
        ? "ready"
        : s.next_action === "open_final_validation"
          ? "success"
          : s.next_action === "inspect_zeus"
            ? "blocked"
            : "idle",
    canPreview: (s) =>
      ["review_transition", "synchronize_results"].includes(
        s?.next_action ?? "",
      ),
    isUnknownConfirmation: finalValidationTransitionIsUncertain,
  });
}
