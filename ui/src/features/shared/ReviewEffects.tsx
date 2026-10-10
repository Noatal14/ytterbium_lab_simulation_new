import { CheckCircle2 } from "lucide-react";
import type { ReactNode } from "react";

export function ReviewEffects({ effects }: { effects: ReactNode[] }) {
  return <ul className="effect-list">{effects.map((effect, index) => <li key={index}><CheckCircle2 aria-hidden="true" /> {effect}</li>)}</ul>;
}
