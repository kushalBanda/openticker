import { createContext, useContext, useEffect, useSyncExternalStore } from "react";
import { type InstrumentKey, keyOf, type Stream, type Tick } from "./connection";

// The newest price per instrument. Components read it through usePrice, which
// re-renders only the component whose price changed.

export interface PriceStore {
  get(key: InstrumentKey): Tick | undefined;
  apply(ticks: Tick[]): void;
  subscribe(fn: () => void): () => void;
}

export function createPriceStore(): PriceStore {
  const prices = new Map<InstrumentKey, Tick>();
  const listeners = new Set<() => void>();
  return {
    get: (key) => prices.get(key),
    apply(ticks) {
      for (const tick of ticks) prices.set(keyOf(tick), tick);
      for (const fn of listeners) fn();
    },
    subscribe(fn) {
      listeners.add(fn);
      return () => {
        listeners.delete(fn);
      };
    },
  };
}

export const StreamContext = createContext<{ stream: Stream; store: PriceStore } | null>(null);

export function useStream(): { stream: Stream; store: PriceStore } {
  const value = useContext(StreamContext);
  if (value === null) throw new Error("useStream needs a StreamContext provider");
  return value;
}

/** The live price of one instrument, subscribed while the component is mounted. */
export function usePrice(key: InstrumentKey): Tick | undefined {
  const { stream, store } = useStream();
  useEffect(() => stream.subscribe([key]), [stream, key]);
  return useSyncExternalStore(store.subscribe, () => store.get(key));
}
