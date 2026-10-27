import { act, render, renderHook, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import success from "./teamContractFixture";
import { parseZeusSnapshot } from "../api/schema/domain";
import { createMot3DDiscoveryApi } from "../api/clients/mot3dDiscovery";
import { createMot3DDiscoveryTransitionApi } from "../api/clients/mot3dDiscoveryTransition";
import { createPreliminaryCheckApi } from "../api/clients/mot3dPreliminaryCheck";
import { createMot3DPreliminaryTransitionApi } from "../api/clients/mot3dPreliminaryTransition";
import { createMot3DRefinementSubmissionApi } from "../api/clients/mot3dRefinementSubmission";
import { createMot3DRefinementTransitionApi } from "../api/clients/mot3dRefinementTransition";
import { useMot3DDiscoveryController } from "../features/campaign/controllers/useMot3DDiscoveryController";
import { useMot3DDiscoveryTransitionController } from "../features/campaign/controllers/useMot3DDiscoveryTransitionController";
import { useMot3DPreliminaryCheckController } from "../features/campaign/controllers/useMot3DPreliminaryCheckController";
import { useMot3DPreliminaryTransitionController } from "../features/campaign/controllers/useMot3DPreliminaryTransitionController";
import { useMot3DRefinementSubmissionController } from "../features/campaign/controllers/useMot3DRefinementSubmissionController";
import { useMot3DRefinementTransitionController } from "../features/campaign/controllers/useMot3DRefinementTransitionController";
import { Mot3DCampaignFlow } from "../features/campaign/Mot3DCampaignFlow";
const data=(id:string)=>structuredClone(success.cases.find(row=>row.id===id)!.body.data) as Record<string,any>;
const cases=[
 ["Discovery","mot3d-discovery","discovery",useMot3DDiscoveryController,createMot3DDiscoveryApi],
 ["Discovery synchronization","mot3d-transition","transition",useMot3DDiscoveryTransitionController,createMot3DDiscoveryTransitionApi],
 ["Preliminary submission","mot3d-preliminary","preliminary",useMot3DPreliminaryCheckController,createPreliminaryCheckApi],
 ["Preliminary synchronization","mot3d-preliminary-transition","preliminaryTransition",useMot3DPreliminaryTransitionController,createMot3DPreliminaryTransitionApi],
 ["Refinement submission","mot3d-refinement","refinement",useMot3DRefinementSubmissionController,createMot3DRefinementSubmissionApi],
 ["Refinement synchronization","mot3d-refinement-transition","refinementTransition",useMot3DRefinementTransitionController,createMot3DRefinementTransitionApi],
] as const;
afterEach(()=>vi.unstubAllGlobals());
it.each(cases)("%s keeps old ready DTO historical after unknown confirm and failed refresh",async(_label,id,slot,useController,createApi)=>{
 const status=data(id+"-status"),preview=data(id+"-preview");const api=createApi(async()=>"csrf");
 const reply=(value:unknown)=>new Response(JSON.stringify({api_version:1,data:value}),{status:200});
 const fetch=vi.fn().mockResolvedValueOnce(reply(status)).mockResolvedValueOnce(reply(preview)).mockResolvedValueOnce(new Response(JSON.stringify({error:{code:slot==="discovery"?"discovery_submission_outcome_unknown":slot==="refinement"?"refinement_submission_outcome_unknown":"transition_outcome_unknown",message:"The operation outcome is unknown. Check current status. Do not retry automatically."}}),{status:409}));vi.stubGlobal("fetch",fetch);
 const snapshot=parseZeusSnapshot(data("zeus-snapshot"));
 // Each real client strictly parses the original success-contract DTOs.
 const hook=renderHook(()=>(useController as (options:any)=>any)({campaignId:status.campaign.id,snapshot,enabled:true,api}));
 await act(()=>hook.result.current.refresh());await act(()=>hook.result.current.review());await act(()=>hook.result.current.confirm());
 const inactive={state:"terminal",status:null,preview:null,result:null,error:"",refresh:vi.fn(),review:vi.fn(),confirm:vi.fn(),reset:vi.fn()};
 const props:any={stage:status.campaign.stage,connected:true,discovery:inactive,transition:inactive,preliminary:inactive,onConnectZeus:vi.fn(),onViewJobs:vi.fn(),[slot]:hook.result.current};
 const view=render(<Mot3DCampaignFlow {...props}/>);
 expect(screen.queryAllByRole("button",{name:/^Review /})).toHaveLength(0);
 let reject!: (error:Error)=>void;fetch.mockReturnValueOnce(new Promise((_resolve,no)=>{reject=no;}));
 act(()=>{void hook.result.current.refresh();});
 view.rerender(<Mot3DCampaignFlow {...props} {...{[slot]:hook.result.current}}/>);
 expect(screen.queryAllByRole("button",{name:/^Review /})).toHaveLength(0);
 await act(()=>reject(new Error("Status transport unavailable")));
 view.rerender(<Mot3DCampaignFlow {...props} {...{[slot]:hook.result.current}}/>);
 expect(hook.result.current.status).toBeTruthy(); // retained historical evidence
 expect(hook.result.current.state).toBe("terminal");
 expect(screen.queryAllByRole("button",{name:/^Review /})).toHaveLength(0);
 fetch.mockResolvedValueOnce(reply(status));await act(()=>hook.result.current.refresh());
 view.rerender(<Mot3DCampaignFlow {...props} {...{[slot]:hook.result.current}}/>);
 expect(screen.queryAllByRole("button",{name:/^Review /})).toHaveLength(1);
 expect(fetch.mock.calls.filter(([path])=>String(path).endsWith('/confirm'))).toHaveLength(1);
 expect(fetch.mock.calls.filter(([path])=>String(path).endsWith('/preview'))).toHaveLength(1);
});
