import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { createStream, type Stream, type Tick } from "../../src/stream/connection";

class FakeSocket {
  static all: FakeSocket[] = [];
  sent: unknown[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: ((e: { code: number }) => void) | null = null;
  closed = false;
  constructor(readonly url: string) {
    FakeSocket.all.push(this);
  }
  send(data: string) {
    this.sent.push(JSON.parse(data));
  }
  close() {
    this.closed = true;
  }
  open() {
    this.onopen?.();
  }
  receive(message: object) {
    this.onmessage?.({ data: JSON.stringify(message) });
  }
  drop(code = 1006) {
    this.onclose?.({ code });
  }
}

const last = () => FakeSocket.all[FakeSocket.all.length - 1] as FakeSocket;
const tick = (symbol: string, last_price: number): Tick => ({
  exchange: "NSE",
  symbol,
  last_price,
  change: null,
  change_pct: null,
  as_of: "2026-09-22T10:30:00+05:30",
  streamed: true,
});

let stream: Stream;
let polled: string[][];

beforeEach(() => {
  vi.useFakeTimers();
  FakeSocket.all = [];
  polled = [];
  stream = createStream({
    url: "ws://test/api/v1/stream",
    socket: (url) => new FakeSocket(url) as unknown as WebSocket,
    pollQuotes: async (keys) => {
      polled.push([...keys]);
      return keys.map((k) => tick(k.split(":")[1] as string, 1));
    },
    backoffMs: [100, 200],
    pollEveryMs: 2000,
  });
});

afterEach(() => {
  stream.close();
  vi.useRealTimers();
});

describe("stream connection", () => {
  test("subscriptions made in one turn go out as one message", async () => {
    last().open();
    stream.subscribe(["NSE:NIFTY 50"]);
    stream.subscribe(["BSE:SENSEX"]);
    await vi.advanceTimersByTimeAsync(0);

    expect(last().sent).toEqual([
      {
        type: "subscribe",
        instruments: [
          { exchange: "NSE", symbol: "NIFTY 50" },
          { exchange: "BSE", symbol: "SENSEX" },
        ],
      },
    ]);
  });

  test("ref-counts keys across components", async () => {
    last().open();
    const first = stream.subscribe(["NSE:NIFTY 50"]);
    const second = stream.subscribe(["NSE:NIFTY 50"]);
    await vi.advanceTimersByTimeAsync(0);
    first();
    await vi.advanceTimersByTimeAsync(0);
    expect(last().sent).toHaveLength(1);

    second();
    await vi.advanceTimersByTimeAsync(0);
    expect(last().sent[1]).toEqual({
      type: "unsubscribe",
      instruments: [{ exchange: "NSE", symbol: "NIFTY 50" }],
    });
  });

  test("delivers ticks and status to listeners, and goes live on open", () => {
    const ticks: Tick[] = [];
    const states: string[] = [];
    stream.onTicks((t) => ticks.push(...t));
    stream.onState((s) => states.push(s));
    const statuses: string[] = [];
    stream.onStatus((s) => statuses.push(s.state));

    last().open();
    last().receive({ type: "tick", ...tick("NIFTY 50", 24812.35) });
    last().receive({ type: "status", feed: { state: "live" } });

    expect(ticks.map((t) => t.last_price)).toEqual([24812.35]);
    expect(statuses).toEqual(["live"]);
    expect(states).toEqual(["live"]);
    expect(stream.state()).toBe("live");
  });

  test("resubscribes after reconnect", async () => {
    last().open();
    stream.subscribe(["NSE:NIFTY 50"]);
    await vi.advanceTimersByTimeAsync(0);
    last().drop();
    expect(stream.state()).toBe("connecting");

    await vi.advanceTimersByTimeAsync(100);
    expect(FakeSocket.all).toHaveLength(2);
    last().open();

    expect(last().sent).toEqual([
      { type: "subscribe", instruments: [{ exchange: "NSE", symbol: "NIFTY 50" }] },
    ]);
  });

  test("falls back to polling every 2s after 3 failures, and stops once back", async () => {
    stream.subscribe(["NSE:NIFTY 50"]);
    const ticks: Tick[] = [];
    stream.onTicks((t) => ticks.push(...t));
    last().drop();
    await vi.advanceTimersByTimeAsync(100);
    last().drop();
    await vi.advanceTimersByTimeAsync(200);
    last().drop();
    expect(stream.state()).toBe("polling");

    await vi.advanceTimersByTimeAsync(2000);
    expect(polled).toEqual([["NSE:NIFTY 50"]]);
    expect(ticks).toHaveLength(1);

    await vi.advanceTimersByTimeAsync(200);
    last().open();
    await vi.advanceTimersByTimeAsync(4000);
    expect(polled).toHaveLength(1);
    expect(stream.state()).toBe("live");
  });

  test("signed-out on 4401, and never reconnects", async () => {
    last().drop(4401);
    await vi.advanceTimersByTimeAsync(10_000);

    expect(stream.state()).toBe("signed-out");
    expect(FakeSocket.all).toHaveLength(1);
  });
});
