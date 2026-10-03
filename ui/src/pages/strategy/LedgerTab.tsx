import type { UseQueryResult } from "@tanstack/react-query";
import { Fragment } from "react";
import type { Schemas } from "../../api/client";
import { StatCard } from "../../components/StatCard";
import { TableEmpty, TableSkeleton } from "../../components/TableStates";
import { direction, MISSING, qty, rupees } from "../../lib/format";
import { reasonLabel, winRate } from "../../lib/strategies";

type Ledger = Schemas["StrategyLedgerResult"];

function Money({ value }: { value: number | null }) {
  if (value === null) return <span className="missing">{MISSING}</span>;
  return <span className={direction(value)}>{rupees(value, { sign: true })}</span>;
}

/** The totals a review judges (ADR 29): runs after costs only. */
export function LedgerTab({ ledger }: { ledger: UseQueryResult<Ledger> }) {
  if (ledger.isPending) return <TableSkeleton label="Loading the ledger" />;
  if (ledger.isError)
    return (
      <div className="tile">
        <TableEmpty>{`The ledger didn't load: ${ledger.error.message}`}</TableEmpty>
      </div>
    );
  const { totals, total_runs, uncharged, open_runs } = ledger.data;
  const left = [
    uncharged && `${uncharged} from before costs were recorded`,
    open_runs && `${open_runs} still open`,
  ].filter(Boolean);
  return (
    <div className="flex flex-col gap-6">
      <div className="stats" style={{ marginBottom: 0 }}>
        <StatCard
          label="Net after costs"
          value={<Money value={totals.runs ? totals.net_pnl : null} />}
          note={`${qty(totals.runs)} of ${qty(total_runs)} runs counted${left.length ? `; not: ${left.join(", ")}` : ""}`}
        />
        <StatCard
          label="Gross"
          value={<Money value={totals.runs ? totals.gross_pnl : null} />}
          note={`${rupees(totals.charges)} charges`}
        />
        <StatCard
          label="Wins"
          value={winRate(totals.wins, totals.runs) ?? MISSING}
          note={`${totals.wins} won · ${totals.losses} lost`}
        />
        <StatCard
          label="Slippage"
          value={rupees(totals.slippage)}
          note="already inside gross: fills beyond their price"
        />
      </div>
      <div className="ledger-grid">
        <div className="tile">
          <h2 className="tile-title">Per run</h2>
          <dl className="kv" style={{ marginTop: 12 }}>
            <dt className="muted">Average win</dt>
            <dd style={{ margin: 0 }}>
              <Money value={totals.average_win} />
            </dd>
            <dt className="muted">Average loss</dt>
            <dd style={{ margin: 0 }}>
              <Money value={totals.average_loss} />
            </dd>
            <dt className="muted">Best run</dt>
            <dd style={{ margin: 0 }}>
              <Money value={totals.best_run} />
            </dd>
            <dt className="muted">Worst run</dt>
            <dd style={{ margin: 0 }}>
              <Money value={totals.worst_run} />
            </dd>
            <dt className="muted">Max drawdown</dt>
            <dd style={{ margin: 0 }}>
              <Money value={totals.runs ? -totals.max_drawdown : null} />
            </dd>
          </dl>
        </div>
        <div className="tile">
          <h2 className="tile-title">How runs ended</h2>
          {Object.keys(totals.stop_reasons).length === 0 ? (
            <p className="note">No runs after costs yet.</p>
          ) : (
            <dl className="kv" style={{ marginTop: 12 }}>
              {Object.entries(totals.stop_reasons).map(([reason, count]) => (
                <Fragment key={reason}>
                  <dt className="muted">
                    {reasonLabel(reason as Schemas["StrategyStopReason"]) ?? reason}
                  </dt>
                  <dd style={{ margin: 0 }}>
                    {count} ({Math.round((count / totals.runs) * 100)}%)
                  </dd>
                </Fragment>
              ))}
            </dl>
          )}
        </div>
      </div>
    </div>
  );
}
