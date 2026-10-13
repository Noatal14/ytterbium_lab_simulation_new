import { useMemo } from "react";
import {
  finalValidationConfirmIsUncertain,
  type Mot3DFinalValidationSubmissionApi,
} from "../../../api/clients/mot3dFinalValidationSubmission";
import type { ZeusSnapshot } from "../../../api/schema/domain";
import { useGuardedStageController } from "../shared/useGuardedStageController";
const ids = new WeakMap<object, number>();
let next = 1;
const id = (v: object) => {
  const old = ids.get(v);
  if (old) return old;
  ids.set(v, next);
  return next++;
};
export function useMot3DFinalValidationSubmissionController({
  campaignId,
  snapshot,
  enabled,
  api,
}: {
  campaignId: string;
  snapshot: ZeusSnapshot | null;
  enabled: boolean;
  api: Mot3DFinalValidationSubmissionApi;
}) {
  const p = snapshot?.profile;
  const operations = useMemo(
    () => ({
      status: () => api.status(campaignId, p!),
      preview: () => api.preview(campaignId, p!),
      confirm: (
        v: Awaited<ReturnType<Mot3DFinalValidationSubmissionApi["preview"]>>,
      ) => api.confirm(v.preview_token),
      reset: () => api.reset(),
    }),
    [api, campaignId, p],
  );
  return useGuardedStageController({
    enabled: enabled && Boolean(p),
    contextKey: `${campaignId}:${enabled}:${p?.host ?? ""}:${p?.authentication ?? ""}:${p?.username ?? ""}:${p?.project_directory ?? ""}:${id(api)}`,
    operations,
    stateForStatus: (s) =>
      s.next_action === "review_submission"
        ? "ready"
        : s.next_action === "inspect_zeus"
          ? "blocked"
          : "idle",
    canPreview: (s) => s?.next_action === "review_submission",
    isUnknownConfirmation: finalValidationConfirmIsUncertain,
  });
}
