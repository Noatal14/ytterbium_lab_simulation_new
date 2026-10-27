import { MOT_3D_REFINEMENT_INVALID_REASONS } from "../../generated/mot3dRefinementTransitionSpec.v1";
import { postData } from "../http/envelope";
import type { ZeusSnapshot } from "../schema/domain";
import { creationApi } from "./campaign";
import type { Mot3DFamilyChain } from "./mot3dFamilyChain";
import { REFINEMENT_TRANSITION, parseSelectionTransitionStatus, parseSelectionTransitionPreview, parseSelectionTransitionResult } from "./mot3dTransitionValidation";

type Profile=ZeusSnapshot["profile"];type InvalidReason=(typeof MOT_3D_REFINEMENT_INVALID_REASONS)[number];
export type Mot3DRefinementTransitionLifecycle="not_submitted"|"submitted"|"queued"|"running"|"held"|"completed_failed"|"status_unknown"|"partial"|"outcome_unknown"|"completed_success_unvalidated"|"ready_to_advance"|"closure_prepared";
export type Mot3DRefinementTransitionStatus={source:"zeus";queried_at:string;campaign:{id:string;name:string;stage:"refinement"|"closure"};refinement:{status:Mot3DRefinementTransitionLifecycle;chain:Mot3DFamilyChain};scheduler:{expected_array_tasks:6;expected_merge_jobs:2;completed_array_tasks:number;completed_merge_jobs:number};validation:{status:"not_started"|"valid"|"scientifically_invalid";result_artifacts:number;expected_result_artifacts:200;reason_code:InvalidReason|null};transition:{status:"not_prepared"|"closure_prepared"};next_action:"wait"|"review_transition"|"synchronize_results"|"open_closure"|"inspect_zeus";local_sync:{status:"not_synchronized"|"synchronized";receipt_sha256:string|null}};
export type Mot3DRefinementTransitionPreview={preview_token:string;expires_in_seconds:300;campaign:{id:string;name:string;git_commit:string};from_stage:"refinement";to_stage:"closure";refinement:{result_artifacts:200;expected_result_artifacts:200;families:["angled_donut","single_pass"];evidence_sha256:string};artifacts:{synchronize:{result_files:200;submission_receipts:1};create:{selection_files:2;job_files:4};update:["campaign.json"];transfer_files:208};effects:{synchronize_refinement:true;prepare_closure:true;submit_closure:false;start_simulation:false;overwrite_existing:false}};
export type Mot3DRefinementTransitionResult={status:"closure_prepared";campaign_id:string;stage:"closure";artifacts:{synchronized:201;created:6;updated:1;bundle_sha256:string};submitted_to_zeus:false;simulation_started:false;local_sync:{status:"synchronized";receipt_sha256:string}};
export function parseMot3DRefinementTransitionStatus(
  value: unknown,
): Mot3DRefinementTransitionStatus {
  const { evidence, ...status } = parseSelectionTransitionStatus(
    value,
    REFINEMENT_TRANSITION,
  );
  return { ...status, refinement: evidence };
}
export function parseMot3DRefinementTransitionPreview(
  value: unknown,
  campaignId: string,
): Mot3DRefinementTransitionPreview {
  const { common } = parseSelectionTransitionPreview(
    value,
    campaignId,
    REFINEMENT_TRANSITION,
  );
  const { evidence, ...preview } = common;
  return {
    ...preview,
    refinement: evidence,
    effects: {
      synchronize_refinement: true,
      prepare_closure: true,
      submit_closure: false,
      start_simulation: false,
      overwrite_existing: false,
    },
  };
}
export function parseMot3DRefinementTransitionResult(
  value: unknown,
  campaignId: string,
): Mot3DRefinementTransitionResult {
  return parseSelectionTransitionResult(
    value,
    campaignId,
    REFINEMENT_TRANSITION,
  );
}
export function createMot3DRefinementTransitionApi(session:()=>Promise<string>){const contexts=new Map<string,{campaignId:string;csrf:string}>();const body=(campaign_id:string,profile:Profile)=>({campaign_id,username:profile.username,project_directory:profile.project_directory});return{async status(campaignId:string,profile:Profile){const csrf=await session();const parsed=parseMot3DRefinementTransitionStatus(await postData("/api/v1/zeus/mot-3d/refinement-transition/status",body(campaignId,profile),csrf));if(parsed.campaign.id!==campaignId)throw new Error("Refinement transition did not match the selected campaign.");return parsed},async preview(campaignId:string,profile:Profile){const csrf=await session();const parsed=parseMot3DRefinementTransitionPreview(await postData("/api/v1/zeus/mot-3d/refinement-transition/preview",body(campaignId,profile),csrf),campaignId);contexts.set(parsed.preview_token,{campaignId,csrf});return parsed},async confirm(token:string){const context=contexts.get(token);if(!context)throw new Error("The Refinement synchronization review is no longer active.");contexts.delete(token);return parseMot3DRefinementTransitionResult(await postData("/api/v1/zeus/mot-3d/refinement-transition/confirm",{preview_token:token},context.csrf),context.campaignId)},reset(){contexts.clear()}}}
export type Mot3DRefinementTransitionApi=ReturnType<typeof createMot3DRefinementTransitionApi>;export const mot3DRefinementTransitionApi=createMot3DRefinementTransitionApi(()=>creationApi.session());
