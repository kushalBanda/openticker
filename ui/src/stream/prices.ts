import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
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
      const received = Date.now();
      for (const tick of ticks) prices.set(keyOf(tick), { ...tick, received });
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

/**
 * The live prices of several instruments, in the order asked. The array is
 * the same object until one of them changes.
 */
export function usePrices(keys: InstrumentKey[]): (Tick | undefined)[] {
  const { stream, store } = useStream();
  const joined = keys.join("|");
  // biome-ignore lint/correctness/useExhaustiveDependencies: `joined` stands for `keys`
  const wanted = useMemo(() => keys, [joined]);
  useEffect(() => (wanted.length ? stream.subscribe(wanted) : undefined), [stream, wanted]);
  const last = useRef<(Tick | undefined)[]>([]);
  const snapshot = () => {
    const now = wanted.map((key) => store.get(key));
    const same =
      now.length === last.current.length && now.every((tick, i) => tick === last.current[i]);
    if (!same) last.current = now;
    return last.current;
  };
  return useSyncExternalStore(store.subscribe, snapshot);
}

export const STALE_AFTER_MS = 60_000;

/**
 * True when a price is expected (`watching`) but none has arrived for a
 * minute; with none at all, counted from when the component mounted.
 */
export function useIsStale(tick: Tick | undefined, watching: boolean): boolean {
  const [since] = useState(() => Date.now());
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!watching) return;
    const timer = setInterval(() => setNow(Date.now()), 5_000);
    return () => clearInterval(timer);
  }, [watching]);
  if (!watching) return false;
  return now - Math.max(tick?.received ?? since, since) > STALE_AFTER_MS;
}
