import { useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useNavigate } from "react-router";
import { keys, useBell } from "../api/queries";
import { notifyDesktop } from "../lib/desktop";
import {
  BELL_KINDS,
  byLabel,
  describe,
  queriesToInvalidate,
  strategyOf,
  tierOf,
} from "../lib/events";
import { istClock } from "../lib/format";
import type { Strategy } from "../lib/strategies";
import type { AuditEntry } from "../stream/connection";
import { useStream } from "../stream/prices";
import { useToast } from "./toasts";

const READ_KEY = "ot.events.read";
const DISMISSED_KEY = "ot.events.dismissed";
/** Your own order that fills this soon after it was placed was said by the window that placed it. */
const OWN_FILL_MS = 5_000;

function load<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw === null ? fallback : (JSON.parse(raw) as T);
  } catch {
    return fallback;
  }
}

function save(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // private window or blocked storage: read state lasts this tab only
  }
}

interface Events {
  /** The bell's last 50, newest first. */
  entries: AuditEntry[] | undefined;
  unread: number;
  /** Unread must-act events not dismissed: the banners. */
  urgent: AuditEntry[];
  markAllRead(): void;
  dismiss(id: number): void;
  /** Strategy names by id, for "By" and event text. */
  names: ReadonlyMap<string, string>;
  /** Opens what an event is about, if anything. */
  openOf(entry: AuditEntry): { label: string; run: () => void } | null;
}

const EventsContext = createContext<Events | null>(null);

export function useEvents(): Events {
  const events = useContext(EventsContext);
  if (events === null) throw new Error("useEvents needs an EventsProvider");
  return events;
}

function useNames(): ReadonlyMap<string, string> {
  const client = useQueryClient();
  const [names, setNames] = useState<ReadonlyMap<string, string>>(new Map());
  useEffect(() => {
    const read = () => {
      const list = client.getQueryData<{ strategies: Strategy[] }>(keys.strategies);
      if (list) setNames(new Map(list.strategies.map((s) => [s.strategy_id, s.name])));
    };
    read();
    return client.getQueryCache().subscribe((event) => {
      if (event.query.queryKey[0] === keys.strategies[0] && event.type === "updated") read();
    });
  }, [client]);
  return names;
}

/**
 * The stream's events, as the app shows them (decision 17): each one
 * refetches what it changed; must-act ones raise a banner and a toast,
 * worth-knowing ones a toast; the bell counts what hasn't been read.
 */
export function EventsProvider({ children }: { children: ReactNode }) {
  const { stream } = useStream();
  const client = useQueryClient();
  const toast = useToast();
  const navigate = useNavigate();
  const bell = useBell(BELL_KINDS);
  const names = useNames();
  const [readUpTo, setReadUpTo] = useState<number | null>(() => load(READ_KEY, null));
  const [dismissed, setDismissed] = useState<number[]>(() => load(DISMISSED_KEY, []));
  const lastSeen = useRef<number | null>(null);
  const placed = useRef(new Map<string, number>());
  const namesRef = useRef(names);
  namesRef.current = names;

  const openOf = useCallback(
    (entry: AuditEntry) => {
      const strategy = strategyOf(entry);
      if (strategy) return { label: "Open", run: () => navigate(`/strategies/${strategy}`) };
      if (entry.event_type === "BrokerSessionExpired") {
        return { label: "Settings", run: () => navigate("/settings") };
      }
      if (entry.event_type.startsWith("Order")) {
        return { label: "Orders", run: () => navigate("/orders") };
      }
      return null;
    },
    [navigate],
  );

  useEffect(() => {
    const offHello = stream.onHello((hello) => {
      // A fresh browser starts with nothing unread.
      setReadUpTo((was) => {
        if (was !== null) return was;
        save(READ_KEY, hello.last_event_id);
        return hello.last_event_id;
      });
      // Back after a gap: what happened meanwhile is only in the log.
      if (lastSeen.current !== null && hello.last_event_id > lastSeen.current) {
        void client.invalidateQueries();
      }
      lastSeen.current = hello.last_event_id;
    });

    const offEvent = stream.onEvent((entry) => {
      lastSeen.current = entry.id;
      for (const key of [keys.audit, ...queriesToInvalidate(entry)]) {
        void client.invalidateQueries({ queryKey: key });
      }
      const orderId = entry.details.order_id;
      if (entry.event_type === "OrderPlaced" && typeof orderId === "string") {
        placed.current.set(orderId, Date.now());
      }
      const tier = tierOf(entry);
      if (tier === "record") return;
      if (entry.source === "you" && entry.event_type === "OrderFilled") {
        const at = typeof orderId === "string" ? placed.current.get(orderId) : undefined;
        if (at !== undefined && Date.now() - at < OWN_FILL_MS) return;
      }
      const said = describe(entry, namesRef.current);
      const by = byLabel(entry, namesRef.current);
      const open = openOf(entry);
      if (tier === "must-act") {
        notifyDesktop(`${said.kind} · OpenTicker`, said.text, () => open?.run());
      }
      toast({
        kind: said.kind,
        tone: said.tone,
        text: said.text,
        note: `${by === "You" ? "by you" : by} · ${istClock(new Date(entry.occurred_at))}`,
        urgent: tier === "must-act",
        action: open ?? undefined,
      });
    });
    return () => {
      offHello();
      offEvent();
    };
  }, [stream, client, toast, openOf]);

  const entries = bell.data?.entries;
  const value = useMemo<Events>(() => {
    const unreadEntries = (entries ?? []).filter((e) => readUpTo !== null && e.id > readUpTo);
    return {
      entries,
      unread: unreadEntries.length,
      urgent: unreadEntries.filter((e) => tierOf(e) === "must-act" && !dismissed.includes(e.id)),
      markAllRead() {
        const newest = entries?.[0]?.id;
        if (newest === undefined) return;
        setReadUpTo(newest);
        save(READ_KEY, newest);
        setDismissed([]);
        save(DISMISSED_KEY, []);
      },
      dismiss(id) {
        setDismissed((was) => {
          const now = [...was, id].slice(-50);
          save(DISMISSED_KEY, now);
          return now;
        });
      },
      names,
      openOf,
    };
  }, [entries, readUpTo, dismissed, names, openOf]);

  return <EventsContext.Provider value={value}>{children}</EventsContext.Provider>;
}
