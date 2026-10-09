import type { ScreeningLifecycle } from "../../api/clients/screening";

export function ScreeningFacts({ lifecycle }: { lifecycle: ScreeningLifecycle }) {
  return <dl className="transfer-facts"><div><dt>Array tasks</dt><dd>{lifecycle.scheduler.task_count}</dd></div><div><dt>Queued</dt><dd>{lifecycle.scheduler.counts.queued}</dd></div><div><dt>Running</dt><dd>{lifecycle.scheduler.counts.running}</dd></div><div><dt>Succeeded</dt><dd>{lifecycle.scheduler.counts.succeeded}</dd></div><div><dt>Failed</dt><dd>{lifecycle.scheduler.counts.failed}</dd></div><div><dt>Validated trials</dt><dd>{lifecycle.validation.completed_trials} of {lifecycle.validation.expected_trials}</dd></div></dl>;
}
