import { useMemo } from "react";
import { finalInputConfirmIsUncertain, type Mot3DFinalInputSubmissionApi } from "../../../api/clients/mot3dFinalInputSubmission";
import type { ZeusSnapshot } from "../../../api/schema/domain";
import { useGuardedStageController } from "../shared/useGuardedStageController";

const apiIds = new WeakMap<object, number>(); let nextApiId = 1;
const apiId = (api: object) => { const found = apiIds.get(api); if (found) return found; const value = nextApiId++; apiIds.set(api, value); return value; };
export function useMot3DFinalInputSubmissionController({ campaignId, snapshot, enabled, api }: { campaignId: string; snapshot: ZeusSnapshot | null; enabled: boolean; api: Mot3DFinalInputSubmissionApi }) {
  const profile = snapshot?.profile, commit = snapshot?.remote?.git_commit;
  const operations = useMemo(() => ({ status: () => api.status(campaignId, profile!), preview: () => api.preview(campaignId, profile!, commit!), confirm: (review: Awaited<ReturnType<Mot3DFinalInputSubmissionApi["preview"]>>) => api.confirm(review.preview_token), reset: () => api.reset() }), [api, campaignId, profile, commit]);
  return useGuardedStageController({
    enabled: enabled && Boolean(profile && commit),
    contextKey: `${campaignId}:${enabled}:${profile?.host ?? ""}:${profile?.authentication ?? ""}:${profile?.username ?? ""}:${profile?.project_directory ?? ""}:${commit ?? ""}:${apiId(api)}`,
    operations,
    stateForStatus: (status) => status.next_action === "review_submission" ? "ready" : status.next_action === "inspect_zeus" ? "blocked" : "idle",
    canPreview: (status) => status?.next_action === "review_submission",
    isUnknownConfirmation: finalInputConfirmIsUncertain,
  });
}
