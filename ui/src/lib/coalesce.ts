/**
 * Runs `run` once, `ms` after the first of a burst of pushes: a debrief
 * writes a note, several checks and a lesson within a second or two, and
 * the brain's reads should refetch once for all of them, not for each.
 */
export function coalescer(run: () => void, ms: number) {
  let timer: ReturnType<typeof setTimeout> | undefined;
  return {
    push() {
      if (timer !== undefined) return;
      timer = setTimeout(() => {
        timer = undefined;
        run();
      }, ms);
    },
    cancel() {
      clearTimeout(timer);
      timer = undefined;
    },
  };
}
