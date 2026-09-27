import { useMemo } from "react";
import {
  useChargesSummary,
  useFunds,
  usePnlHistory,
  usePositions,
  useRecentEvents,
  useSetup,
  useStrategies,
  useToday,
} from "../../api/queries";
import { Page } from "../../components/Page";
import { Reveal } from "../../components/Reveal";
import { StatCard } from "../../components/StatCard";
import { istClock, istDate, qty, rupees } from "../../lib/format";
import { livePrice, markToMarket, total } from "../../lib/pnl";
import { useEvents } from "../../shell/events";
import type { InstrumentKey } from "../../stream/connection";
import { usePrices } from "../../stream/prices";
import { useLive, useServerNow } from "../../stream/StreamProvider";
import { FirstRun } from "./FirstRun";
import {
  ChargesTile,
  DailyCalendar,
  type LiveRow,
  MarginTile,
  OpenPositionsTile,
  RecentEventsTile,
  StrategiesTile,
} from "./Tiles";
import { TodayHero } from "./TodayHero";

const iso = (d: Date) => d.toISOString().slice(0, 10);
const DAYS_SHOWN = 120;

const weekday = new Intl.DateTimeFormat("en-IN", {
  timeZone: "Asia/Kolkata",
  weekday: "long",
});

/** Today's figure as the server gave it, moved by each open position's newer ticks. */
function useLiveRows(broker: string | undefined) {
  const positions = usePositions(broker, false);
  const open = useMemo(
    () => (positions.data?.positions ?? []).filter((p) => p.quantity !== 0),
    [positions.data],
  );
  const keys = useMemo(() => open.map((p) => `${p.exchange}:${p.symbol}` as InstrumentKey), [open]);
  const ticks = usePrices(keys);
  const rows: LiveRow[] = open.map((position, i) => {
    const ltp = livePrice(position, positions.dataUpdatedAt, ticks[i]);
    return { position, ltp, pnl: markToMarket(position, ltp) };
  });
  const server = total(open.map((p) => p.unrealized_pnl));
  const live = total(rows.map((r) => r.pnl));
  const drift = server === null || live === null ? 0 : live - server;
  return { rows, drift, loading: positions.isPending };
}

export function Dashboard() {
  const { status } = useLive();
  const broker = status?.broker;
  const now = useServerNow();
  const setup = useSetup(broker);
  const today = useToday(broker);
  const funds = useFunds(broker);
  const strategies = useStrategies();
  const recent = useRecentEvents(6);
  const { names } = useEvents();
  const { rows, drift, loading } = useLiveRows(broker);

  const to = iso(now());
  const fromDate = new Date(now());
  fromDate.setUTCDate(fromDate.getUTCDate() - DAYS_SHOWN);
  const from = iso(fromDate);
  const history = usePnlHistory(broker, from, to);
  const charges = useChargesSummary(`${to.slice(0, 4)}-01-01`, to);

  const firstRun = setup.data !== undefined && setup.data.first_fill_at === null;
  const data = today.data;
  const net = data?.net_pnl === null || data?.net_pnl === undefined ? null : data.net_pnl + drift;
  const list = strategies.data?.strategies;
  const running = list?.filter((s) => s.state === "running" || s.state === "listening").length;
  const killed = list?.filter((s) => s.state === "killed").length ?? 0;
  const held = rows.filter((r) => r.position.held_by.some((h) => h.strategy_id !== null)).length;

  return (
    <Page
      title="Dashboard"
      actions={
        <span className="muted">
          {weekday.format(now())} {istDate(now())}
        </span>
      }
    >
      {firstRun && setup.data ? (
        <FirstRun setup={setup.data} funds={funds.data} />
      ) : (
        <>
          {data ? (
            <TodayHero
              today={data}
              net={net}
              updatedAt={new Date(today.dataUpdatedAt)}
              minute={istClock(now()).slice(0, 5)}
              names={names}
            />
          ) : (
            <section className="today-hero" aria-busy="true" aria-label="Loading today">
              <span className="skeleton" style={{ width: 160, height: 16 }} />
              <span className="skeleton" style={{ width: 280, height: 64, marginTop: 12 }} />
            </section>
          )}

          <div className="stats stats-small">
            <StatCard
              label="Available funds"
              value={rupees(funds.data?.available_cash)}
              note={funds.data ? `of ${rupees(funds.data.total_capital)}` : undefined}
            />
            <StatCard
              label="Open positions"
              value={loading ? "—" : qty(rows.length)}
              note={held ? `${held} held by strategies` : "None held by strategies"}
            />
            <StatCard
              label="Strategies running"
              value={running === undefined ? "—" : qty(running)}
              note={
                killed ? (
                  <span className="text-warn">{killed} killed</span>
                ) : (
                  `${list?.length ?? 0} in all`
                )
              }
            />
          </div>

          <div className="dash-grid">
            <Reveal>
              <OpenPositionsTile rows={rows} loading={loading} />
            </Reveal>
            <Reveal>
              <MarginTile funds={funds.data} />
            </Reveal>
            <Reveal>
              <DailyCalendar days={history.data?.days ?? []} from={from} to={to} />
            </Reveal>
            <Reveal>
              <ChargesTile summary={charges.data} />
            </Reveal>
            <Reveal>
              <StrategiesTile strategies={list} />
            </Reveal>
            <Reveal>
              <RecentEventsTile entries={recent.data?.entries} names={names} />
            </Reveal>
          </div>
        </>
      )}
    </Page>
  );
}
