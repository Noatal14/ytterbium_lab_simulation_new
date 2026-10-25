import { act, render, renderHook, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import success from "../../../tests/contracts/v1/workflow_api_success.json";
import { createFinalizationApi, createProductionApi, createProductionSubmissionApi } from "../api/clients/production";
import { parseFinalizationPreview, parseFinalizationStatus, parseProductionPreview, parseProductionResult, parseProductionStatus, parseProductionSubmissionPreview, parseProductionSubmissionResult, parseProductionSubmissionStatus, parseZeusSnapshot } from "../api/schema/domain";
import { useProductionController } from "../features/campaign/controllers/useProductionController";
import { ProductionStage } from "../features/campaign/ProductionStage";
const data=(id:string)=>structuredClone(success.cases.find(x=>x.id===id)!.body.data) as Record<string,unknown>;
afterEach(()=>vi.unstubAllGlobals());
it.each([
  [createProductionApi,"production-preview","transition_outcome_unknown"],
  [createProductionSubmissionApi,"production-submit-preview","production_submission_outcome_unknown"],
  [createFinalizationApi,"finalization-preview","finalization_outcome_unknown"],
] as const)("consumes a %s review after a lost/malformed post-confirm response",async(create,id,code)=>{
  const api=create(async()=>"csrf");const profile=parseZeusSnapshot(data("zeus-snapshot")).profile;
  const preview=data(id);const campaign=(preview.campaign as {id:string}).id;
  const fetch=vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({api_version:1,data:preview}),{status:200})).mockResolvedValueOnce(new Response('{"api_version":1,"data":', {status:201}));vi.stubGlobal("fetch",fetch);
  const reviewed=await api.preview(campaign,profile);
  await expect(api.confirm(reviewed.preview_token)).rejects.toMatchObject({code,message:expect.stringMatching(/outcome is unknown.*Check.*Do not retry/)});
  await expect(api.confirm(reviewed.preview_token)).rejects.toThrow(/no longer active/);
  expect(fetch).toHaveBeenCalledTimes(2);
});
function setup() {
 const ready=parseFinalizationStatus(data("finalization-status"));
 const api={status:vi.fn().mockResolvedValue(parseProductionStatus(data("production-status"))),preview:vi.fn().mockResolvedValue(parseProductionPreview(data("production-preview"))),confirm:vi.fn().mockResolvedValue(parseProductionResult(data("production-confirm"))),reset:vi.fn()};
 const submissionApi={status:vi.fn().mockResolvedValue(parseProductionSubmissionStatus(data("production-submit-status"))),preview:vi.fn().mockResolvedValue(parseProductionSubmissionPreview(data("production-submit-preview"))),confirm:vi.fn().mockResolvedValue(parseProductionSubmissionResult(data("production-submit-confirm"))),reset:vi.fn()};
 const finalizationApi={status:vi.fn().mockResolvedValue(ready),preview:vi.fn().mockResolvedValue(parseFinalizationPreview(data("finalization-preview"))),confirm:vi.fn().mockRejectedValue(new Error("The operation outcome is unknown. Check the current campaign status. Do not retry or submit again automatically.")),reset:vi.fn()};
 const snapshot=parseZeusSnapshot(data("zeus-snapshot"));
 const hook=renderHook(()=>useProductionController({campaignId:ready.campaign.id,snapshot,enabled:true,api,submissionApi,finalizationApi}));
 return {hook,api,submissionApi,finalizationApi};
}
it("recovers finalization by status only after response loss without claiming a safe stop or resubmitting",async()=>{
 const {hook,api,submissionApi,finalizationApi}=setup();
 await act(()=>hook.result.current.preparation.review());await act(()=>hook.result.current.preparation.confirm());
 await act(()=>hook.result.current.submission.refresh());await act(()=>hook.result.current.finalization.refresh());
 const savedReview = hook.result.current.finalization.review;
 await act(()=>hook.result.current.finalization.review());await act(()=>hook.result.current.finalization.confirm());
 await act(()=>savedReview());
 expect(finalizationApi.preview).toHaveBeenCalledTimes(1);
 expect(hook.result.current.finalization.state).toBe("terminal");expect(hook.result.current.finalization.result).toBeNull();
 await act(()=>hook.result.current.finalization.confirm());expect(finalizationApi.confirm).toHaveBeenCalledTimes(1);
 const view=render(<ProductionStage visible flow={hook.result.current} onViewJobs={vi.fn()}/>);
 expect(screen.getByRole("alert")).toHaveTextContent("Finalization could not be verified");
 expect(screen.getByRole("alert")).not.toHaveTextContent("stopped safely");
 expect(screen.queryByRole("button",{name:"Finalize campaign"})).not.toBeInTheDocument();
 let rejectStatus!: (error: Error) => void;
 finalizationApi.status.mockReturnValueOnce(new Promise((_resolve, reject)=>{rejectStatus=reject;}));
 await userEvent.click(screen.getByRole("button",{name:"Check current status"}));
 view.rerender(<ProductionStage visible flow={hook.result.current} onViewJobs={vi.fn()}/>);
 expect(hook.result.current.finalization.state).toBe("checking");
 await act(()=>savedReview());
 expect(finalizationApi.preview).toHaveBeenCalledTimes(1);
 expect(screen.queryByRole("button",{name:"Review final results"})).not.toBeInTheDocument();
 await act(()=>hook.result.current.finalization.review());
 expect(finalizationApi.preview).toHaveBeenCalledTimes(1);
 await act(async()=>rejectStatus(new Error("Status read unavailable")));
 view.rerender(<ProductionStage visible flow={hook.result.current} onViewJobs={vi.fn()}/>);
 expect(screen.getByRole("button",{name:"Check current status"})).toBeEnabled();
 await act(()=>savedReview());
 expect(finalizationApi.preview).toHaveBeenCalledTimes(1);
 expect(screen.queryByRole("button",{name:"Review final results"})).not.toBeInTheDocument();
 expect(screen.queryByRole("button",{name:"Finalize campaign"})).not.toBeInTheDocument();
 await act(()=>hook.result.current.finalization.review());
 expect(finalizationApi.preview).toHaveBeenCalledTimes(1);
 const complete=data("finalization-status");complete.campaign={...(complete.campaign as object),stage:"complete"};(complete.production as Record<string,unknown>).status="campaign_complete";complete.next_action="none";complete.results=data("finalization-confirm").results;
 finalizationApi.status.mockResolvedValue(parseFinalizationStatus(complete));
 await userEvent.click(screen.getByRole("button",{name:"Check current status"}));
 view.rerender(<ProductionStage visible flow={hook.result.current} onViewJobs={vi.fn()}/>);
 expect(screen.getByRole("heading",{name:"Sealed final results"})).toBeVisible();
 expect(finalizationApi.confirm).toHaveBeenCalledTimes(1);expect(finalizationApi.preview).toHaveBeenCalledTimes(1);expect(submissionApi.confirm).not.toHaveBeenCalled();expect(api.confirm).toHaveBeenCalledTimes(1);
});

it.each([["inspection_failed","transition_outcome_unknown"],["source_inspection_failed","transition_outcome_unknown"],["invalid_csrf","invalid_csrf"]])("handles %s after confirm without a duplicate POST",async(code,expected)=>{
 const api=createProductionApi(async()=>"csrf");const preview=data("production-preview");const profile=parseZeusSnapshot(data("zeus-snapshot")).profile;
 const fetch=vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({api_version:1,data:preview}),{status:200})).mockResolvedValueOnce(new Response(JSON.stringify({error:{code,message:"Internal inspection failed safely."}}),{status:code==="invalid_csrf"?403:500}));vi.stubGlobal("fetch",fetch);
 const reviewed=await api.preview((preview.campaign as {id:string}).id,profile);
 await expect(api.confirm(reviewed.preview_token)).rejects.toMatchObject({code:expected});
 await expect(api.confirm(reviewed.preview_token)).rejects.toThrow(/no longer active/);expect(fetch).toHaveBeenCalledTimes(2);
});

it("keeps Production submission Review disabled after uncertain confirmation then failed status",async()=>{
 const {hook,submissionApi}=setup();
 await act(()=>hook.result.current.preparation.review());await act(()=>hook.result.current.preparation.confirm());
 await act(()=>hook.result.current.submission.refresh());await act(()=>hook.result.current.submission.review());
 submissionApi.confirm.mockRejectedValueOnce(new Error("Unknown submission outcome"));
 await act(()=>hook.result.current.submission.confirm());
 submissionApi.status.mockRejectedValueOnce(new Error("Status unavailable"));await act(()=>hook.result.current.submission.refresh());
 render(<ProductionStage visible flow={hook.result.current} onViewJobs={vi.fn()}/>);
 expect(screen.getByRole("button",{name:"Review Production job"})).toBeDisabled();
 expect(screen.getByRole("button",{name:"Check Zeus status"})).toBeEnabled();
});

it.each(["outputs_invalid", "held", "failed", "status_unknown"] as const)("keeps %s final outputs visibly blocked with read-only recovery controls", async lifecycle => {
 const {hook,finalizationApi}=setup();
 const raw=data("finalization-status");
 const production=raw.production as Record<string,unknown>,scheduler=production.scheduler as Record<string,unknown>;
 production.status=lifecycle;
 scheduler.state=({outputs_invalid:"completed_success",held:"held",failed:"completed_failed",status_unknown:"unknown"} as const)[lifecycle];
 scheduler.counts={queued:0,running:0,held:lifecycle==="held"?20:0,succeeded:lifecycle==="outputs_invalid"?20:0,failed:lifecycle==="failed"?20:0};
 raw.validation={status:lifecycle==="outputs_invalid"?"invalid":"not_ready",completed_ensembles:0,expected_ensembles:20};raw.next_action="wait";
 finalizationApi.status.mockResolvedValue(parseFinalizationStatus(raw));
 await act(()=>hook.result.current.preparation.review());await act(()=>hook.result.current.preparation.confirm());
 await act(()=>hook.result.current.submission.refresh());await act(()=>hook.result.current.finalization.refresh());
 expect(hook.result.current.finalization.state).toBe("terminal");expect(hook.result.current.finalization.error).toBe("");
 const jobs=vi.fn();render(<ProductionStage visible flow={hook.result.current} onViewJobs={jobs}/>);
 expect(screen.getByRole("alert")).toBeVisible();
 expect(screen.getByRole("alert")).toHaveTextContent(({outputs_invalid:"Sealed Production outputs failed validation",held:"Production job is held",failed:"Production job failed",status_unknown:"Production job status is unknown"} as const)[lifecycle]);
 if(lifecycle==="outputs_invalid")expect(screen.getByRole("alert")).toHaveTextContent("0 of 20 output ensembles");
 expect(screen.queryByRole("button",{name:"Review final results"})).not.toBeInTheDocument();
 expect(screen.queryByRole("button",{name:"Finalize campaign"})).not.toBeInTheDocument();
 expect(screen.queryByRole("heading",{name:"Sealed final results"})).not.toBeInTheDocument();
 await userEvent.click(screen.getByRole("button",{name:"View Zeus jobs"}));expect(jobs).toHaveBeenCalledTimes(1);
 await userEvent.click(screen.getByRole("button",{name:"Check current status"}));expect(finalizationApi.status).toHaveBeenCalledTimes(2);
 expect(finalizationApi.preview).not.toHaveBeenCalled();expect(finalizationApi.confirm).not.toHaveBeenCalled();
});
