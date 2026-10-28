import type { Campaign } from "../../api/clients/campaign";
import type { useSensitivityController } from "./controllers/useSensitivityController";
import type { useProductionController } from "./controllers/useProductionController";
type Operation<T> = Pick<T, Extract<keyof T, "state" | "status" | "result" | "error">> & { lastObservation?: "status" | "confirm" | null };
type SensitivityFlow = ReturnType<typeof useSensitivityController>;
type ProductionFlow = ReturnType<typeof useProductionController>;
export type SensitivityPriorityFlow = { [K in keyof SensitivityFlow]: Operation<SensitivityFlow[K]> };
export type ProductionPriorityFlow = { [K in "preparation" | "submission" | "finalization"]: Operation<ProductionFlow[K]> };
type Evidence = { stage: "Confirmation" | "Sensitivity" | "Production" | "Final report"; lifecycle: string; error: boolean; time: number; order: number };

/** Only same-campaign controller evidence can supersede an earlier stage card.
 * Controller generations own freshness; local campaign.stage is never authority.
 */
export function late2DPriority(campaign: Campaign, sensitivity?: SensitivityPriorityFlow, production?: ProductionPriorityFlow) {
  if (campaign.family !== "mot_2d" || campaign.trust !== "trusted-current") return null;
  const owns = (v: { campaign: { id: string } } | null | undefined) => v?.campaign.id === campaign.id;
  const resultOwns = (v: { campaign_id: string } | null | undefined) => v?.campaign_id === campaign.id;
  // A failed fresh read has no new DTO timestamp; keep that uncertainty.
  // Terminal DTO lifecycles are ranked by their own authenticated query time.
  const bad = (op: { error: string }) => Boolean(op.error);
  const confirmed = (op: { lastObservation?: "status" | "confirm" | null; result: { campaign_id: string } | null }) => op.lastObservation === "confirm" && resultOwns(op.result);
  const candidates: Evidence[] = [];
  const time = (v: { queried_at: string } | null) => v ? Date.parse(v.queried_at) : 0;
  const final = production?.finalization;
  if (final && (owns(final.status) || resultOwns(final.result))) {
    const lifecycle = !confirmed(final) && owns(final.status) ? final.status!.production.status : "campaign_complete";
    candidates.push({ stage: lifecycle === "campaign_complete" ? "Final report" : "Production", lifecycle, error: bad(final), time: time(final.status), order: lifecycle === "campaign_complete" ? 30 : 22 });
  }
  const prod = production?.submission;
  if (prod && (owns(prod.status) || resultOwns(prod.result))) candidates.push({ stage: "Production", lifecycle: !confirmed(prod) && owns(prod.status) ? prod.status!.submission.status : "submitted", error: bad(prod), time: time(prod.status), order: 21 });
  const prep = production?.preparation;
  if (prep && (owns(prep.status) || resultOwns(prep.result))) {
    const lifecycle = !confirmed(prep) && owns(prep.status) ? prep.status!.sensitivity.status : "production_prepared";
    candidates.push({ stage: lifecycle === "production_prepared" ? "Production" : "Sensitivity", lifecycle, error: bad(prep), time: time(prep.status), order: lifecycle === "production_prepared" ? 20 : 11 });
  }
  const sens = sensitivity?.submission;
  if (sens && (owns(sens.status) || resultOwns(sens.result))) candidates.push({ stage: "Sensitivity", lifecycle: !confirmed(sens) && owns(sens.status) ? sens.status!.submission.status : "submitted", error: bad(sens), time: time(sens.status), order: 11 });
  const sensPrep = sensitivity?.preparation;
  if (sensPrep && (owns(sensPrep.status) || resultOwns(sensPrep.result))) {
    const lifecycle = !confirmed(sensPrep) && owns(sensPrep.status) ? sensPrep.status!.confirmation.status : "sensitivity_prepared";
    candidates.push({ stage: lifecycle === "sensitivity_prepared" ? "Sensitivity" : "Confirmation", lifecycle, error: bad(sensPrep), time: time(sensPrep.status), order: lifecycle === "sensitivity_prepared" ? 10 : 9 });
  }
  // A later authenticated phase supersedes errors in its predecessor card.
  const e = candidates.sort((a,b) => b.order - a.order || Number(b.error) - Number(a.error) || b.time - a.time)[0];
  if (!e) return null;
  const blocked = e.error || ["held", "failed", "completed_failed", "status_unknown", "outcome_unknown", "outputs_invalid"].includes(e.lifecycle);
  if (blocked) return { blocked, title: "Manual verification required", text: `${e.stage} is the latest verified campaign stage, but its current outcome needs inspection. Do not submit again; inspect the stage evidence and Zeus jobs.` };
  if (e.lifecycle === "campaign_complete") return { blocked, title: "Final report is ready", text: "The authenticated sealed final results are available below. Earlier stage warnings remain in their historical cards." };
  if (["queued", "running", "submitted"].includes(e.lifecycle)) return { blocked, title: `${e.stage} is ${words(e.lifecycle)}`, text: `Follow the current ${e.stage} job below. Earlier stage warnings remain historical and do not replace this verified later-stage evidence.` };
  if (["not_submitted", "sensitivity_prepared", "production_prepared", "ready_to_prepare_sensitivity", "ready_to_prepare_production", "ready_to_finalize"].includes(e.lifecycle)) return { blocked, title: "Action required", text: `${e.stage} has reached ${words(e.lifecycle)}. Review the validated next operation in its stage card; no automatic submission occurs.` };
  return { blocked, title: `${e.stage} needs result validation`, text: "Scheduler completion alone does not verify results. Check the current stage outputs below before any next operation." };
}
const words = (value: string) => value.replaceAll("_", " ");
