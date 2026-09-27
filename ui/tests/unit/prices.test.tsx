import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, test } from "vitest";
import type { InstrumentKey, Stream, Tick } from "../../src/stream/connection";
import { createPriceStore, StreamContext, usePrice } from "../../src/stream/prices";

const tick = (last_price: number): Tick => ({
  exchange: "NSE",
  symbol: "NIFTY 50",
  last_price,
  change: 10,
  change_pct: 0.04,
  as_of: "2026-09-22T10:30:00+05:30",
  streamed: true,
});

function fakeStream() {
  const wanted: InstrumentKey[][] = [];
  const released: InstrumentKey[][] = [];
  const stream = {
    subscribe(keys: InstrumentKey[]) {
      wanted.push(keys);
      return () => released.push(keys);
    },
  } as unknown as Stream;
  return { stream, wanted, released };
}

describe("price store", () => {
  test("keeps the newest tick per instrument and tells subscribers", () => {
    const store = createPriceStore();
    let told = 0;
    store.subscribe(() => {
      told += 1;
    });

    store.apply([tick(100), tick(101)]);

    expect(store.get("NSE:NIFTY 50")?.last_price).toBe(101);
    expect(told).toBe(1);
  });

  test("usePrice subscribes while mounted and follows ticks", () => {
    const store = createPriceStore();
    const { stream, wanted, released } = fakeStream();
    const wrapper = ({ children }: { children: ReactNode }) => (
      <StreamContext.Provider value={{ stream, store }}>{children}</StreamContext.Provider>
    );

    const { result, unmount } = renderHook(() => usePrice("NSE:NIFTY 50"), { wrapper });
    expect(result.current).toBeUndefined();
    expect(wanted).toEqual([["NSE:NIFTY 50"]]);

    act(() => store.apply([tick(24812.35)]));
    expect(result.current?.last_price).toBe(24812.35);

    unmount();
    expect(released).toEqual([["NSE:NIFTY 50"]]);
  });
});
