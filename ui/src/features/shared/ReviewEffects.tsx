import { CheckCircle2 } from "lucide-react";
import type { ReactNode } from "react";

export function ReviewEffects({ children }: { children: ReactNode[] }) {
  return <ul className="effect-list">{children.map((child, index) => <li key={index}><CheckCircle2 aria-hidden="true" /> {child}</li>)}</ul>;
}
