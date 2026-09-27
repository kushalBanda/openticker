import NumberFlow from "@number-flow/react";
import { CircleUser, SunMoon } from "lucide-react";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import { useEffect, useRef, useState } from "react";
import { useSession, useSignOut } from "../api/queries";
import { change, direction, istClock, price } from "../lib/format";
import { enter, leave } from "../lib/motion";
import { useTheme } from "../lib/theme";
import type { FeedStatus, InstrumentKey, StreamState } from "../stream/connection";
import { usePrice } from "../stream/prices";
import { useLive } from "../stream/StreamProvider";
import { useBarTitle } from "./title";

const INDICES: { key: InstrumentKey; name: string }[] = [
  { key: "NSE:NIFTY 50", name: "NIFTY 50" },
  { key: "NSE:NIFTY BANK", name: "NIFTY BANK" },
  { key: "BSE:SENSEX", name: "SENSEX" },
];

const PRICE = { minimumFractionDigits: 2, maximumFractionDigits: 2 } as const;

function Index({ id, name }: { id: InstrumentKey; name: string }) {
  const tick = usePrice(id);
  const moved = tick?.change != null ? change(tick.change, tick.change_pct) : "";
  // The rolling digits are drawn, not read: the label says the value once.
  const label = `${name} ${tick ? price(tick.last_price) : "no price yet"} ${moved}`.trim();
  return (
    <span data-testid={`index-${name}`} role="img" aria-label={label}>
      <b>{name}</b>
      {tick ? (
        <NumberFlow value={tick.last_price} locales="en-IN" format={PRICE} />
      ) : (
        <span className="muted">—</span>
      )}{" "}
      {moved && <span className={direction(tick?.change)}>{moved}</span>}
    </span>
  );
}

function Clock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);
  return <span className="muted">{istClock(now)}</span>;
}

function Market({ status }: { status: FeedStatus | null }) {
  if (status === null) return null;
  return status.market_open ? (
    <span className="flex items-center gap-2">
      <span className="badge" data-tone="accent">
        Market open
      </span>
      <Clock />
    </span>
  ) : (
    <span className="badge" data-tone="warn">
      Market closed
    </span>
  );
}

const title = (broker: string) => broker.charAt(0).toUpperCase() + broker.slice(1);

/** One item for where prices come from: the broker session and the stream share a dot. */
export function priceSource(
  status: FeedStatus | null,
  state: StreamState,
  now: Date,
): { tone: "up" | "warn" | "down" | "muted"; text: string; warn?: boolean } {
  if (state === "connecting" || state === "polling") {
    const broker = status ? title(status.broker) : "Prices";
    return { tone: "warn", text: `${broker} · reconnecting` };
  }
  if (status === null) return { tone: "muted", text: "Connecting" };
  const broker = title(status.broker);
  if (!status.broker_connected) {
    const expired = status.broker_expires_at !== null && new Date(status.broker_expires_at) <= now;
    return expired
      ? { tone: "down", text: `${broker} expired`, warn: true }
      : { tone: "muted", text: "No broker" };
  }
  if (status.state === "live") return { tone: "up", text: `${broker} · live` };
  if (status.state === "quiet") return { tone: "warn", text: `${broker} · quiet` };
  return { tone: "up", text: broker };
}

function PriceSource() {
  const { status, state } = useLive();
  const source = priceSource(status, state, new Date());
  return (
    <span className="bar-item" data-testid="price-source" title="Where prices come from">
      <span className="dot" data-tone={source.tone} />
      <span className={source.warn ? "text-warn" : undefined}>{source.text}</span>
    </span>
  );
}

function ThemeToggle() {
  const [theme, setTheme] = useTheme();
  const next = theme === "dark" ? "light" : "dark";
  return (
    <button
      type="button"
      className="bar-button"
      onClick={() => setTheme(next)}
      aria-label={`Switch to ${next} theme`}
      title={`Switch to ${next} theme`}
    >
      <SunMoon aria-hidden />
    </button>
  );
}

const since = new Intl.DateTimeFormat("en-IN", {
  timeZone: "Asia/Kolkata",
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

function Account() {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLSpanElement>(null);
  const session = useSession().data;
  const signOut = useSignOut(false);
  const signOutAll = useSignOut(true);

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent | KeyboardEvent) => {
      if (
        event instanceof KeyboardEvent
          ? event.key === "Escape"
          : !box.current?.contains(event.target as Node)
      ) {
        setOpen(false);
      }
    };
    window.addEventListener("pointerdown", close);
    window.addEventListener("keydown", close);
    return () => {
      window.removeEventListener("pointerdown", close);
      window.removeEventListener("keydown", close);
    };
  }, [open]);

  return (
    <span className="relative" ref={box}>
      <button
        type="button"
        className="bar-button"
        aria-label="Account"
        aria-expanded={open}
        onClick={() => setOpen((was) => !was)}
      >
        <CircleUser aria-hidden />
      </button>
      <AnimatePresence>
        {open && (
          <m.div className="menu" role="menu" {...enter} exit={leave}>
            {session && (
              <div className="menu-note">
                Signed in on this browser since {since.format(new Date(session.signed_in_at))} IST
              </div>
            )}
            <button
              type="button"
              role="menuitem"
              className="menu-row"
              onClick={() => signOut.mutate()}
            >
              Sign out
            </button>
            <button
              type="button"
              role="menuitem"
              className="menu-row"
              onClick={() => signOutAll.mutate()}
            >
              Sign out everywhere
            </button>
          </m.div>
        )}
      </AnimatePresence>
    </span>
  );
}

export function StatusBar() {
  const { status } = useLive();
  const bar = useBarTitle();
  return (
    <header className="statusbar">
      <span className="index-strip">
        {INDICES.map((index) => (
          <Index key={index.key} id={index.key} name={index.name} />
        ))}
      </span>
      <Market status={status} />
      <span className="bar-title" data-shown={bar.shown} aria-hidden={!bar.shown}>
        {bar.title}
      </span>
      <PriceSource />
      <ThemeToggle />
      <Account />
    </header>
  );
}
