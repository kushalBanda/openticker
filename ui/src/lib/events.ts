// What the app does with each audit log entry (decision 17): a must-act one
// raises a banner and a toast, a worth-knowing one a toast, and every one is
// kept in Activity and the bell. Plain functions of the entry, so the stream,
// the bell and the Activity page read an event the same way.

import type { AuditEntry } from "../stream/connection";
import { dayTitle, statusLabel } from "./brain";
import {
  chatLabel,
  instrumentName,
  price,
  qty,
  rupees,
  type Source,
  signed,
  sourceLabel,
} from "./format";
import { isWake, wakeLabel } from "./manager";
import { istDay } from "./session";
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
  "WatchlistChanged",
  "LessonWritten",
  "ProposalDecided",
  "BrainNoteEdited",
  "AgentSettingsChanged",
  "AgentChatStarted",
  "AgentChatDeleted",
  "ManagerNumbersChanged",
  "ManagerWoke",
  "ManagerPlanSet",
  "ManagerSwitched",
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
  if (entry.event_type === "ManagerStalled") return "must-act";
  if (entry.event_type === "StrategyStopped" && MUST_ACT_STOPS.has(text(d, "reason"))) {
    return "must-act";
  }
  // A chat's reply is worth a toast: the shell holds it back while that chat is on screen.
  // The desk manager's own wakes that finished are on its page: a record.
  if (entry.event_type === "AgentJobEnded" && text(d, "kind") === "chat") {
    return text(d, "reason") === "finished" && isWake(text(d, "trigger"))
      ? "record"
      : "worth-knowing";
  }
  // A debrief job's own end already says its debrief is in; a quiet day is a record.
  if (entry.event_type === "DebriefWritten") {
    return d.quiet === true || (entry.triggered_by ?? "").startsWith("debrief:")
      ? "record"
      : "worth-knowing";
  }
  return RECORDS.has(entry.event_type) ? "record" : "worth-knowing";
}

/** The chat an agent job's end belongs to, for its toast's Open. */
export function chatOf(entry: AuditEntry): string | null {
  if (entry.event_type !== "AgentJobEnded") return null;
  const thread = text(entry.details, "thread_id");
  return thread || null;
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
    case "WatchlistChanged":
      return { kind: "Watchlist", tone: undefined, text: watchlistText(d) };
    case "ManagerWoke":
      return {
        kind: "Manager",
        tone: undefined,
        text: `Manager woke: ${wakeLabel(text(d, "reason"))}`,
      };
    case "ManagerPlanSet":
      return { kind: "Manager", tone: "accent", text: `Manager's plan: ${text(d, "text")}` };
    case "ManagerStalled":
      return {
        kind: "Manager",
        tone: "down",
        text:
          text(d, "why") === "capped"
            ? "Manager used its wakes for today"
            : "Manager stalled: its turns keep failing",
      };
    case "ManagerSwitched":
      return {
        kind: "Manager",
        tone: undefined,
        text: d.enabled === true ? "Manager turned on" : "Manager turned off",
      };
    case "ManagerNumbersChanged":
      return { kind: "Manager", tone: d.kept_yours ? "warn" : undefined, text: managerLineText(d) };
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
    case "AgentJobStarted": {
      // Older entries have no title: they were all reviews.
      const title = text(d, "title") || `Review of ${strategy}`;
      return {
        kind: jobKind(d),
        tone: undefined,
        text: `${title} started (${text(d, "harness") === "codex" ? "Codex" : "Claude"})`,
      };
    }
    case "AgentJobEnded": {
      const done = text(d, "reason") === "finished";
      if (text(d, "kind") === "chat" && text(d, "thread_id")) {
        const chat = `“${text(d, "title")}”`;
        return {
          kind: "Chat",
          tone: done ? undefined : "down",
          text: done
            ? `Answered in ${chat}`
            : `${chat} ended: ${text(d, "detail") || words(text(d, "reason"))}`,
        };
      }
      const title = text(d, "title") || `Review of ${text(d, "strategy_name")}`;
      return {
        kind: jobKind(d),
        tone: done ? undefined : "down",
        text: done
          ? `${title} ${text(d, "kind") === "debrief" ? "is in" : "answered"}`
          : `${title} ended: ${text(d, "detail") || words(text(d, "reason"))}`,
      };
    }
    case "DebriefWritten": {
      const day = dayTitle(text(d, "trading_date"));
      return d.quiet === true
        ? { kind: "Debrief", tone: undefined, text: `${day} was quiet: ${text(d, "headline")}` }
        : { kind: "Debrief", tone: undefined, text: `Debrief of ${day}: ${text(d, "headline")}` };
    }
    case "LessonWritten":
      return {
        kind: "Lesson",
        tone: undefined,
        text: `${text(d, "change") === "created" ? "New lesson" : "Lesson changed"}: ${text(d, "title")}`,
      };
    case "LessonStatusChanged":
      return { kind: "Lesson", tone: lessonTone(text(d, "status")), text: lessonText(d) };
    case "ProposalRaised":
      return {
        kind: "Proposal",
        tone: "accent",
        text: `Proposed for ${proposalStrategy(d, names)}: ${text(d, "change")}`,
      };
    case "ProposalDecided": {
      const decision = text(d, "decision");
      const reason = text(d, "reason");
      const what = `${proposalStrategy(d, names)}: ${text(d, "change")}`;
      return {
        kind: "Proposal",
        tone: undefined,
        text:
          decision === "accept"
            ? `${what} accepted`
            : decision === "reject"
              ? `${what} rejected${reason ? ` (“${reason}”)` : ""}`
              : `${what} put off`,
      };
    }
    case "BrainNoteEdited":
      return { kind: "Note", tone: undefined, text: `Your note on ${text(d, "title")} changed` };
    case "AgentSettingsChanged":
      return { kind: "Agents", tone: undefined, text: `Agent settings: ${text(d, "summary")}` };
    case "AgentChatStarted":
      return { kind: "Chat", tone: undefined, text: `Chat started: ${text(d, "title")}` };
    case "AgentChatDeleted":
      return { kind: "Chat", tone: undefined, text: `Chat deleted: ${text(d, "title")}` };
    default:
      return { kind: entry.event_type, tone: undefined, text: "" };
  }
}

function lessonTone(status: string): Tone {
  return status === "rule"
    ? "up"
    : status === "retired"
      ? "down"
      : status === "hunch"
        ? "warn"
        : undefined;
}

function lessonText(d: Details): string {
  const title = text(d, "title");
  const status = statusLabel(text(d, "status")).toLowerCase();
  const reason = text(d, "reason");
  if (text(d, "override") === "retired" && text(d, "status") === "retired") {
    return `${title} retired by hand${reason ? `: ${reason}` : ""}`;
  }
  const checks = num(d, "checks") ?? 0;
  const counted = checks ? `, held ${num(d, "held") ?? 0} of ${checks}` : "";
  return `${title}: ${statusLabel(text(d, "previous")).toLowerCase()} → ${status}${counted}`;
}

function proposalStrategy(d: Details, names: ReadonlyMap<string, string>): string {
  return names.get(text(d, "strategy_id")) ?? "a strategy";
}

function jobKind(d: Details): string {
  const kind = text(d, "kind");
  return kind === "debrief" ? "Debrief" : kind === "chat" ? "Chat" : "Review";
}

function watchlistText(d: Details): string {
  const name = text(d, "name");
  const symbols = Array.isArray(d.symbols) ? d.symbols.map((s) => symbolName(String(s))) : [];
  switch (text(d, "change")) {
    case "added":
      return `${symbols.join(", ")} added to ${name}`;
    case "removed":
      return `${symbols.join(", ")} removed from ${name}`;
    case "renamed":
      return `Watchlist ${text(d, "previous_name")} renamed ${name}`;
    case "deleted":
      return `Watchlist ${name} deleted`;
    default:
      return `Watchlist ${name} made`;
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
  if (entry.event_type.startsWith("AgentJob")) {
    return text(entry.details, "kind") === "chat" ? "Your agent" : `${jobKind(entry.details)} job`;
  }
  return chatLabel(entry.triggered_by) ?? sourceLabel(source);
}

/** The strategy an entry is about, for its Open link. */
export function strategyOf(entry: AuditEntry): string | null {
  const id = entry.details.strategy_id;
  return typeof id === "string" && id ? id : null;
}

/** The brain page an entry is about, for its Open link: a day, a lesson or a proposal. */
export function brainPageOf(entry: AuditEntry): string | null {
  const d = entry.details;
  switch (entry.event_type) {
    case "DebriefWritten":
      return text(d, "trading_date") ? `/brain/days/${text(d, "trading_date")}` : null;
    case "LessonWritten":
    case "LessonStatusChanged":
      return text(d, "lesson_id") ? `/brain/lessons/${text(d, "lesson_id")}` : null;
    case "ProposalRaised":
    case "ProposalDecided":
      return text(d, "proposal_id") ? `/brain/proposals/${text(d, "proposal_id")}` : null;
    case "BrainNoteEdited":
      return text(d, "note_id") ? `/brain#${text(d, "note_id")}` : null;
    default:
      return null;
  }
}

/** The trading day a debrief job's entry is about, for its Open link. */
export function dayOf(entry: AuditEntry): string | null {
  if (!entry.event_type.startsWith("AgentJob") || entry.details.kind !== "debrief") return null;
  const day = entry.details.subject;
  return typeof day === "string" && day ? day : null;
}

/** The page an entry is about, for a link to it: its chat, brain page,
 * strategy, day, script, the orders or the watchlist. */
export function pageOf(entry: AuditEntry): string | null {
  const chat = chatOf(entry);
  if (chat) return `/agents/${chat}`;
  const page = brainPageOf(entry);
  if (page) return page;
  const strategy = strategyOf(entry);
  if (strategy) return `/strategies/${strategy}`;
  const day = dayOf(entry);
  if (day) return `/brain/days/${day}`;
  const script = text(entry.details, "script_id");
  if (entry.event_type.startsWith("Script") && script) return `/scripts/${script}`;
  if (entry.event_type.startsWith("Order")) return "/orders";
  if (entry.event_type === "WatchlistChanged") return "/watchlist";
  if (entry.event_type.startsWith("Manager")) return "/manager";
  return null;
}

/** The chat whose agent recorded an entry: "chat:claude:thr_1" is thr_1's. */
export function chatThreadOf(entry: AuditEntry): string | null {
  const match = /^chat:[a-z]+:(.+)$/.exec(entry.triggered_by ?? "");
  return match?.[1] ?? null;
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
  // Every page's numbers: a reset changes them all, and a login or logout
  // changes what every read of the broker can answer.
  if (type === "PaperAccountReset" || type === "BrokerConnected" || type === "BrokerDisconnected")
    return [[]];
  if (type === "InstrumentSyncCompleted") return [["instruments-status"]];
  if (type === "ChargeRatesChecked") return [["account"]];
  if (type === "WatchlistChanged") return [["watchlists"]];
  if (type.startsWith("Manager")) return [["manager"]];
  if (type === "AgentSettingsChanged") return [["agent-settings"]];
  if (type.startsWith("AgentChat")) return [["agent-threads"]];
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
  if (BRAIN_EVENTS.has(type)) return [["brain"]];
  if (type.startsWith("AgentJob")) {
    const id = strategyOf(entry);
    // Reviews and debriefs are chats too (ADR 40): the rail and the open one.
    const threads = [["agent-threads"]];
    // The desk manager's wakes are chat turns (ADR 41): its page shows them.
    if (text(entry.details, "kind") === "chat") threads.push(["manager"]);
    if (dayOf(entry)) return [["agent-jobs"], ["brain"], ...threads];
    return [
      ...threads,
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
export type KindFilter =
  | "all"
  | "orders"
  | "strategies"
  | "scripts"
  | "risk"
  | "broker"
  | "agents"
  | "brain";

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
  agents: [
    "AgentJobStarted",
    "AgentJobEnded",
    "AgentChatStarted",
    "AgentChatDeleted",
    "AgentSettingsChanged",
    "ManagerNumbersChanged",
    "ManagerWoke",
    "ManagerPlanSet",
    "ManagerSwitched",
    "ManagerStalled",
  ],
  brain: [
    "DebriefWritten",
    "LessonWritten",
    "LessonStatusChanged",
    "ProposalRaised",
    "ProposalDecided",
    "BrainNoteEdited",
  ],
};

const BRAIN_EVENTS = new Set(KINDS.brain);

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
  | "alert"
  | "manager";

export type Range = "today" | "7d" | "30d";

/** The first exchange-local day a range covers, YYYY-MM-DD, counted from `now`. */
export function fromDate(range: Range, now: Date): string {
  const back = range === "today" ? 0 : range === "7d" ? 6 : 29;
  return istDay(new Date(now.getTime() - back * 86_400_000));
}

/** "Manager: Straddle at ₹6,00,000, stop -₹6,000"; a line the user set that
 * the manager wanted otherwise says so. */
export function managerLineText(d: Details): string {
  const key = text(d, "key");
  const what =
    key === "desk" ? "the desk" : key === "own" ? "its own trades" : text(d, "name") || key;
  const capital = num(d, "capital");
  const stop = num(d, "stop");
  const numbers = [
    capital === null ? null : `${rupees(capital, { decimals: 0 })}`,
    stop === null ? "no stop" : `stop ${rupees(stop, { decimals: 0 })}`,
  ]
    .filter(Boolean)
    .join(", ");
  if (d.kept_yours) return `Manager kept your numbers for ${what}; it wanted ${numbers}`;
  const who = text(d, "set_by") === "you" ? "You set" : "Manager set";
  return `${who} ${what}: ${numbers}`;
}
