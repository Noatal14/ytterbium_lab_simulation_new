import { FINALIST_TRANSITION } from "../../../api/clients/mot3dTransitionValidation";
import { useMemo } from "react";
import { finalistTransitionIsUncertain, type Mot3DFinalistTransitionApi, type Mot3DFinalistTransitionStatus } from "../../../api/clients/mot3dFinalistTransition";
import type { ZeusSnapshot } from "../../../api/schema/domain";
import { useGuardedStageController } from "../shared/useGuardedStageController";

const apiIds = new WeakMap<object, number>();
let nextApiId = 1;
const apiId = (api: object) => { const current = apiIds.get(api); if (current) return current; const created = nextApiId++; apiIds.set(api, created); return created; };

export function useMot3DFinalistTransitionController({ campaignId, snapshot, enabled, api }: { campaignId: string; snapshot: ZeusSnapshot | null; enabled: boolean; api: Mot3DFinalistTransitionApi }) {
  const operations = useMemo(() => ({
    status: () => api.status(campaignId, snapshot!.profile),
    preview: () => api.preview(campaignId, snapshot!.profile),
    confirm: (preview: Awaited<ReturnType<Mot3DFinalistTransitionApi["preview"]>>) => api.confirm(preview.preview_token),
    reset: () => api.reset(),
  }), [api, campaignId, snapshot]);
  const stateForStatus = (status: Mot3DFinalistTransitionStatus) =>
    ["review_transition", "synchronize_results"].includes(status.next_action) ? "ready" as const
      : status.next_action === FINALIST_TRANSITION.openAction ? "success" as const
        : status.next_action === "inspect_zeus" ? "blocked" as const : "idle" as const;
  return useGuardedStageController({
    enabled: enabled && Boolean(snapshot),
    contextKey: `${campaignId}:${snapshot?.profile.host ?? ""}:${snapshot?.profile.authentication ?? ""}:${snapshot?.profile.username ?? ""}:${snapshot?.profile.project_directory ?? ""}:${enabled}:${apiId(api)}`,
    operations,
    stateForStatus,
    canPreview: (status) => ["review_transition", "synchronize_results"].includes(status?.next_action ?? ""),
    isUnknownConfirmation: finalistTransitionIsUncertain,
  });
}
