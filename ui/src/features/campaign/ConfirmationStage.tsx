import { useEffect, useRef } from "react";
import type {
  ConfirmationPreview,
  ConfirmationResult,
  RefinementLifecycle,
} from "../../api/clients/refinement";
import type {
  ConfirmationLifecycleCheck,
  ConfirmationUiState,
} from "./controllers/useConfirmationController";
import { ConfirmationLifecycleSection } from "./confirmation/ConfirmationLifecycleSection";
import { ConfirmationPreparationView } from "./confirmation/ConfirmationPreparationView";
export function ConfirmationStage(props: {
  visible: boolean;
  lifecycle: RefinementLifecycle | null;
  lifecycleCheck: ConfirmationLifecycleCheck;
  state: ConfirmationUiState;
  preview: ConfirmationPreview | null;
  result: ConfirmationResult | null;
  error: string;
  onRefresh: () => void;
  onPreview: () => void;
  onConfirm: () => void;
  onReset: () => void;
  onViewJobs: () => void;
}) {
  const lifecycleHeading = useRef<HTMLHeadingElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const previousLifecycleCheck = useRef(props.lifecycleCheck);
  const previousState = useRef(props.state);
  useEffect(() => {
    if (
      props.lifecycleCheck === "ready" &&
      previousLifecycleCheck.current !== "ready"
    )
      lifecycleHeading.current?.focus();
    previousLifecycleCheck.current = props.lifecycleCheck;
  }, [props.lifecycleCheck]);
  useEffect(() => {
    const previous = previousState.current;
    if (props.state === "review") heading.current?.focus();
    else if (["success", "terminal"].includes(props.state) || props.error)
      panel.current?.focus();
    else if (props.state === "idle" && previous === "review")
      button.current?.focus();
    previousState.current = props.state;
  }, [props.state, props.error]);
  if (!props.visible) return null;
  return (
    <>
      <ConfirmationLifecycleSection
        lifecycle={props.lifecycle}
        lifecycleCheck={props.lifecycleCheck}
        error={props.error}
        lifecycleHeading={lifecycleHeading}
        panel={panel}
        onRefresh={props.onRefresh}
        onViewJobs={props.onViewJobs}
      />
      <ConfirmationPreparationView
        lifecycle={props.lifecycle}
        state={props.state}
        preview={props.preview}
        result={props.result}
        error={props.error}
        lifecycleCheck={props.lifecycleCheck}
        heading={heading}
        button={button}
        panel={panel}
        onPreview={props.onPreview}
        onConfirm={props.onConfirm}
        onReset={props.onReset}
        onViewJobs={props.onViewJobs}
      />
    </>
  );
}
