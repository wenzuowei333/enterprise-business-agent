import { lazy, Suspense, useEffect, type RefObject } from "react";

type CrmWorkbenchMotionControllerProps = {
  scopeRef: RefObject<HTMLElement | null>;
};

const FAIL_OPEN_DELAY_MS = 600;

function revealWorkbench(scopeRef: RefObject<HTMLElement | null>, state: "complete" | "skipped") {
  const root = scopeRef.current;
  if (!root) return;
  const currentState = root.dataset.motionState;
  if (currentState === "pending" || (state === "complete" && currentState === "skipped")) {
    root.dataset.motionState = state;
  }
}

function CrmWorkbenchEntranceUnavailable({ scopeRef }: CrmWorkbenchMotionControllerProps) {
  useEffect(() => {
    revealWorkbench(scopeRef, "complete");
  }, [scopeRef]);

  return null;
}

function CrmWorkbenchMotionFallback({ scopeRef }: CrmWorkbenchMotionControllerProps) {
  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      revealWorkbench(scopeRef, "skipped");
    }, FAIL_OPEN_DELAY_MS);

    return () => window.clearTimeout(timeoutId);
  }, [scopeRef]);

  return null;
}

const LazyCrmWorkbenchEntrance = lazy(async () => {
  try {
    const module = await import("./CrmWorkbenchEntrance");
    return { default: module.CrmWorkbenchEntrance };
  } catch {
    return { default: CrmWorkbenchEntranceUnavailable };
  }
});

export function CrmWorkbenchMotionController({ scopeRef }: CrmWorkbenchMotionControllerProps) {
  return (
    <Suspense fallback={<CrmWorkbenchMotionFallback scopeRef={scopeRef} />}>
      <LazyCrmWorkbenchEntrance scopeRef={scopeRef} />
    </Suspense>
  );
}
