// What the app does with each audit log entry (decision 17): a must-act one
// raises a banner and a toast, a worth-knowing one a toast, and every one is
// kept in Activity and the bell. Plain functions of the entry, so the stream,
// the bell and the Activity page read an event the same way.

import type { AuditEntry } from "../stream/connection";
import { instrumentName, price, qty, rupees, type Source, signed, sourceLabel } from "./format";
import { contractOf } from "./strategies";

export type Tier = "must-act" | "worth-knowing" | "record";
export type Tone = "up" | "down" | "warn" | "accent" | undefined;

/** A run ended by these needs the user: it is locked, or something broke. */
const MUST_ACT_STOPS = new Set([
  "kill",
  "daily_loss_limit",
  "tick_stale",
  "recovery_failed",
  "error",
]);

const RECORDS = new Set([
  "OrderPlaced",
  "OrderModified",
  "OrderCancelled",
  "InstrumentSyncCompleted",
  "ScriptStarted",
  "AgentJobStarted",
  "BrokerConnected",
  "BrokerDisconnected",
  "ChargeRatesChecked",
  "PaperAccountReset",
]);

type Details = Record<string, unknown>;

const text = (d: Details, key: string): string => {
  const value = d[key];
  return typeof value === "string" ? value : value == null ? "" : String(value);
};
const num = (d: Details, key: string): number | null =>
  typeof d[key] === "number" ? (d[key] as number) : null;

export function tierOf(entry: AuditEntry): Tier {
  const d = entry.details;
  if (entry.event_type === "BrokerSessionExpired") return "must-act";
  if (entry.event_type === "StrategyStopped" && MUST_ACT_STOPS.has(text(d, "reason"))) {
    return "must-act";
  }
  return RECORDS.has(entry.event_type) ? "record" : "worth-knowing";
}

/** NIFTY OCT FUT, NIFTY SEP 24800 CE, RELIANCE: as the rest of the app names it. */
export function symbolName(symbol: string): string {
  const contract = contractOf(symbol);
  return instrumentName(symbol, "NSE", contract.type, contract.expiry, contract.strike).name;
}

const sideWord = (d: Details) => (text(d, "side") === "SELL" ? "Sell" : "Buy");
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
const words = (reason: string) => reason.replaceAll("_", " ");

export interface Described {
  kind: string; // the badge: Fill, Order, Kill, ...
  tone: Tone;
  text: string; // one line: what happened
}

/** One entry as a row, a toast or a bell item says it. `names` maps strategy ids to names. */
export function describe(
  entry: AuditEntry,
  names: ReadonlyMap<string, string> = new Map(),
): Described {
  const d = entry.details;
  const symbol = symbolName(text(d, "symbol"));
  const strategy = names.get(text(d, "strategy_id")) ?? (text(d, "name") || "A strategy");
  switch (entry.event_type) {
    case "OrderPlaced":
      return {
        kind: "Order",
        tone: "accent",
        text: `${sideWord(d)} ${qty(num(d, "quantity"))} ${symbol} placed`,
      };
    case "OrderFilled":
      return {
        kind: "Fill",
        tone: "up",
        text: `${sideWord(d)} ${qty(num(d, "quantity"))} ${symbol} at ${price(num(d, "price"))}`,
      };
    case "OrderFailed":
      return { kind: "Rejected", tone: "down", text: `${symbol}: ${text(d, "reason")}` };
    case "OrderModified":
      return {
        kind: "Order",
        tone: undefined,
        text: `${symbol} order changed: ${text(d, "change")}`,
      };
    case "OrderCancelled": {
      const reason = text(d, "reason");
      const why = reason && reason !== "cancelled" ? `: ${reason}` : "";
      return { kind: "Cancelled", tone: undefined, text: `${symbol} order cancelled${why}` };
    }
    case "RiskBreached":
      return { kind: "Risk", tone: "warn", text: `${symbol}: ${text(d, "detail")}` };
    case "PositionSettled":
      return {
        kind: "Settled",
        tone: undefined,
        text: `${symbol} settled at ${price(num(d, "price"))}, ${signed(num(d, "realized_pnl"))}`,
      };
    case "InstrumentSyncCompleted":
      return {
        kind: "Broker",
        tone: undefined,
        text: `${qty(num(d, "count"))} instruments synced from ${cap(text(d, "broker"))}`,
      };
    case "BrokerSessionExpired":
      return {
        kind: "Expired",
        tone: "down",
        text: `${cap(text(d, "broker"))} session expired: live prices stopped`,
      };
    case "BrokerConnected":
      return { kind: "Broker", tone: "accent", text: `${cap(text(d, "broker"))} connected` };
    case "BrokerDisconnected":
      return {
        kind: "Broker",
        tone: undefined,
        text: `${cap(text(d, "broker"))} disconnected: live prices stopped`,
      };
    case "ChargeRatesChecked": {
      const differing = num(d, "differing") ?? 0;
      return {
        kind: "Charges",
        tone: differing ? "warn" : undefined,
        text: differing
          ? `Charges checked: ${differing} of ${text(d, "checked")} orders differ from ${cap(text(d, "broker"))}`
          : `Charges checked: ${text(d, "checked")} orders match ${cap(text(d, "broker"))}'s contract note`,
      };
    }
    case "PaperAccountReset":
      return {
        kind: "Reset",
        tone: "down",
        text: `Paper account reset to ${rupees(num(d, "capital"))}: ${qty(num(d, "orders"))} orders, ${qty(num(d, "trades"))} trades deleted`,
      };
    case "ChargeRatesDiffer":
      return {
        kind: "Charges",
        tone: "warn",
        text: `Charges differ from ${cap(text(d, "broker"))}'s contract note on ${text(d, "differing")} of ${text(d, "checked")} orders`,
      };
    case "StrategyStarted":
      return { kind: "Strategy", tone: "accent", text: `${strategy} started: ${text(d, "legs")}` };
    case "StrategyLegClosed":
      return {
        kind: "Leg",
        tone: undefined,
        text: `${strategy}: ${symbol} closed, ${words(text(d, "reason"))}, ${signed(num(d, "realized_pnl"))}`,
      };
    case "StrategyStopped": {
      const reason = text(d, "reason");
      const pnl = num(d, "realized_pnl");
      const detail = text(d, "detail") || words(reason);
      if (reason === "kill") {
        return { kind: "Kill", tone: "down", text: `${strategy} killed: ${detail}` };
      }
      return {
        kind: MUST_ACT_STOPS.has(reason) ? "Stopped" : "Ended",
        tone: MUST_ACT_STOPS.has(reason) ? "down" : undefined,
        text: `${strategy} stopped: ${detail}${pnl === null ? "" : `, ${rupees(pnl, { sign: true })}`}`,
      };
    }
    case "ScriptStarted":
      return { kind: "Script", tone: undefined, text: `${text(d, "name")} started` };
    case "ScriptExited": {
      const reason = text(d, "reason");
      const fine = reason === "exited" || reason === "stopped" || reason === "schedule";
      return {
        kind: "Script",
        tone: fine ? undefined : "down",
        text: `${text(d, "name")} ${fine ? "ended" : "failed"}: ${text(d, "detail") || words(reason)}`,
      };
    }
    case "AgentJobStarted":
      return {
        kind: "Review",
        tone: undefined,
        text: `Review of ${strategy} started (${text(d, "harness") === "codex" ? "Codex" : "Claude"})`,
      };
    case "AgentJobEnded": {
      const done = text(d, "reason") === "finished";
      return {
        kind: "Review",
        tone: done ? undefined : "down",
        text: done
          ? `Review of ${text(d, "strategy_name")} answered`
          : `Review of ${text(d, "strategy_name")} ended: ${text(d, "detail") || words(text(d, "reason"))}`,
      };
    }
    default:
      return { kind: entry.event_type, tone: undefined, text: "" };
  }
}

/** Who did it, as the By column says it: a strategy or alert by name when known. */
export function byLabel(entry: AuditEntry, names: ReadonlyMap<string, string> = new Map()): string {
  const [, id = ""] = (entry.triggered_by ?? "").split(":");
  const source = entry.source as Source;
  if (source === "strategy") return names.get(id) ?? (text(entry.details, "name") || "A strategy");
  if (source === "alert") {
    const name = names.get(id);
    return name ? `Alert → ${name}` : "An alert";
  }
  if (entry.event_type.startsWith("AgentJob")) return "Review job";
  return sourceLabel(source);
}

/** The strategy an entry is about, for its Open link. */
export function strategyOf(entry: AuditEntry): string | null {
  const id = entry.details.strategy_id;
  return typeof id === "string" ? id : null;
}

type Key = readonly unknown[];

/** The cached reads an entry makes stale; each is a query key prefix. */
export function queriesToInvalidate(entry: AuditEntry): Key[] {
  const type = entry.event_type;
  const orders: Key[] = [
    ["orders"],
    ["positions"],
    ["funds"],
    ["trades"],
    ["today"],
    ["setup"],
    ["pnl-history"],
    ["charges-summary"],
  ];
  if (type.startsWith("Order") || type === "PositionSettled") return orders;
  if (type === "PaperAccountReset") return [[]]; // every page's numbers
  if (type === "BrokerConnected" || type === "BrokerDisconnected") return [["broker-session"]];
  if (type === "InstrumentSyncCompleted") return [["instruments-status"]];
  if (type === "ChargeRatesChecked") return [["account"]];
  if (type.startsWith("Strategy")) {
    const id = strategyOf(entry);
    return [
      ...orders,
      ["strategies"],
      ...(id
        ? [
            ["strategy", id],
            ["ledger", id],
            ["signals", id],
          ]
        : []),
    ];
  }
  if (type.startsWith("AgentJob")) {
    const id = strategyOf(entry);
    return [
      ["strategies"],
      ...(id
        ? [
            ["reviews", id],
            ["strategy", id],
          ]
        : []),
    ];
  }
  return [];
}

// The Activity page's filters: kinds of event, and who did it.
export type KindFilter = "all" | "orders" | "strategies" | "scripts" | "risk" | "broker" | "agents";

export const KINDS: Record<Exclude<KindFilter, "all">, string[]> = {
  orders: [
    "OrderPlaced",
    "OrderFilled",
    "OrderFailed",
    "OrderModified",
    "OrderCancelled",
    "PositionSettled",
  ],
  strategies: ["StrategyStarted", "StrategyLegClosed", "StrategyStopped"],
  scripts: ["ScriptStarted", "ScriptExited"],
  risk: ["RiskBreached"],
  broker: [
    "BrokerSessionExpired",
    "BrokerConnected",
    "BrokerDisconnected",
    "InstrumentSyncCompleted",
    "ChargeRatesChecked",
    "ChargeRatesDiffer",
    "PaperAccountReset",
  ],
  agents: ["AgentJobStarted", "AgentJobEnded"],
};

/** What the bell lists: everything but records. */
export const BELL_KINDS = Object.values(KINDS)
  .flat()
  .filter((type) => !RECORDS.has(type));

export type WhoFilter =
  | "anyone"
  | "you"
  | "claude-code"
  | "codex"
  | "strategy"
  | "script"
  | "alert";

export type Range = "today" | "7d" | "30d";

/** The first exchange-local day a range covers, YYYY-MM-DD, counted from `now`. */
export function fromDate(range: Range, now: Date): string {
  const back = range === "today" ? 0 : range === "7d" ? 6 : 29;
  const day = new Date(now.getTime() + 5.5 * 3_600_000 - back * 86_400_000);
  return day.toISOString().slice(0, 10);
}
