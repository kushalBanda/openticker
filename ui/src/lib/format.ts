// Numbers as Kite and Indian traders read them (DESIGN.md, Content & Voice):
// Indian digit grouping, an explicit sign on every change, hyphen-minus, and
// "—" for a value that is missing, never 0.

export const MISSING = "—";

type Num = number | null | undefined;

const grouped = (decimals: number) =>
  new Intl.NumberFormat("en-IN", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
const two = grouped(2);
const none = grouped(0);

function present(v: Num): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

/** 24,812.35 */
export function price(v: Num): string {
  return present(v) ? two.format(v) : MISSING;
}

/** ₹1,23,456.50; with `sign`, +₹6,976 / -₹6,975.85 */
export function rupees(v: Num, opts: { sign?: boolean; decimals?: 0 | 2 } = {}): string {
  if (!present(v)) return MISSING;
  const body = `₹${(opts.decimals === 0 ? none : two).format(Math.abs(v))}`;
  if (v < 0) return `-${body}`;
  return opts.sign && v > 0 ? `+${body}` : body;
}

/** +13.70 / -4.25 / 0.00 */
export function signed(v: Num, decimals = 2): string {
  if (!present(v)) return MISSING;
  const body = Math.abs(v).toFixed(decimals);
  if (v > 0) return `+${body}`;
  return v < 0 ? `-${body}` : body;
}

/** +13.70 (+0.47%), as Kite writes a change */
export function change(v: Num, pct: Num): string {
  if (!present(v)) return MISSING;
  return present(pct) ? `${signed(v)} (${signed(pct)}%)` : signed(v);
}

/** "up", "down" or undefined: pairs a colour with the sign already shown. */
export function direction(v: Num): "up" | "down" | undefined {
  if (!present(v) || v === 0) return undefined;
  return v > 0 ? "up" : "down";
}

const clock = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Asia/Kolkata",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
});

/** 11:42:07, exchange time */
export function istClock(at: Date): string {
  return clock.format(at);
}
