import { useMemo } from "react";
import { finalistConfirmIsUncertain, type Mot3DFinalistSubmissionApi, type Mot3DFinalistSubmissionPreview, type Mot3DFinalistSubmissionResult, type Mot3DFinalistSubmissionStatus } from "../../../api/clients/mot3dFinalistSubmission";
import type { ZeusSnapshot } from "../../../api/schema/domain";
import { useGuardedStageController } from "../shared/useGuardedStageController";

const apiIds = new WeakMap<object, number>(); let nextApiId = 1;
const apiId = (api: object) => { const found = apiIds.get(api); if (found) return found; const value = nextApiId++; apiIds.set(api, value); return value; };
export function useMot3DFinalistSubmissionController({ campaignId, snapshot, enabled, api }: { campaignId: string; snapshot: ZeusSnapshot | null; enabled: boolean; api: Mot3DFinalistSubmissionApi }) {
  const profile = snapshot?.profile;
  const operations = useMemo(() => ({ status: () => api.status(campaignId, profile!), preview: () => api.preview(campaignId, profile!), confirm: (review: Mot3DFinalistSubmissionPreview) => api.confirm(review.preview_token), reset: () => api.reset() }), [api, campaignId, profile]);
  return useGuardedStageController<Mot3DFinalistSubmissionStatus, Mot3DFinalistSubmissionPreview, Mot3DFinalistSubmissionResult>({
    enabled: enabled && Boolean(profile),
    contextKey: `${campaignId}:${enabled}:${profile?.host ?? ""}:${profile?.authentication ?? ""}:${profile?.username ?? ""}:${profile?.project_directory ?? ""}:${apiId(api)}`,
    operations,
    stateForStatus: (status) => status.next_action === "review_submission" ? "ready" : status.next_action === "inspect_zeus" ? "blocked" : "idle",
    canPreview: (status) => status?.next_action === "review_submission",
    isUnknownConfirmation: finalistConfirmIsUncertain,
  });
}
