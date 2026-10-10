// The brain's words for its notes, shared by the graph, the note sheet and
// the lists.

export type NoteKind = "day" | "strategy" | "symbol" | "lesson" | "proposal";

export const KIND_LABEL: Record<NoteKind, string> = {
  day: "Day",
  strategy: "Strategy",
  symbol: "Symbol",
  lesson: "Lesson",
  proposal: "Proposal",
};

/** A badge's tone for a lesson's status or a proposal's state. */
export function statusTone(status: string): string | undefined {
  return ({ hunch: "warn", rule: "up", open: "link", accepted: "up" } as Record<string, string>)[
    status
  ];
}

export function statusLabel(status: string): string {
  return status === "not_held" ? "Not held" : status[0]?.toUpperCase() + status.slice(1);
}

/** "Held 7 of 9"; "Not checked yet" with none. */
export function heldText(checks: number | null | undefined, held: number | null | undefined) {
  if (!checks) return "Not checked yet";
  return `Held ${held ?? 0} of ${checks}`;
}

/** Where a note's own record lives elsewhere in the app, when it has one. */
export function recordHref(kind: NoteKind, key: string): { href: string; label: string } | null {
  if (kind === "day") return { href: `/brain/days/${key}`, label: "Open day" };
  if (kind === "lesson") return { href: `/brain/lessons/${key}`, label: "Open lesson" };
  if (kind === "proposal") return { href: `/brain/proposals/${key}`, label: "Open proposal" };
  if (kind === "strategy") return { href: `/strategies/${key}`, label: "Open strategy" };
  if (kind === "symbol") {
    const [exchange, ...rest] = key.split(":");
    const symbol = rest.join(":");
    if (!exchange || !symbol) return null;
    return { href: `/symbols/${exchange}/${encodeURIComponent(symbol)}`, label: "Open symbol" };
  }
  return null;
}

/** A wikilink's target among the notes a note links to: their graph anchor. */
export function wikiHref(
  links: { kind: string; key: string; note_id: string; title: string }[],
): (ref: { kind: string; key: string }) => { href: string; title: string } | null {
  const byRef = new Map(links.map((l) => [`${l.kind}:${l.key}`, l]));
  return (ref) => {
    const note = byRef.get(`${ref.kind}:${ref.key}`);
    return note ? { href: `#${note.note_id}`, title: note.title } : null;
  };
}

/** A note's own page: a day's, lesson's or proposal's page; a strategy or symbol in the graph. */
export function noteHref(note: { kind: string; key: string; note_id: string }): string {
  if (note.kind === "day") return `/brain/days/${note.key}`;
  if (note.kind === "lesson") return `/brain/lessons/${note.note_id}`;
  if (note.kind === "proposal") return `/brain/proposals/${note.note_id}`;
  return `/brain#${note.note_id}`;
}

/** A lesson check's answer in words, and its badge's tone. */
export const OUTCOME: Record<string, { label: string; tone?: string }> = {
  held: { label: "Held", tone: "up" },
  not_held: { label: "Didn't hold", tone: "down" },
  not_tested: { label: "Not tested" },
};

/** What a check is about: "Run of Straddle" or "Order SB-12, by hand". */
export function subjectText(
  subject: { run_id?: string | null; order_id?: string | null; strategy_id?: string | null },
  names: Map<string, string>,
): string {
  if (subject.run_id) {
    const name = subject.strategy_id ? names.get(subject.strategy_id) : undefined;
    return name ? `Run of ${name}` : "Run of a deleted strategy";
  }
  return `Order ${subject.order_id ?? ""} outside a strategy`;
}

/** Wikilinks on a page outside the graph: each to its note's own page. */
export function pageHref(
  links: { kind: string; key: string; note_id: string; title: string }[],
): (ref: { kind: string; key: string }) => { href: string; title: string } | null {
  const byRef = new Map(links.map((l) => [`${l.kind}:${l.key}`, l]));
  return (ref) => {
    const note = byRef.get(`${ref.kind}:${ref.key}`);
    return note ? { href: noteHref(note), title: note.title } : null;
  };
}

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "Mon 21 Sep" from "2026-09-21", as the server titles day notes. */
export function dayTitle(iso: string): string {
  const day = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(day.getTime())) return iso;
  return `${WEEKDAYS[day.getUTCDay()]} ${day.getUTCDate()} ${MONTHS[day.getUTCMonth()]}`;
}
