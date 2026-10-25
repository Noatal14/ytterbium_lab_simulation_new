import { useEffect, useRef, useState } from "react";

type RecoveryStep = {
  ready: boolean;
  refresh: () => Promise<void>;
};

/** Orchestrate the existing controllers' read-only status checks, once per opening
 * and connection identity. No preparation, preview, confirm or submission here.
 * A later check is eligible only when its controller's prerequisites are restored.
 */
export function useMot2DRecovery(identity: string | null, steps: RecoveryStep[], paused = false) {
  const attempted = useRef(new Set<number>());
  const busy = useRef(false);
  const generation = useRef(0);
  const [checking, setChecking] = useState(false);
  const [, changed] = useState(0);
  useEffect(() => {
    generation.current++;
    attempted.current.clear();
    busy.current = false;
    setChecking(false);
    return () => {
      // This ref is a request epoch, not a mounted DOM node.
      // eslint-disable-next-line react-hooks/exhaustive-deps
      generation.current++;
    };
  }, [identity]);
  useEffect(() => {
    if (paused) {
      // Once the operator starts a review, leave the rest to explicit controls.
      // A later cancel/confirm must not restart recovery and clear that review.
      steps.forEach((_, index) => attempted.current.add(index));
      return;
    }
    if (!identity || busy.current) return;
    const index = steps.findIndex((_, i) => !attempted.current.has(i));
    if (index < 0 || !steps[index].ready) return;
    const current = generation.current;
    // Defer until the controllers' identity/enabled reset effects have settled;
    // cleanup also prevents a duplicate request in React StrictMode.
    const timer = window.setTimeout(() => {
      attempted.current.add(index);
      busy.current = true;
      setChecking(true);
      void steps[index].refresh().finally(() => {
        if (generation.current !== current) return;
        busy.current = false;
        setChecking(false);
        changed(v => v + 1);
      });
    }, 0);
    return () => window.clearTimeout(timer);
  }, [identity, paused, steps]);
  return { checking };
}
