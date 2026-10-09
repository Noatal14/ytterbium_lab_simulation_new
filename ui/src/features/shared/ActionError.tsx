import { AlertTriangle } from "lucide-react";
import type { ReactNode, RefObject } from "react";

export function ActionError({ title, message, panelRef, action }: { title: string; message: string; panelRef?: RefObject<HTMLDivElement>; action?: ReactNode }) {
  return <div ref={panelRef} className="state-panel state-panel--error" role="alert" tabIndex={-1}><AlertTriangle aria-hidden="true" /><div><strong>{title}</strong><p>{message}</p>{action}</div></div>;
}

export function ManualVerification({ title, message, onViewJobs, panelRef }: { title: string; message: string; onViewJobs: () => void; panelRef?: RefObject<HTMLDivElement> }) {
  return <ActionError title={title} message={message} panelRef={panelRef} action={<button className="secondary-button compact-action" type="button" onClick={onViewJobs}>View Zeus jobs</button>} />;
}
