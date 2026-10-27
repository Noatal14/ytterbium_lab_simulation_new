import { adaptConfirmationError, isKnownServerError, confirmationRequiresManualVerification } from "../errorSemantics";
import { postData } from "../http/envelope";
import type { ZeusSnapshot } from "../schema/domain";
import { creationApi } from "./campaign";
import { FINALIST_TRANSITION, parseSelectionTransitionStatus, parseSelectionTransitionPreview, parseSelectionTransitionResult, transitionObject } from "./mot3dTransitionValidation";
type Profile=ZeusSnapshot["profile"];
const domain="mot_3d_finalist_transition" as const,RULE="largest lower endpoint of the simultaneous two-sided 95% interval; ties broken by mean usable fraction",candidate=/^(angled_donut|single_pass)_finalist_0[1-3]$/;
export class Mot3DFinalistTransitionApiError extends Error{constructor(public code:string,message:string){super(message)}}
const adapt=(e:{code:string;message:string})=>new Mot3DFinalistTransitionApiError(isKnownServerError(domain,e.code)?e.code:"mot_3d_finalist_transition_failed",isKnownServerError(domain,e.code)?e.message:"Finalist result verification could not be verified.");
export const finalistTransitionIsUncertain=(e:unknown)=>e instanceof Mot3DFinalistTransitionApiError&&(confirmationRequiresManualVerification(domain,e.code)||["finalist_transition_outcome_unknown","transition_outcome_unknown","local_sync_outcome_unknown"].includes(e.code));
export function parseMot3DFinalistTransitionStatus(value: unknown) {
  const { evidence, ...status } = parseSelectionTransitionStatus(
    value,
    FINALIST_TRANSITION,
  );
  return { ...status, finalist_selection: evidence };
}
export function parseMot3DFinalistTransitionPreview(
  value: unknown,
  campaignId: string,
) {
  const parsed = parseSelectionTransitionPreview(
    value,
    campaignId,
    FINALIST_TRANSITION,
  );
  const { evidence, ...preview } = parsed.common;
  const winner = transitionObject(parsed.winnerSelection, [
    "rule",
    "winners",
    "evidence_sha256",
  ]);
  if (
    winner.rule !== RULE ||
    winner.evidence_sha256 !== evidence.evidence_sha256 ||
    !Array.isArray(winner.winners) ||
    winner.winners.length !== 2
  )
    throw new Error("Invalid winner selection.");
  const winners = winner.winners.map((value: unknown, index) => {
    const row = transitionObject(value, ["family", "candidate_id"]);
    const family = index === 0 ? "angled_donut" : "single_pass";
    if (
      row.family !== family ||
      typeof row.candidate_id !== "string" ||
      !candidate.test(row.candidate_id) ||
      !row.candidate_id.startsWith(`${family}_finalist_`)
    )
      throw new Error("Invalid winner selection.");
    return { family, candidate_id: row.candidate_id };
  });
  return {
    ...preview,
    finalist_selection: evidence,
    winner_selection: {
      rule: RULE,
      winners,
      evidence_sha256: evidence.evidence_sha256,
    },
    effects: {
      synchronize_finalist_selection: true,
      prepare_final_validation_inputs: true,
      submit_final_validation_inputs: false,
      start_simulation: false,
      overwrite_existing: false,
    },
  };
}
export function parseMot3DFinalistTransitionResult(
  value: unknown,
  campaignId: string,
) {
  return parseSelectionTransitionResult(value, campaignId, FINALIST_TRANSITION);
}
export type Mot3DFinalistTransitionStatus=ReturnType<typeof parseMot3DFinalistTransitionStatus>;export type Mot3DFinalistTransitionPreview=ReturnType<typeof parseMot3DFinalistTransitionPreview>;export type Mot3DFinalistTransitionResult=ReturnType<typeof parseMot3DFinalistTransitionResult>;
export function createMot3DFinalistTransitionApi(session:()=>Promise<string>){let generation=0;const contexts=new Map<string,{campaignId:string;csrf:string;generation:number}>(),body=(campaign_id:string,p:Profile)=>({campaign_id,username:p.username,project_directory:p.project_directory});return{async status(campaignId:string,p:Profile){const active=generation,v=parseMot3DFinalistTransitionStatus(await postData("/api/v1/zeus/mot-3d/finalist-transition/status",body(campaignId,p),await session(),adapt));if(active!==generation||v.campaign.id!==campaignId)throw new Error("Finalist transition status is stale or mismatched.");return v},async preview(campaignId:string,p:Profile){const active=generation,csrf=await session(),v=parseMot3DFinalistTransitionPreview(await postData("/api/v1/zeus/mot-3d/finalist-transition/preview",body(campaignId,p),csrf,adapt),campaignId);if(active!==generation)throw new Error("Finalist transition review is stale.");contexts.set(v.preview_token,{campaignId,csrf,generation:active});return v},async confirm(token:string){const c=contexts.get(token);if(!c)throw new Error("The Finalist transition review is no longer active.");contexts.delete(token);try{const v=parseMot3DFinalistTransitionResult(await postData("/api/v1/zeus/mot-3d/finalist-transition/confirm",{preview_token:token},c.csrf,(error) => adaptConfirmationError(error, adapt, Mot3DFinalistTransitionApiError)),c.campaignId);if(c.generation!==generation)throw new Error("stale");return v}catch(e){if(e instanceof Mot3DFinalistTransitionApiError)throw e;throw new Mot3DFinalistTransitionApiError("finalist_transition_outcome_unknown","The transition outcome could not be verified. Do not retry; inspect Zeus and the campaign.")}},reset(){generation+=1;contexts.clear()}}}
export type Mot3DFinalistTransitionApi=ReturnType<typeof createMot3DFinalistTransitionApi>;export const mot3DFinalistTransitionApi=createMot3DFinalistTransitionApi(()=>creationApi.session());
