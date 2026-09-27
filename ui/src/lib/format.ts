// Numbers as Kite and Indian traders read them (DESIGN.md, Content & Voice):
// Indian digit grouping, an explicit sign on every change, hyphen-minus, and
// "—" for a value that is missing, never 0.

export const MISSING = "—";

type Num = number | null | undefined;

const formats = new Map<number, Intl.NumberFormat>();
const grouped = (decimals: number) => {
  let format = formats.get(decimals);
  if (!format) {
    format = new Intl.NumberFormat("en-IN", {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    });
    formats.set(decimals, format);
  }
  return format;
};
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

/** +13.70 / -4.25 / 0.00 / +1,065.00 */
export function signed(v: Num, decimals = 2): string {
  if (!present(v)) return MISSING;
  const body = grouped(decimals).format(Math.abs(v));
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

const dayParts = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Asia/Kolkata",
  day: "numeric",
  month: "numeric",
  year: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

/** 22 Sep; with `time`, 22 Sep 10:18; with `year`, 22 Sep 26. Exchange time, Kite's months. */
export function istDate(at: string | Date, opts: { time?: boolean; year?: boolean } = {}): string {
  const parts = dayParts.formatToParts(new Date(at));
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  const month = MONTH_NAMES[Number(get("month")) - 1] ?? "";
  let text = `${get("day")} ${month}`;
  if (opts.year) text += ` ${get("year")}`;
  if (opts.time) text += ` ${get("hour")}:${get("minute")}`;
  return text;
}

const MONTH_NAMES = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

/** 6 Oct: a plain date ("2026-10-06"), an expiry, in Kite's months. */
export function dayMonth(iso: string): string {
  return `${Number(iso.slice(8, 10))} ${MONTH_NAMES[Number(iso.slice(5, 7)) - 1] ?? ""}`;
}

/** 1,500 / -75: quantities, no decimals. */
export function qty(v: Num): string {
  return present(v) ? none.format(v) : MISSING;
}

const MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];

function ordinal(day: number): string {
  if (day % 100 >= 11 && day % 100 <= 13) return `${day}th`;
  const suffix: Record<number, string> = { 1: "st", 2: "nd", 3: "rd" };
  return `${day}${suffix[day % 10] ?? "th"}`;
}

// OpenTicker's symbols: <underlying><DDMMMYY>FUT and <underlying><DDMMMYY><strike><CE|PE>.
const DERIVATIVE = /^(.+?)\d{2}[A-Z]{3}\d{2}(?:FUT|[\d.]+(?:CE|PE))$/;

export type InstrumentType = "EQ" | "FUT" | "CE" | "PE" | "INDEX";

/**
 * Kite's name for an instrument and its exchange tag: RELIANCE; NIFTY OCT FUT
 * NFO; NIFTY SEP 24800 CE NFO; a weekly option, NIFTY 7th w OCT 25000 CE.
 * NSE cash needs no tag.
 */
export function instrumentName(
  symbol: string,
  exchange: string,
  type?: InstrumentType,
  expiry?: string | null,
  strike?: number | null,
): { name: string; tag: string } {
  const tag = exchange === "NSE" ? "" : exchange;
  const underlying = DERIVATIVE.exec(symbol)?.[1];
  if (!type || type === "EQ" || type === "INDEX" || !expiry || !underlying) {
    return { name: symbol, tag };
  }
  const [year, month, day] = expiry.split("-").map(Number) as [number, number, number];
  const mon = MONTHS[month - 1] ?? "";
  if (type === "FUT") return { name: `${underlying} ${mon} FUT`, tag };
  // A monthly contract is the month's last expiry: a week later is next month.
  const monthly = new Date(Date.UTC(year, month - 1, day + 7)).getUTCMonth() !== month - 1;
  const when = monthly ? mon : `${ordinal(day)} w ${mon}`;
  const at = strike == null ? "" : ` ${Number.isInteger(strike) ? strike : strike.toFixed(2)}`;
  return { name: `${underlying} ${when}${at} ${type}`, tag };
}

export type Source =
  | "you"
  | "claude-code"
  | "codex"
  | "agent"
  | "strategy"
  | "alert"
  | "script"
  | "schedule"
  | "rest"
  | "system";

const SOURCES: Record<Source, string> = {
  you: "You",
  "claude-code": "Claude",
  codex: "Codex",
  agent: "An agent",
  strategy: "A strategy",
  alert: "An alert",
  script: "A script",
  schedule: "Schedule",
  rest: "REST API",
  system: "OpenTicker",
};

/** Who did it, as a row says it: You, Claude, Codex, ... */
export function sourceLabel(source: Source): string {
  return SOURCES[source];
}
