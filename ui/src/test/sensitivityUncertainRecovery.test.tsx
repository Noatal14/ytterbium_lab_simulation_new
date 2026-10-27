import { act,render,screen } from "@testing-library/react";
import { renderHook } from "@testing-library/react";
import { expect,it,vi } from "vitest";
import success from "./teamContractFixture";
import { parseZeusSnapshot,parseSensitivityStatus,parseSensitivityPreview,parseSensitivityResult,parseSensitivitySubmissionStatus,parseSensitivitySubmissionPreview } from "../api/schema/domain";
import { useSensitivityController } from "../features/campaign/controllers/useSensitivityController";
import { SensitivityStage } from "../features/campaign/SensitivityStage";
const data=(id:string)=>structuredClone(success.cases.find(x=>x.id===id)!.body.data) as Record<string,unknown>;
it.each(["preparation","submission"] as const)("Sensitivity %s does not offer stale Review after unknown then failed status",async(operation)=>{
 const ready=parseSensitivityStatus(data("sensitivity-status"));
 const api={status:vi.fn().mockResolvedValue(ready),preview:vi.fn().mockResolvedValue(parseSensitivityPreview(data("sensitivity-preview"))),confirm:vi.fn().mockResolvedValue(parseSensitivityResult(data("sensitivity-confirm"))),reset:vi.fn()};
 const submissionApi={status:vi.fn().mockResolvedValue(parseSensitivitySubmissionStatus(data("sensitivity-submit-status"))),preview:vi.fn().mockResolvedValue(parseSensitivitySubmissionPreview(data("sensitivity-submit-preview"))),confirm:vi.fn().mockRejectedValue(new Error("Unknown outcome")),reset:vi.fn()};
 const snapshot=parseZeusSnapshot(data("zeus-snapshot"));const hook=renderHook(()=>useSensitivityController({campaignId:ready.campaign.id,snapshot,enabled:true,api,submissionApi}));
 if(operation==="submission") {await act(()=>hook.result.current.preparation.review());await act(()=>hook.result.current.preparation.confirm());}
 else api.confirm.mockRejectedValueOnce(new Error("Unknown outcome"));
 await act(()=>hook.result.current[operation].refresh());await act(()=>hook.result.current[operation].review());await act(()=>hook.result.current[operation].confirm());
 (operation==="preparation"?api:submissionApi).status.mockRejectedValueOnce(new Error("Status unavailable"));await act(()=>hook.result.current[operation].refresh());
 render(<SensitivityStage visible flow={hook.result.current} onViewJobs={vi.fn()}/>);
 if(operation==="preparation")expect(screen.queryByRole("button",{name:"Review Sensitivity preparation"})).not.toBeInTheDocument();
 else expect(screen.getByRole("button",{name:"Review Sensitivity job"})).toBeDisabled();
 const count=(operation==="preparation"?api:submissionApi).preview.mock.calls.length;await act(()=>hook.result.current[operation].review());expect((operation==="preparation"?api:submissionApi).preview).toHaveBeenCalledTimes(count);
});
