import type { Schemas } from "../api/client";

// The live stream (ADR 32): one WebSocket per tab. Components subscribe to the
// instruments they show; the socket carries each price at once and every
// change after it, and every new audit log entry (who did what, from any
// process) within half a second. When the socket keeps failing, prices come from quotes
// every 2 s until it is back. Close code 4401 means the browser's session
// ended: nothing reconnects until the user signs in again.

export type Exchange = "NSE" | "BSE" | "NFO" | "BFO" | "MCX";
export type InstrumentKey = `${Exchange}:${string}`;
export type StreamState = "connecting" | "live" | "polling" | "signed-out";
export type FeedState = "live" | "quiet" | "closed" | "no-broker";

export interface Tick {
  exchange: Exchange;
  symbol: string;
  last_price: number;
  change: number | null;
  change_pct: number | null;
  as_of: string;
  streamed: boolean;
  /** Browser time it arrived (ms), set by the price store. */
  received?: number;
}

export interface FeedStatus {
  broker: string;
  broker_connected: boolean;
  broker_expires_at: string | null;
  last_tick_at: string | null;
  market_open: boolean;
  state: FeedState;
}

/** The first message on every connection: the server's clock and newest audit entry. */
export interface Hello {
  server_time: string;
  last_event_id: number;
}

/** An audit log entry, as the stream and `GET /api/v1/audit` send it. */
export type AuditEntry = Schemas["AuditEntryResult"];

export interface Stream {
  /** Wants these prices; returns the function that stops wanting them. */
  subscribe(keys: InstrumentKey[]): () => void;
  onTicks(fn: (ticks: Tick[]) => void): () => void;
  onStatus(fn: (status: FeedStatus) => void): () => void;
  onState(fn: (state: StreamState) => void): () => void;
  onHello(fn: (hello: Hello) => void): () => void;
  onEvent(fn: (entry: AuditEntry) => void): () => void;
  state(): StreamState;
  close(): void;
}

export interface StreamOptions {
  url: string;
  pollQuotes: (keys: InstrumentKey[]) => Promise<Tick[]>;
  socket?: (url: string) => WebSocket;
  backoffMs?: number[];
  pollEveryMs?: number;
}

const SIGNED_OUT = 4401;
const FAILURES_BEFORE_POLLING = 3;

export const keyOf = (t: { exchange: Exchange; symbol: string }): InstrumentKey =>
  `${t.exchange}:${t.symbol}`;

function ref(key: InstrumentKey) {
  const at = key.indexOf(":");
  return { exchange: key.slice(0, at) as Exchange, symbol: key.slice(at + 1) };
}

type Listener<T> = (value: T) => void;

function listeners<T>() {
  const all = new Set<Listener<T>>();
  return {
    add(fn: Listener<T>) {
      all.add(fn);
      return () => {
        all.delete(fn);
      };
    },
    emit(value: T) {
      for (const fn of all) fn(value);
    },
  };
}

export function createStream({
  url,
  pollQuotes,
  socket = (to) => new WebSocket(to),
  backoffMs = [500, 1000, 2000, 5000],
  pollEveryMs = 2000,
}: StreamOptions): Stream {
  const counts = new Map<InstrumentKey, number>();
  const pending = { add: new Set<InstrumentKey>(), remove: new Set<InstrumentKey>() };
  const ticks = listeners<Tick[]>();
  const statuses = listeners<FeedStatus>();
  const states = listeners<StreamState>();
  const hellos = listeners<Hello>();
  const events = listeners<AuditEntry>();
  let current: StreamState = "connecting";
  let ws: WebSocket | null = null;
  let open = false;
  let failures = 0;
  let closed = false;
  let flushQueued = false;
  let reconnect: ReturnType<typeof setTimeout> | undefined;
  let poll: ReturnType<typeof setInterval> | undefined;

  const setState = (next: StreamState) => {
    if (next === current) return;
    current = next;
    states.emit(next);
  };

  const send = (message: object) => {
    if (ws && open) ws.send(JSON.stringify(message));
  };

  const flush = () => {
    flushQueued = false;
    const add = [...pending.add].filter((k) => counts.has(k));
    const remove = [...pending.remove].filter((k) => !counts.has(k));
    pending.add.clear();
    pending.remove.clear();
    if (add.length) send({ type: "subscribe", instruments: add.map(ref) });
    if (remove.length) send({ type: "unsubscribe", instruments: remove.map(ref) });
  };

  const queue = () => {
    if (flushQueued) return;
    flushQueued = true;
    queueMicrotask(flush);
  };

  const stopPolling = () => {
    clearInterval(poll);
    poll = undefined;
  };

  const startPolling = () => {
    if (poll !== undefined) return;
    setState("polling");
    poll = setInterval(() => {
      const keys = [...counts.keys()];
      if (keys.length === 0) return;
      pollQuotes(keys)
        .then((got) => {
          if (poll !== undefined && got.length) ticks.emit(got);
        })
        .catch(() => undefined); // the next poll tries again
    }, pollEveryMs);
  };

  const connect = () => {
    if (closed) return;
    const next = socket(url);
    ws = next;
    open = false;
    next.onopen = () => {
      open = true;
      failures = 0;
      stopPolling();
      setState("live");
      pending.add.clear();
      pending.remove.clear();
      if (counts.size) send({ type: "subscribe", instruments: [...counts.keys()].map(ref) });
    };
    next.onmessage = (event: MessageEvent<string>) => {
      const message = JSON.parse(event.data) as { type: string } & Record<string, unknown>;
      if (message.type === "tick") {
        const { type: _, ...tick } = message;
        ticks.emit([tick as unknown as Tick]);
      } else if (message.type === "status") {
        statuses.emit(message.feed as FeedStatus);
      } else if (message.type === "event") {
        events.emit(message.entry as AuditEntry);
      } else if (message.type === "hello") {
        hellos.emit(message as unknown as Hello);
      }
    };
    next.onclose = (event: CloseEvent) => {
      if (ws !== next) return;
      ws = null;
      open = false;
      if (closed) return;
      if (event.code === SIGNED_OUT) {
        stopPolling();
        setState("signed-out");
        return;
      }
      failures += 1;
      if (failures >= FAILURES_BEFORE_POLLING) startPolling();
      else setState("connecting");
      const wait = backoffMs[Math.min(failures - 1, backoffMs.length - 1)] ?? 1000;
      reconnect = setTimeout(connect, wait);
    };
  };

  connect();

  return {
    subscribe(keys) {
      for (const key of keys) {
        const count = counts.get(key) ?? 0;
        counts.set(key, count + 1);
        if (count === 0) {
          pending.add.add(key);
          pending.remove.delete(key);
        }
      }
      queue();
      let done = false;
      return () => {
        if (done) return;
        done = true;
        for (const key of keys) {
          const count = (counts.get(key) ?? 1) - 1;
          if (count > 0) {
            counts.set(key, count);
          } else {
            counts.delete(key);
            pending.remove.add(key);
            pending.add.delete(key);
          }
        }
        queue();
      };
    },
    onTicks: ticks.add,
    onStatus: statuses.add,
    onState: states.add,
    onHello: hellos.add,
    onEvent: events.add,
    state: () => current,
    close() {
      closed = true;
      clearTimeout(reconnect);
      stopPolling();
      ws?.close();
    },
  };
}
