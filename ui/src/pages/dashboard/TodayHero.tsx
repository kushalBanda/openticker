import NumberFlow from "@number-flow/react";
import { Fragment, lazy, Suspense } from "react";
import { Link } from "react-router";
import type { Today } from "../../api/queries";
import { direction, istClock, qty, rupees } from "../../lib/format";
import { sinceSentence } from "../../lib/today";

const DAY = new Intl.DateTimeFormat("en-IN", {
  weekday: "short",
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});

/** 2026-09-25 as "Fri 25 Sep 2026": a trading date, no clock. */
function sessionDay(date: string): string {
  const parts = DAY.formatToParts(new Date(`${date}T00:00:00Z`));
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  return `${get("weekday")} ${get("day")} ${get("month")} ${get("year")}`;
}

// lightweight-charts loads with the first chart, not with the app.
const IntradayChart = lazy(() =>
  import("../../components/IntradayChart").then((m) => ({ default: m.IntradayChart })),
);

const FIGURE = { minimumFractionDigits: 2, maximumFractionDigits: 2 } as const;

/**
 * The first thing on the Dashboard (DESIGN.md Today Hero): today's P&L after
 * charges, what it is made of, the minute line, and what happened since the
 * user was last here. `net` is the server's figure moved by the ticks since.
 */
export function TodayHero({
  today,
  net,
  updatedAt,
  minute,
  names,
}: {
  today: Today;
  net: number | null;
  updatedAt: Date;
  /** HH:MM now, exchange-local. */
  minute: string;
  names: ReadonlyMap<string, string>;
}) {
  const tone = direction(net);
  const day = sessionDay(today.trading_date);
  const since = today.since ? sinceSentence(today.since, names) : null;
  const visit = today.since ? istClock(new Date(today.since.at)).slice(0, 5) : undefined;

  return (
    <section className="today-hero" aria-labelledby="today-label" data-testid="today-hero">
      <div className="today-top">
        <span className="label" id="today-label">
          {today.market_open ? "Today, after charges" : `${day}, after charges`}
        </span>
        <span className="flex-1" />
        <span className="note">
          {today.market_open ? "live · " : "market closed · "}updated {istClock(updatedAt)}
        </span>
      </div>
      <div className={`today-figure ${tone ?? ""}`} data-testid="today-net">
        {net === null ? (
          <span className="missing">—</span>
        ) : (
          <>
            <span className="today-sign">{net > 0 ? "+" : net < 0 ? "-" : ""}</span>
            <span className="today-cur">₹</span>
            <NumberFlow value={Math.abs(net)} locales="en-IN" format={FIGURE} />
          </>
        )}
      </div>
      <p className="today-after">
        {today.before_charges === null
          ? "An open position has no price yet"
          : `${rupees(today.before_charges, { sign: true })} before`}{" "}
        {rupees(today.charges)} charges on {qty(today.fills)} fill{today.fills === 1 ? "" : "s"} ·
        realized {rupees(today.realized_pnl, { sign: true })} · open{" "}
        {today.unrealized_pnl === null ? "—" : rupees(today.unrealized_pnl, { sign: true })}
        {!today.complete && " · some older fills didn't record what they realized"}
      </p>
      {today.points.length > 0 ? (
        <Suspense fallback={<div className="skeleton" style={{ width: "100%", height: 172 }} />}>
          <IntradayChart
            day={today.trading_date}
            points={today.points}
            now={today.market_open && net !== null ? { minute, net_pnl: net } : undefined}
            visit={visit}
          />
        </Suspense>
      ) : (
        <p className="note today-empty" data-testid="intraday-empty">
          No minute line for {day}: openticker-serve records a point each minute while it runs in
          the session.
        </p>
      )}
      {since && (
        <p className="today-since" data-testid="since">
          {since.lead}
          {since.parts.map((part, i) => (
            <Fragment key={part.text}>
              {i > 0 && (i === since.parts.length - 1 ? ", and " : ", ")}
              {part.to ? (
                <Link to={part.to} className={part.tone}>
                  {part.text}
                </Link>
              ) : (
                <span className={part.tone}>{part.text}</span>
              )}
            </Fragment>
          ))}
          {since.parts.length > 0 && "."}
        </p>
      )}
    </section>
  );
}
