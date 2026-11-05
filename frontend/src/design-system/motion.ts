export type MotionPreset = "instant" | "fast" | "standard" | "deliberate";

export const motionDurationMs = {
  instant: 120,
  fast: 160,
  standard: 220,
  deliberate: 280
} as const satisfies Record<MotionPreset, number>;

export const motionDurationSeconds = {
  instant: 0.12,
  fast: 0.16,
  standard: 0.22,
  deliberate: 0.28
} as const satisfies Record<MotionPreset, number>;

export const motionDistance = {
  feedback: 4,
  enter: 8,
  panel: 48
} as const;

export const motionEase = {
  css: {
    productive: "cubic-bezier(0.2, 0, 0, 1)",
    emphasized: "cubic-bezier(0.2, 0.8, 0.2, 1)"
  },
  framer: {
    productive: [0.2, 0, 0, 1] as const,
    emphasized: [0.2, 0.8, 0.2, 1] as const
  },
  gsap: {
    productive: "power2.out",
    emphasized: "power3.out"
  }
} as const;

export const cssMotionVariable = {
  duration: {
    instant: "var(--motion-duration-instant)",
    fast: "var(--motion-duration-fast)",
    standard: "var(--motion-duration-standard)",
    deliberate: "var(--motion-duration-deliberate)"
  },
  distance: {
    feedback: "var(--motion-distance-xs)",
    enter: "var(--motion-distance-sm)",
    panel: "var(--motion-distance-panel)"
  },
  ease: {
    productive: "var(--motion-ease-productive)",
    emphasized: "var(--motion-ease-emphasized)"
  }
} as const;

export const framerTransition = (preset: MotionPreset = "standard", reducedMotion = false) => ({
  duration: reducedMotion ? 0.1 : motionDurationSeconds[preset],
  ease: motionEase.framer.productive
});

export const crmEntranceMotion = {
  totalDuration: 0.44,
  itemDuration: motionDurationSeconds.standard,
  returnDuration: motionDurationSeconds.fast,
  reducedDuration: 0.1,
  distance: motionDistance.enter,
  stagger: 0.035,
  maxStaggerItems: 6,
  ease: motionEase.gsap.productive
} as const;

