import { useMemo } from "react";
import {
  finalValidationCompletionIsUncertain,
  type Mot3DFinalValidationCompletionApi,
} from "../../../api/clients/mot3dFinalValidationCompletion";
import type { ZeusSnapshot } from "../../../api/schema/domain";
import { useGuardedStageController } from "../shared/useGuardedStageController";

const ids = new WeakMap<object, number>();
let nextId = 1;
const apiId = (api: object) => {
  const existing = ids.get(api);
  if (existing) return existing;
  const value = nextId++;
  ids.set(api, value);
  return value;
};

export function useMot3DFinalValidationCompletionController({
  campaignId,
  snapshot,
  enabled,
  api,
}: {
  campaignId: string;
  snapshot: ZeusSnapshot | null;
  enabled: boolean;
  api: Mot3DFinalValidationCompletionApi;
}) {
  const profile = snapshot?.profile;
  const commit = snapshot?.remote?.git_commit;
  const operations = useMemo(
    () => ({
      status: () => api.status(campaignId, profile!),
      preview: () => api.preview(campaignId, profile!, commit!),
      confirm: (preview: Awaited<ReturnType<Mot3DFinalValidationCompletionApi["preview"]>>) => api.confirm(preview),
      reset: () => api.reset(),
    }),
    [api, campaignId, profile, commit],
  );
  return useGuardedStageController({
    enabled: enabled && Boolean(profile && commit),
    contextKey: `${campaignId}:${enabled}:${profile?.host ?? ""}:${profile?.authentication ?? ""}:${profile?.username ?? ""}:${profile?.project_directory ?? ""}:${commit ?? ""}:${apiId(api)}`,
    operations,
    stateForStatus: (status) =>
      ["review_completion", "synchronize_results"].includes(status.next_action)
        ? "ready"
        : ["open_final_report", "review_extension_required"].includes(status.next_action)
          ? "success"
          : status.next_action === "inspect_zeus"
            ? "blocked"
            : "idle",
    canPreview: (status) => ["review_completion", "synchronize_results"].includes(status?.next_action ?? ""),
    isUnknownConfirmation: finalValidationCompletionIsUncertain,
  });
}
