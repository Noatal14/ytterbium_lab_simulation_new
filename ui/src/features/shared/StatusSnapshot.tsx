import { LoaderCircle, RefreshCw } from "lucide-react";
import type { ReactNode } from "react";

export function StatusSnapshot({ source, checkedAt, checking, onRefresh, refreshLabel, liveText, children }: { source: string; checkedAt: ReactNode; checking: boolean; onRefresh: () => void; refreshLabel: string; liveText: string; children?: ReactNode }) {
  return <><div className="remote-status-toolbar"><div><strong>{source}</strong><p>{checkedAt}</p></div><button className="secondary-button" type="button" disabled={checking} onClick={onRefresh}>{checking ? <><LoaderCircle aria-hidden="true" /> Checking…</> : <><RefreshCw aria-hidden="true" /> {refreshLabel}</>}</button></div><div className="sr-only" aria-live="polite">{liveText}</div>{children}</>;
}
