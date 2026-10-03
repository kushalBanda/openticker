// DESIGN.md motion tokens. Never ad-hoc durations.
export const duration = { fast: 0.12, base: 0.2, slow: 0.4 } as const;
export const ease = {
  out: [0.22, 1, 0.36, 1],
  inOut: [0.65, 0, 0.35, 1],
  in: [0.55, 0, 1, 0.45],
} as const;
export const spring = {
  snappy: { type: "spring", visualDuration: 0.2, bounce: 0 },
  soft: { type: "spring", visualDuration: 0.35, bounce: 0.1 },
} as const;
export const enter = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0 },
  transition: spring.soft,
} as const;
export const leave = { opacity: 0, y: 8, transition: { duration: duration.fast, ease: ease.in } };
