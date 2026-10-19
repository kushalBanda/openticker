// The exchange's day (ADR 13): NSE and BSE trade 09:15 to 15:30 IST, which
// is UTC+05:30 all year. Every time-box the app draws (a chart's session
// axis, the manager's rail, candle buckets) counts from these.

export const IST_OFFSET_MS = 330 * 60_000;

/** Minutes since midnight, exchange-local. */
export const OPEN = 9 * 60 + 15;
export const CLOSE = 15 * 60 + 30;

/** "09:15" as minutes since midnight. */
export function toMinutes(hhmm: string): number {
  const [h, m] = hhmm.split(":").map(Number);
  return (h ?? 0) * 60 + (m ?? 0);
}

/** Minutes since midnight as "09:15". */
export function toClock(minutes: number): string {
  return `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
}

/** An instant moved to the exchange's clock, read with getUTC*. */
export function istShift(at: string | Date): Date {
  return new Date(new Date(at).getTime() + IST_OFFSET_MS);
}

/** Minutes since midnight, IST, of an instant. */
export function istMinutes(at: string | Date): number {
  const shifted = istShift(at);
  return shifted.getUTCHours() * 60 + shifted.getUTCMinutes();
}

/** The exchange-local date of a moment, "2026-10-15". */
export function istDay(at: string | Date): string {
  return istShift(at).toISOString().slice(0, 10);
}

/** Every `step`-th minute of the session as "HH:MM", open to close inclusive. */
export function sessionMinutes(step = 1): string[] {
  const out: string[] = [];
  for (let t = OPEN; t <= CLOSE; t += step) out.push(toClock(t));
  return out;
}

/** Where a minute of the day falls along the session, 0 at the open, 1 at the close. */
export function sessionAt(minutes: number): number {
  return Math.min(1, Math.max(0, (minutes - OPEN) / (CLOSE - OPEN)));
}
