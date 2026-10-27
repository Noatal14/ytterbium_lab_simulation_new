import { useCallback, useEffect, useState } from "react";
import type { RecoverableRun } from "./individualRunRecovery";

/** A saved state is not evidence that this backend owns an active worker. */
export function localRunNeedsInspection(run: RecoverableRun | null) {
  return Boolean(
    run &&
    run.execution.mode === "local" &&
    !run.execution.locally_scheduled &&
    !run.execution.progress &&
    ["running", "outcome_unknown"].includes(run.record_state),
  );
}

export function useLocalRunInspection<Run extends RecoverableRun>(api: object) {
  const [inspectionRun, setInspectionRun] = useState<Run | null>(null);
  useEffect(() => {
    setInspectionRun(null);
  }, [api]);
  const holdForInspection = useCallback((run: Run) => {
    if (!localRunNeedsInspection(run)) return false;
    setInspectionRun(run);
    return true;
  }, []);
  return { inspectionRun, holdForInspection };
}

export function SavedLocalRunNotice({
  run,
  onInspect,
  disabled,
}: {
  run: RecoverableRun;
  onInspect: () => void;
  disabled: boolean;
}) {
  return (
    <section className="state-panel" role="status">
      <strong>Previous local run needs inspection</strong>
      <p>
        No active local worker could be verified for{" "}
        <code>{run.display_name}</code>. Its files are preserved and it has not
        been restarted. Inspect that run, or configure a separate simulation
        below.
      </p>
      <button
        type="button"
        className="secondary-button"
        onClick={onInspect}
        disabled={disabled}
      >
        Inspect saved run
      </button>
    </section>
  );
}
