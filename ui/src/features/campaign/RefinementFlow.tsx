import { useEffect, useRef } from "react";
import type {
  RefinementChainStatus,
  RefinementSubmissionPreview,
  RefinementSubmissionResult,
} from "../../api/clients/refinement";
import type {
  ChainLifecycleCheck,
  ChainUiState,
} from "./controllers/useRefinementController";
import { RefinementStatusSection } from "./refinement/RefinementStatusSection";
import { RefinementSubmissionView } from "./refinement/RefinementSubmissionView";
export function RefinementFlow(props: {
  visible: boolean;
  status: RefinementChainStatus | null;
  check: ChainLifecycleCheck;
  state: ChainUiState;
  preview: RefinementSubmissionPreview | null;
  result: RefinementSubmissionResult | null;
  error: string;
  onRefresh: () => void;
  onPreview: () => void;
  onConfirm: () => void;
  onReset: () => void;
  onViewJobs: () => void;
}) {
  const button = useRef<HTMLButtonElement>(null),
    heading = useRef<HTMLHeadingElement>(null),
    panel = useRef<HTMLDivElement>(null),
    previous = useRef(props.state);
  useEffect(() => {
    if (props.state === "review") heading.current?.focus();
    else if (["submitted", "blocked", "error"].includes(props.state))
      panel.current?.focus();
    else if (props.state === "idle" && previous.current === "review")
      button.current?.focus();
    previous.current = props.state;
  }, [props.state]);
  if (!props.visible) return null;
  return (
    <>
      <RefinementStatusSection
        status={props.status}
        check={props.check}
        state={props.state}
        error={props.error}
        panel={panel}
        onRefresh={props.onRefresh}
        onReset={props.onReset}
        onViewJobs={props.onViewJobs}
      />
      <RefinementSubmissionView
        status={props.status}
        state={props.state}
        preview={props.preview}
        result={props.result}
        button={button}
        heading={heading}
        panel={panel}
        onPreview={props.onPreview}
        onConfirm={props.onConfirm}
        onReset={props.onReset}
        onViewJobs={props.onViewJobs}
      />
    </>
  );
}
