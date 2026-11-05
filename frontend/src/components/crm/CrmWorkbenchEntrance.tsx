import { useGSAP } from "@gsap/react";
import { gsap } from "gsap";
import type { RefObject } from "react";

import { crmEntranceMotion } from "../../design-system/motion";

gsap.registerPlugin(useGSAP);

export const CRM_WORKBENCH_INTRO_STORAGE_KEY = "demo:crm-workbench-intro-seen";

type CrmWorkbenchEntranceProps = {
  scopeRef: RefObject<HTMLElement | null>;
};

function hasSeenWorkbenchIntro() {
  try {
    return window.sessionStorage.getItem(CRM_WORKBENCH_INTRO_STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

function markWorkbenchIntroSeen() {
  try {
    window.sessionStorage.setItem(CRM_WORKBENCH_INTRO_STORAGE_KEY, "1");
  } catch {
    // Session storage can be unavailable in restricted browser contexts.
  }
}

export function CrmWorkbenchEntrance({ scopeRef }: CrmWorkbenchEntranceProps) {
  useGSAP(() => {
    const root = scopeRef.current;
    if (!root) return;

    const targets = gsap.utils
      .toArray<HTMLElement>("[data-crm-enter]", root)
      .slice(0, crmEntranceMotion.maxStaggerItems);
    if (root.dataset.motionState === "skipped") {
      root.dataset.motionState = "complete";
      markWorkbenchIntroSeen();
      return;
    }
    const media = gsap.matchMedia();

    media.add(
      {
        reduceMotion: "(prefers-reduced-motion: reduce)",
        allowMotion: "(prefers-reduced-motion: no-preference)"
      },
      (context) => {
        const reduced = Boolean(context.conditions?.reduceMotion);
        const mode = reduced ? "reduced" : hasSeenWorkbenchIntro() ? "repeat" : "full";
        root.dataset.motionState = mode;

        const complete = () => {
          if (!root.isConnected) return;
          root.dataset.motionState = "complete";
          if (mode === "full") markWorkbenchIntroSeen();
        };

        if (targets.length === 0) {
          complete();
          return;
        }

        if (mode === "reduced") {
          gsap.fromTo(
            targets,
            { autoAlpha: 0 },
            {
              autoAlpha: 1,
              duration: crmEntranceMotion.reducedDuration,
              ease: "none",
              clearProps: "opacity,visibility",
              onComplete: complete
            }
          );
          return;
        }

        if (mode === "repeat") {
          gsap.fromTo(
            targets,
            { autoAlpha: 0 },
            {
              autoAlpha: 1,
              duration: crmEntranceMotion.returnDuration,
              ease: "power1.out",
              clearProps: "opacity,visibility",
              onComplete: complete
            }
          );
          return;
        }

        const timeline = gsap.timeline({
          defaults: { ease: crmEntranceMotion.ease },
          onComplete: complete
        });
        timeline.fromTo(
          targets,
          { autoAlpha: 0, y: crmEntranceMotion.distance, willChange: "transform,opacity" },
          {
            autoAlpha: 1,
            y: 0,
            duration: crmEntranceMotion.itemDuration,
            stagger: crmEntranceMotion.stagger,
            clearProps: "transform,opacity,visibility,willChange"
          },
          0
        );
      },
      root
    );

    return () => {
      media.revert();
      root.dataset.motionState = "complete";
    };
  }, { scope: scopeRef });

  return null;
}
