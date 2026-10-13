import type { GuardedStagePhase } from "./useGuardedStageController";

export type GuardedStageActionDescriptor = {
  refreshLabel: string;
  reviewLabel: string;
  confirmLabel: string;
  resetLabel: string;
};

export function GuardedStageActions({
  phase,
  labels,
  onRefresh,
  onReview,
  onConfirm,
  onReset,
}: {
  phase: GuardedStagePhase;
  labels: GuardedStageActionDescriptor;
  onRefresh: () => void;
  onReview: () => void;
  onConfirm: () => void;
  onReset: () => void;
}) {
  if (phase === "review") return <div className="form-actions"><button type="button" className="secondary-button" onClick={onReset}>{labels.resetLabel}</button><button type="button" className="primary-button" onClick={onConfirm}>{labels.confirmLabel}</button></div>;
  if (phase === "ready") return <div className="form-actions"><button type="button" className="secondary-button" onClick={onRefresh}>{labels.refreshLabel}</button><button type="button" className="primary-button" onClick={onReview}>{labels.reviewLabel}</button></div>;
  if (["checking", "reviewing", "confirming"].includes(phase)) return <div className="form-actions"><button type="button" className="secondary-button" disabled>{phase === "checking" ? "Checking…" : phase === "reviewing" ? "Reviewing…" : "Confirming…"}</button></div>;
  if (phase === "blocked" || phase === "success") return null;
  return <div className="form-actions"><button type="button" className="primary-button" onClick={onRefresh}>{labels.refreshLabel}</button></div>;
}
