import { render, screen, cleanup } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import contracts from "./teamContractFixture";
import { parseConfirmationSubmissionPreview } from "../api/schema/domain";
import { campaignConfirmationParticles } from "../api/campaignPolicy";
import { UI_ACCEPTANCE_POLICY } from "../generated/uiAcceptance.v1";
import { ConfirmationSubmissionView } from "../features/campaign/confirmation/ConfirmationSubmissionView";
import { CampaignPriorityPanel } from "../features/campaign/CampaignPriorityPanel";
import { campaignFixture } from "./campaignFixture";
// This component copy test uses a genuine public review DTO. Its particle count
// is not carried by that DTO: the closed mode's frozen policy owns the wording.
const preview=parseConfirmationSubmissionPreview(structuredClone(contracts.cases.find(x=>x.id==="confirmation-submit-preview")!.body.data) as Record<string,unknown>);
afterEach(()=>{cleanup();vi.unstubAllEnvs();});
it.each([["development",10_000,"10,000"],["ui-acceptance",UI_ACCEPTANCE_POLICY.mot_2d.stages.confirmation.particles_per_ensemble,"2"]] as const)("uses the reviewed %s particle workload in both final-review surfaces",(mode,count,label)=>{
 vi.stubEnv("MODE",mode);expect(campaignConfirmationParticles()).toBe(count);
 const noop=vi.fn();
 render(<ConfirmationSubmissionView enabled state="review" status={null} preview={preview} result={null} error="" onRefresh={noop} onReview={noop} onConfirm={noop} onReset={noop} onViewJobs={noop}/>);
 expect(screen.getByText(new RegExp('using '+label+' particles per ensemble'))).toBeVisible();
 cleanup();
 render(<CampaignPriorityPanel campaign={campaignFixture} transferState="idle" submissionState="idle" submissionResult={null} submissionError="" submissionTerminalCode={null} remoteState={null} remoteEvidenceFresh={false} screenSubmitState="idle" screenState={null} chainStatus={null} refinementLifecycle={null} confirmationSubmitState="review" copyStatus="" onCopyCommand={noop}/>);
 expect(screen.getByText(new RegExp('with '+label+' particles each'))).toBeVisible();
 if(mode==='ui-acceptance')expect(screen.queryByText(/10,000 particles/)).not.toBeInTheDocument();
 expect(noop).not.toHaveBeenCalled();
});
