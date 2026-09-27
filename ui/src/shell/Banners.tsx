import { OctagonX, PlugZap, WifiOff } from "lucide-react";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { describe } from "../lib/events";
import { istClock } from "../lib/format";
import { enter, leave } from "../lib/motion";
import { useLive } from "../stream/StreamProvider";
import { useEvents } from "./events";

const title = (broker: string) => broker.charAt(0).toUpperCase() + broker.slice(1);

/** Seconds since `on` last turned true; null while it's false. */
function useSecondsSince(on: boolean): number | null {
  const [since, setSince] = useState<number | null>(null);
  const [, tick] = useState(0);
  useEffect(() => {
    if (!on) {
      setSince(null);
      return;
    }
    setSince(Date.now());
    const timer = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(timer);
  }, [on]);
  return since === null ? null : Math.round((Date.now() - since) / 1000);
}

/**
 * Under the status bar, only when something needs the user (DESIGN.md
 * Banners): the broker session expired, live prices lost, a strategy killed
 * or stopped by a fault. A strategy's banner stays until dismissed or read
 * in the bell.
 */
export function Banners() {
  const { status, state } = useLive();
  const { urgent, dismiss, names, openOf } = useEvents();
  const lost = useSecondsSince(state === "polling");
  const expired =
    status !== null &&
    !status.broker_connected &&
    status.broker_expires_at !== null &&
    new Date(status.broker_expires_at) <= new Date();
  const strategies = urgent.filter((e) => e.event_type !== "BrokerSessionExpired");

  return (
    <div className="banners">
      <AnimatePresence initial={false}>
        {expired && status && (
          <m.div
            key="session"
            className="banner"
            data-tone="warn"
            role="alert"
            {...enter}
            exit={leave}
          >
            <PlugZap size={18} aria-hidden />
            <span className="grow">
              <b>{title(status.broker)} session expired.</b> Prices are paused and strategies are
              holding. Log in again to resume.
            </span>
            <Link to="/settings" className="btn" data-variant="solid" data-size="sm">
              Reconnect {title(status.broker)}
            </Link>
          </m.div>
        )}
        {lost !== null && (
          <m.div
            key="stream"
            className="banner"
            data-tone="warn"
            role="status"
            {...enter}
            exit={leave}
          >
            <WifiOff size={18} aria-hidden />
            <span className="grow">
              <b>Live prices lost{lost >= 1 ? ` for ${lost}s` : ""}.</b> Showing quotes every 2s
              until the stream comes back.
            </span>
          </m.div>
        )}
        {strategies.map((entry) => {
          const said = describe(entry, names);
          const open = openOf(entry);
          return (
            <m.div
              key={entry.id}
              className="banner"
              data-tone="down"
              role="alert"
              data-testid="kill-banner"
              {...enter}
              exit={leave}
            >
              <OctagonX size={18} aria-hidden />
              <span className="grow">
                <b>{said.text}</b> at {istClock(new Date(entry.occurred_at))}.
              </span>
              {open && (
                <button type="button" className="btn" data-size="sm" onClick={open.run}>
                  Open strategy
                </button>
              )}
              <button
                type="button"
                className="btn"
                data-variant="ghost"
                data-size="sm"
                onClick={() => dismiss(entry.id)}
              >
                Dismiss
              </button>
            </m.div>
          );
        })}
      </AnimatePresence>
    </div>
  );
}
