/** A successful, receipt-bound transition requests a canonical GET; it never grants a stage. */
export type CanonicalTransitionCommit = {
  campaign_id: string;
  stage: string;
  submitted_to_zeus: false;
  simulation_started: false;
  local_sync: { status: "synchronized"; receipt_sha256: string };
};

export function observeCampaignTransition<Args extends unknown[], Result>(
  api: { confirm: (...args: Args) => Promise<Result> },
  onCommitted: (result: CanonicalTransitionCommit) => void,
) {
  return async (...args: Args): Promise<Result> => {
    const result = await api.confirm(...args);
    if (result && typeof result === "object") {
      const value = result as Partial<CanonicalTransitionCommit>;
      if (typeof value.campaign_id === "string" && typeof value.stage === "string" && value.submitted_to_zeus === false && value.simulation_started === false && value.local_sync?.status === "synchronized" && typeof value.local_sync.receipt_sha256 === "string" && /^[a-f0-9]{64}$/.test(value.local_sync.receipt_sha256)) onCommitted(value as CanonicalTransitionCommit);
    }
    return result;
  };
}
