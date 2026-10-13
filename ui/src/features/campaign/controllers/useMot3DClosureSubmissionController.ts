import { useMemo } from "react";
import {
  closureConfirmIsUncertain,
  type Mot3DClosureSubmissionApi,
  type Mot3DClosureSubmissionPreview,
  type Mot3DClosureSubmissionResult,
  type Mot3DClosureSubmissionStatus,
} from "../../../api/clients/mot3dClosureSubmission";
import type { ZeusSnapshot } from "../../../api/schema/domain";
import { useGuardedStageController } from "../shared/useGuardedStageController";

export function useMot3DClosureSubmissionController({
  campaignId,
  snapshot,
  enabled,
  api,
}: {
  campaignId: string;
  snapshot: ZeusSnapshot | null;
  enabled: boolean;
  api: Mot3DClosureSubmissionApi;
}) {
  const profile = snapshot?.profile;
  const operations = useMemo(() => ({
    status: () => {
      if (!profile) throw new Error("Connect to Zeus before checking Closure.");
      return api.status(campaignId, profile);
    },
    preview: () => {
      if (!profile) throw new Error("Connect to Zeus before reviewing Closure.");
      return api.preview(campaignId, profile);
    },
    confirm: (review: Mot3DClosureSubmissionPreview) => api.confirm(review.preview_token),
    reset: () => api.reset(),
  }), [api, campaignId, profile]);
  const contextKey = `${campaignId}:${enabled}:${profile?.host ?? ""}:${profile?.username ?? ""}:${profile?.project_directory ?? ""}:${profile?.authentication ?? ""}`;
  return useGuardedStageController<Mot3DClosureSubmissionStatus, Mot3DClosureSubmissionPreview, Mot3DClosureSubmissionResult>({
    enabled: enabled && Boolean(profile),
    contextKey,
    operations,
    stateForStatus: (status) => status.next_action === "review_submission" ? "ready" : status.next_action === "inspect_zeus" ? "blocked" : "idle",
    canPreview: (status) => status?.next_action === "review_submission",
    isUnknownConfirmation: closureConfirmIsUncertain,
  });
}
