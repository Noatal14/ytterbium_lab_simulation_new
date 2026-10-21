import { act,render,renderHook,screen } from "@testing-library/react";
import { afterEach,expect,it,vi } from "vitest";
import success from "../../../tests/contracts/v1/workflow_api_success.json";
import { parseZeusSnapshot } from "../api/schema/domain";
import { Mot3DCampaignFlow } from "../features/campaign/Mot3DCampaignFlow";
import { createMot3DRefinementSubmissionApi } from "../api/clients/mot3dRefinementSubmission";
import { useMot3DRefinementSubmissionController } from "../features/campaign/controllers/useMot3DRefinementSubmissionController";
import { createMot3DClosureSubmissionApi } from "../api/clients/mot3dClosureSubmission";
import { useMot3DClosureSubmissionController } from "../features/campaign/controllers/useMot3DClosureSubmissionController";
import { createMot3DClosureTransitionApi } from "../api/clients/mot3dClosureTransition";
import { useMot3DClosureTransitionController } from "../features/campaign/controllers/useMot3DClosureTransitionController";
import { createMot3DFinalistSubmissionApi } from "../api/clients/mot3dFinalistSubmission";
import { useMot3DFinalistSubmissionController } from "../features/campaign/controllers/useMot3DFinalistSubmissionController";
import { createMot3DFinalistTransitionApi } from "../api/clients/mot3dFinalistTransition";
import { useMot3DFinalistTransitionController } from "../features/campaign/controllers/useMot3DFinalistTransitionController";
import { createMot3DFinalInputSubmissionApi } from "../api/clients/mot3dFinalInputSubmission";
import { useMot3DFinalInputSubmissionController } from "../features/campaign/controllers/useMot3DFinalInputSubmissionController";
import { createMot3DFinalValidationSubmissionApi } from "../api/clients/mot3dFinalValidationSubmission";
import { useMot3DFinalValidationSubmissionController } from "../features/campaign/controllers/useMot3DFinalValidationSubmissionController";
import { createMot3DFinalValidationTransitionApi } from "../api/clients/mot3dFinalValidationTransition";
import { useMot3DFinalValidationTransitionController } from "../features/campaign/controllers/useMot3DFinalValidationTransitionController";
import { createMot3DFinalValidationCompletionApi } from "../api/clients/mot3dFinalValidationCompletion";
import { useMot3DFinalValidationCompletionController } from "../features/campaign/controllers/useMot3DFinalValidationCompletionController";
const cases=[
 ["RefinementSubmission","mot3d-refinement","refinement",useMot3DRefinementSubmissionController,createMot3DRefinementSubmissionApi],
 ["ClosureSubmission","mot3d-closure","closure",useMot3DClosureSubmissionController,createMot3DClosureSubmissionApi],
 ["ClosureTransition","mot3d-closure-transition","closureTransition",useMot3DClosureTransitionController,createMot3DClosureTransitionApi],
 ["FinalistSubmission","mot3d-finalist","finalist",useMot3DFinalistSubmissionController,createMot3DFinalistSubmissionApi],
 ["FinalistTransition","mot3d-finalist-transition","finalistTransition",useMot3DFinalistTransitionController,createMot3DFinalistTransitionApi],
 ["FinalInputSubmission","mot3d-final-input","finalInputSubmission",useMot3DFinalInputSubmissionController,createMot3DFinalInputSubmissionApi],
 ["FinalValidationSubmission","mot3d-final-validation","finalValidation",useMot3DFinalValidationSubmissionController,createMot3DFinalValidationSubmissionApi],
 ["FinalValidationTransition","mot3d-final-validation-transition","finalValidationTransition",useMot3DFinalValidationTransitionController,createMot3DFinalValidationTransitionApi],
 ["FinalValidationCompletion","mot3d-final-validation-completion","finalValidationCompletion",useMot3DFinalValidationCompletionController,createMot3DFinalValidationCompletionApi],
] as const;
const data=(id:string)=>structuredClone(success.cases.find(row=>row.id===id)!.body.data) as Record<string,any>;
afterEach(()=>vi.unstubAllGlobals());
const internalFallback: Record<string,string> = {refinement:"creation_failed",closure:"mot_3d_closure_submission_failed",closureTransition:"mot_3d_closure_transition_failed",finalist:"mot_3d_finalist_submission_failed",finalistTransition:"mot_3d_finalist_transition_failed",finalInputSubmission:"mot_3d_final_input_submission_failed",finalValidation:"mot_3d_final_validation_submission_failed",finalValidationTransition:"mot_3d_final_validation_transition_failed",finalValidationCompletion:"mot_3d_final_validation_completion_failed"};
const uncertainCases=cases.flatMap(row=>[([...row,"remote_response_invalid"] as const),([...row,"creation_failed"] as const)]);
it.each(uncertainCases)("%s treats %s after confirmation as uncertain",async(_label,id,slot,useController,createApi,errorCode)=>{
 const status=data(id+"-status"),preview=data(id+"-preview");
 if(slot==="finalValidationCompletion") {
  // The snapshot catalog stores completed status. Use the existing canonical
  // pre-completion state shape, still parsed by the real strict API client.
  status.campaign.stage="final_validation";status.final_validation.status="ready_to_advance";
  status.completion={status:"not_completed",detail:null};status.next_action="review_completion";
  status.local_sync={status:"not_synchronized",receipt_sha256:null};
 }
 const api=createApi(async()=>"csrf");const confirm=vi.spyOn(api,"confirm");
 const reply=(value:unknown)=>new Response(JSON.stringify({api_version:1,data:value}),{status:200});
 const fetch=vi.fn().mockResolvedValueOnce(reply(status)).mockResolvedValueOnce(reply(preview)).mockResolvedValueOnce(new Response(JSON.stringify({error:{code:errorCode,message:errorCode==="creation_failed"?"Local campaign creation failed safely.":"The response could not be verified."}}),{status:errorCode==="creation_failed"?500:412}));vi.stubGlobal("fetch",fetch);
 const snapshot=parseZeusSnapshot(data("zeus-snapshot"));
 const hook=renderHook(()=>(useController as (options:any)=>any)({campaignId:status.campaign.id,snapshot,enabled:true,api}));
 await act(()=>hook.result.current.refresh());await act(()=>hook.result.current.review());await act(()=>hook.result.current.confirm());
 expect(hook.result.current.errorPhase).toBe(slot==="refinement"?"submit_unknown":"confirm_unknown");
 await expect(confirm.mock.results[0].value).rejects.toMatchObject({code:errorCode==="creation_failed"?internalFallback[slot]:"remote_response_invalid"});
 if(errorCode==="creation_failed")expect(hook.result.current.error).toMatch(/outcome is unknown/);
 await expect(api.confirm(slot==="finalValidationCompletion"?preview:preview.preview_token)).rejects.toThrow(/no longer active/);
 const inactive={state:"terminal",phase:"blocked",status:null,preview:null,result:null,error:"",refresh:vi.fn(),review:vi.fn(),confirm:vi.fn(),reset:vi.fn()};
 const props:any={stage:status.campaign.stage,connected:true,discovery:inactive,transition:inactive,preliminary:inactive,onConnectZeus:vi.fn(),onViewJobs:vi.fn(),[slot]:hook.result.current};
 const view=render(<Mot3DCampaignFlow {...props}/>);
 expect(screen.queryAllByRole("button",{name:/^Review /})).toHaveLength(0);
 let reject!: (error:Error)=>void;fetch.mockReturnValueOnce(new Promise((_resolve,no)=>{reject=no;}));act(()=>{void hook.result.current.refresh();});
 view.rerender(<Mot3DCampaignFlow {...props} {...{[slot]:hook.result.current}}/>);
 expect(screen.queryAllByRole("button",{name:/^Review /})).toHaveLength(0);
 await act(()=>reject(new Error("Status transport unavailable")));
 view.rerender(<Mot3DCampaignFlow {...props} {...{[slot]:hook.result.current}}/>);
 expect(screen.queryAllByRole("button",{name:/^Review /})).toHaveLength(0);
 fetch.mockResolvedValueOnce(reply(status));await act(()=>hook.result.current.refresh());
 view.rerender(<Mot3DCampaignFlow {...props} {...{[slot]:hook.result.current}}/>);
 expect(screen.queryAllByRole("button",{name:/^Review /})).toHaveLength(1);
 expect(fetch.mock.calls.filter(([path])=>String(path).endsWith('/confirm'))).toHaveLength(1);
 expect(fetch.mock.calls.filter(([path])=>String(path).endsWith('/preview'))).toHaveLength(1);
});

const rejectionCases=cases.flatMap(row=>["confirmation_invalid","local_files_changed","invalid_csrf","untrusted_origin"].map(code=>[...row,code] as const));
it.each(rejectionCases)("%s preserves deterministic preflight rejection",async(_label,id,_slot,useController,createApi,errorCode)=>{
 const status=data(id+"-status"),preview=data(id+"-preview");
 if(_slot==="finalValidationCompletion") {
  status.campaign.stage="final_validation";status.final_validation.status="ready_to_advance";
  status.completion={status:"not_completed",detail:null};status.next_action="review_completion";status.local_sync={status:"not_synchronized",receipt_sha256:null};
 }
 const api=createApi(async()=>"csrf");const confirm=vi.spyOn(api,"confirm");
 const fetch=vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({api_version:1,data:status}))).mockResolvedValueOnce(new Response(JSON.stringify({api_version:1,data:preview}))).mockResolvedValueOnce(new Response(JSON.stringify({error:{code:errorCode,message:"The confirmation was rejected before publication."}}),{status:["invalid_csrf","untrusted_origin"].includes(errorCode)?403:412}));vi.stubGlobal("fetch",fetch);
 const snapshot=parseZeusSnapshot(data("zeus-snapshot"));
 const hook=renderHook(()=>(useController as (options:any)=>any)({campaignId:status.campaign.id,snapshot,enabled:true,api}));
 await act(()=>hook.result.current.refresh());await act(()=>hook.result.current.review());await act(()=>hook.result.current.confirm());
 await expect(confirm.mock.results[0].value).rejects.toMatchObject({code:errorCode});
 expect(hook.result.current.errorPhase).toBe(_slot==="refinement"?"submit_rejected":"confirm_rejected");
 expect(fetch.mock.calls.filter(([path])=>String(path).endsWith('/confirm'))).toHaveLength(1);
});
