import { useMemo } from "react";
import { closureTransitionIsUncertain, type Mot3DClosureTransitionApi, type Mot3DClosureTransitionStatus } from "../../../api/clients/mot3dClosureTransition";
import type { ZeusSnapshot } from "../../../api/schema/domain";
import { useGuardedStageController } from "../shared/useGuardedStageController";

const apiIds = new WeakMap<object, number>();
let nextApiId = 1;
const apiId = (api: object) => { const current = apiIds.get(api); if (current) return current; const created = nextApiId++; apiIds.set(api, created); return created; };

export function useMot3DClosureTransitionController({ campaignId, snapshot, enabled, api }: { campaignId: string; snapshot: ZeusSnapshot | null; enabled: boolean; api: Mot3DClosureTransitionApi }) {
  const operations = useMemo(() => ({
    status: () => api.status(campaignId, snapshot!.profile),
    preview: () => api.preview(campaignId, snapshot!.profile),
    confirm: (preview: Awaited<ReturnType<Mot3DClosureTransitionApi["preview"]>>) => api.confirm(preview.preview_token),
    reset: () => api.reset(),
  }), [api, campaignId, snapshot]);
  const stateForStatus = (status: Mot3DClosureTransitionStatus) =>
    ["review_transition", "synchronize_results"].includes(status.next_action) ? "ready" as const
      : status.next_action === "open_finalist_selection" ? "success" as const
        : status.next_action === "inspect_zeus" ? "blocked" as const : "idle" as const;
  return useGuardedStageController({
    enabled: enabled && Boolean(snapshot),
    contextKey: `${campaignId}:${snapshot?.profile.host ?? ""}:${snapshot?.profile.authentication ?? ""}:${snapshot?.profile.username ?? ""}:${snapshot?.profile.project_directory ?? ""}:${enabled}:${apiId(api)}`,
    operations,
    stateForStatus,
    canPreview: (status) => ["review_transition", "synchronize_results"].includes(status?.next_action ?? ""),
    isUnknownConfirmation: closureTransitionIsUncertain,
  });
}
