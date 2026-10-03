import { lazy, Suspense, useMemo, useState } from "react";
import type { Schemas } from "../../api/client";
import { useCloseStrategyLegs } from "../../api/queries";
import { type Column, DataTable } from "../../components/DataTable";
import { Instrument } from "../../components/Instrument";
import { SideBadge } from "../../components/PlacedBy";
import { Segmented } from "../../components/Segmented";
import { TableEmpty } from "../../components/TableStates";
import {
  direction,
  istClock,
  istDate,
  MISSING,
  price,
  qty,
  rupees,
  signed,
} from "../../lib/format";
import {
  contractOf,
  isToday,
  type OptionsDefinition,
  type SignalDefinition,
  type Strategy,
} from "../../lib/strategies";
import { useActions } from "../../shell/actions";
import { type LiveLeg, useLiveLegs } from "../strategies/live";
import { OptionsDefinitionCard } from "./definitions/OptionsDefinition";
import { SignalDefinitionCard } from "./definitions/SignalDefinition";
import { LatestReview } from "./LatestReview";

// lightweight-charts loads with the first chart, not with the app.
const EquityChart = lazy(() =>
  import("../../components/EquityChart").then((m) => ({ default: m.EquityChart })),
);

type Ledger = Schemas["StrategyLedgerResult"];
type Signals = Schemas["StrategySignalsResult"];
type Job = Schemas["AgentJobResult"];
type Range = "1m" | "3m" | "all";

const RESULT_TONE: Record<string, "accent" | "down" | undefined> = {
  accepted: "accent",
  refused: "down",
  error: "down",
};

export function AlertResult({ result }: { result: string }) {
  return (
    <span className="badge" data-tone={RESULT_TONE[result]}>
      {result.charAt(0).toUpperCase() + result.slice(1)}
    </span>
  );
}

function LegsTile({
  id,
  summary,
  marketOpen,
  alerts,
}: {
  id: string;
  summary: Strategy | undefined;
  marketOpen: boolean;
  alerts?: Signals["calls"];
}) {
  const run = summary?.active_run;
  const live = useLiveLegs(run?.legs ?? []);
  const closeLegs = useCloseStrategyLegs();
  const { notify } = useActions();
  const [closing, setClosing] = useState<string | null>(null);

  const columns: Column<LiveLeg>[] = [
    {
      key: "instrument",
      head: "Instrument",
      align: "left",
      cell: ({ leg }) => {
        const contract = contractOf(leg.symbol);
        return (
          <Instrument
            symbol={leg.symbol}
            exchange={leg.exchange}
            type={contract.type}
            expiry={contract.expiry}
            strike={contract.strike}
          />
        );
      },
    },
    { key: "side", head: "Side", align: "left", cell: ({ leg }) => <SideBadge side={leg.side} /> },
    { key: "qty", head: "Qty.", cell: ({ leg }) => qty(leg.quantity) },
    { key: "entry", head: "Entry", cell: ({ leg }) => price(leg.entry_price) },
    {
      key: "ltp",
      head: "LTP",
      cell: ({ leg, ltp }) =>
        leg.status === "closed" ? (
          <span className="muted">{price(leg.exit_price)}</span>
        ) : (
          price(ltp)
        ),
    },
    { key: "stop", head: "Stop", cell: ({ leg }) => price(leg.stop_loss) },
    { key: "target", head: "Target", cell: ({ leg }) => price(leg.target) },
    {
      key: "pnl",
      head: "P&L",
      cell: ({ pnl }) =>
        pnl === null ? (
          <span className="missing">{MISSING}</span>
        ) : (
          <span className={direction(pnl)}>{signed(pnl)}</span>
        ),
      sub: ({ leg }) => (leg.status === "open" ? null : leg.status),
    },
  ];

  const total = live.reduce<number | null>(
    (sum, l) => (sum === null || l.pnl === null ? null : sum + l.pnl),
    0,
  );

  return (
    <div className="tile" data-flush="true">
      <div className="tile-head">
        <h2>{summary?.kind === "signal" ? "Legs" : "Legs · this run"}</h2>
        <span className="flex-1" />
        {run && (
          <span className="note">
            entered {istClock(new Date(run.started_at))}
            {total !== null && ` · P&L ${rupees(total, { sign: true })}`}
          </span>
        )}
      </div>
      {!run ? (
        <TableEmpty>
          {summary?.state === "listening"
            ? "Nothing open. The next alert it accepts enters a leg."
            : summary?.state === "scheduled"
              ? "Nothing open. It enters at its next scheduled time."
              : "Nothing open."}
        </TableEmpty>
      ) : (
        <DataTable
          label="Legs"
          columns={columns}
          rows={live}
          rowKey={(l) => l.leg.leg_id}
          selected={closing ?? undefined}
          actions={(l) =>
            l.leg.status === "open" ? (
              <button
                type="button"
                className="btn"
                data-variant="ghost"
                data-size="sm"
                disabled={!marketOpen || closeLegs.isPending}
                onClick={async () => {
                  setClosing(l.leg.leg_id);
                  try {
                    await closeLegs.mutateAsync({ strategyId: id, legIds: [l.leg.leg_id] });
                    notify(`Closing ${l.leg.symbol}: the run carries on with the others.`);
                  } catch (error) {
                    notify(error instanceof Error ? error.message : String(error));
                  } finally {
                    setClosing(null);
                  }
                }}
              >
                {marketOpen ? "Close leg" : "Market closed"}
              </button>
            ) : null
          }
        />
      )}
      {alerts && (
        <>
          <div className="tile-head" style={{ borderTop: "1px solid var(--line)", marginTop: 8 }}>
            <h2>Recent alerts</h2>
          </div>
          {alerts.length === 0 ? (
            <TableEmpty>No alerts yet.</TableEmpty>
          ) : (
            <table className="table" aria-label="Recent alerts">
              <tbody>
                {alerts.slice(0, 3).map((call) => (
                  <tr key={call.received_at + call.message}>
                    <td data-align="left" className="muted" style={{ width: 120 }}>
                      {isToday(call.received_at, new Date())
                        ? istClock(new Date(call.received_at))
                        : istDate(call.received_at, { time: true })}
                    </td>
                    <td data-align="left" style={{ width: 96 }}>
                      <AlertResult result={call.result} />
                    </td>
                    <td data-align="left" data-wrap="true">
                      {call.message}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </div>
  );
}

function EquityTile({ ledger }: { ledger: Ledger | undefined }) {
  const [range, setRange] = useState<Range>("3m");
  const points = useMemo(() => {
    const all = ledger?.equity ?? [];
    if (range === "all" || all.length === 0) return all;
    const last = new Date(all[all.length - 1]?.day ?? 0);
    last.setMonth(last.getMonth() - (range === "1m" ? 1 : 3));
    const from = last.toISOString().slice(0, 10);
    return all.filter((p) => p.day >= from);
  }, [ledger, range]);

  return (
    <div className="tile">
      <div className="flex items-center gap-3" style={{ marginBottom: 12 }}>
        <h2 className="tile-title">Equity after costs</h2>
        <span className="flex-1" />
        <Segmented<Range>
          label="Range"
          value={range}
          onChange={setRange}
          segments={[
            { value: "1m", label: "1M" },
            { value: "3m", label: "3M" },
            { value: "all", label: "All" },
          ]}
        />
      </div>
      {!ledger ? (
        <div className="skeleton" style={{ width: "100%", height: 200 }} />
      ) : points.length === 0 ? (
        <p
          className="note"
          style={{ height: 200, margin: 0, display: "grid", placeItems: "center" }}
        >
          No runs after costs yet: the curve starts with the first one that ends.
        </p>
      ) : (
        <Suspense fallback={<div className="skeleton" style={{ width: "100%", height: 200 }} />}>
          <EquityChart points={points} />
        </Suspense>
      )}
    </div>
  );
}

export function Overview({
  id,
  summary,
  definition,
  ledger,
  signals,
  reviews,
  marketOpen,
  broker,
  reviewSchedule,
}: {
  id: string;
  summary: Strategy | undefined;
  definition: OptionsDefinition | SignalDefinition | undefined;
  ledger: Ledger | undefined;
  signals: Signals | undefined;
  reviews: Job[] | undefined;
  marketOpen: boolean;
  broker: string | undefined;
  reviewSchedule: Schemas["ReviewScheduleResult"] | null | undefined;
}) {
  const name = summary?.name ?? "";
  return (
    <div className="flex flex-col gap-6">
      <LegsTile id={id} summary={summary} marketOpen={marketOpen} alerts={signals?.calls} />
      <div className="overview-grid">
        <div className="flex flex-col gap-6">
          <EquityTile ledger={ledger} />
          <LatestReview id={id} summary={summary} reviews={reviews} schedule={reviewSchedule} />
        </div>
        {definition &&
          ("underlying" in definition ? (
            <OptionsDefinitionCard definition={definition} strategy={{ name, strategy_id: id }} />
          ) : (
            <SignalDefinitionCard
              definition={definition}
              strategy={{ name, strategy_id: id }}
              signals={signals}
              broker={broker}
              locked={summary?.state === "killed"}
            />
          ))}
      </div>
    </div>
  );
}
