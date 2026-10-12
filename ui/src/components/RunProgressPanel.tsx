import type { RunProgress } from "../api/clients/individualZeeman";

export function RunProgressPanel({ progress }: { progress: RunProgress | null }) {
  if (!progress) return <div className="run-progress run-progress--indeterminate" role="status"><div className="run-progress__track"><span /></div><p>Waiting for reliable particle progress from the simulation engine.</p></div>;
  const percent = Math.min(100, Math.max(0, 100 * progress.fraction));
  return <div className="run-progress" role="status"><div className="run-progress__summary"><strong>{percent.toFixed(0)}%</strong><span>{progress.completed_particles.toLocaleString()} of {progress.total_particles.toLocaleString()} particles</span><span>Runtime {progress.runtime_s.toFixed(0)} s</span></div><div className="run-progress__track" role="progressbar" aria-label={`Simulation ${percent.toFixed(0)} percent complete`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(percent)}><span style={{ width: `${percent}%` }} /></div></div>;
}
