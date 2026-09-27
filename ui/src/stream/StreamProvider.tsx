import { useQueryClient } from "@tanstack/react-query";
import { createContext, type ReactNode, useContext, useEffect, useState } from "react";
import { api, unwrap } from "../api/client";
import { keys } from "../api/queries";
import {
  createStream,
  type FeedStatus,
  type InstrumentKey,
  type Stream,
  type StreamState,
  type Tick,
} from "./connection";
import { createPriceStore, type PriceStore, StreamContext } from "./prices";

interface Live {
  status: FeedStatus | null;
  state: StreamState;
}

const LiveContext = createContext<Live>({ status: null, state: "connecting" });

/** Where prices come from now, and the socket's own state. */
export function useLive(): Live {
  return useContext(LiveContext);
}

function streamUrl(): string {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${window.location.host}/api/v1/stream`;
}

async function pollQuotes(broker: string, wanted: InstrumentKey[]): Promise<Tick[]> {
  const instruments = wanted.slice(0, 50).map((key) => {
    const at = key.indexOf(":");
    return { exchange: key.slice(0, at) as Tick["exchange"], symbol: key.slice(at + 1) };
  });
  const result = await unwrap(api.POST("/api/v1/quotes", { body: { broker, instruments } }));
  return result.quotes.map((q) => {
    const change = q.prev_close ? q.last_price - q.prev_close : null;
    return {
      exchange: q.exchange,
      symbol: q.symbol,
      last_price: q.last_price,
      change,
      change_pct: change !== null && q.prev_close ? (change / q.prev_close) * 100 : null,
      as_of: q.as_of,
      streamed: false,
    };
  });
}

function open(): { stream: Stream; store: PriceStore } {
  let broker = "zerodha";
  const stream = createStream({
    url: streamUrl(),
    pollQuotes: (wanted) => pollQuotes(broker, wanted),
  });
  stream.onStatus((status) => {
    broker = status.broker;
  });
  const store = createPriceStore();
  stream.onTicks((ticks) => store.apply(ticks));
  return { stream, store };
}

/** One stream for the signed-in app, opened on mount and closed on unmount. */
export function StreamProvider({ children }: { children: ReactNode }) {
  const client = useQueryClient();
  const [value, setValue] = useState<{ stream: Stream; store: PriceStore } | null>(null);
  const [live, setLive] = useState<Live>({ status: null, state: "connecting" });

  useEffect(() => {
    const opened = open();
    setValue(opened);
    const { stream } = opened;
    const offStatus = stream.onStatus((status) => setLive((now) => ({ ...now, status })));
    const offState = stream.onState((state) => {
      setLive((now) => ({ ...now, state }));
      if (state === "signed-out") client.setQueryData(keys.session, null);
    });
    return () => {
      offStatus();
      offState();
      stream.close();
    };
  }, [client]);

  if (value === null) return null;
  return (
    <StreamContext.Provider value={value}>
      <LiveContext.Provider value={live}>{children}</LiveContext.Provider>
    </StreamContext.Provider>
  );
}
