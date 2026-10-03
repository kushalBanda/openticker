import type { UseQueryResult } from "@tanstack/react-query";
import type { Schemas } from "../../api/client";
import { type Column, DataTable } from "../../components/DataTable";
import { TableEmpty, TableSkeleton } from "../../components/TableStates";
import { direction, istDate, MISSING, rupees, signed } from "../../lib/format";
import { reasonLabel, triggerLabel } from "../../lib/strategies";

type Ledger = Schemas["StrategyLedgerResult"];
type LedgerRun = Schemas["LedgerRunResult"];

const stamp = (at: string) => istDate(at, { time: true, year: true });

export function Signed({ value }: { value: number | null }) {
  if (value === null) return <span className="missing">{MISSING}</span>;
  return <span className={direction(value)}>{signed(value)}</span>;
}

export function statusOf(run: LedgerRun) {
  if (run.status === "open")
    return (
      <span className="badge" data-tone="accent">
        Open
      </span>
    );
  if (run.status === "stopping")
    return (
      <span className="badge" data-tone="accent">
        Stopping
      </span>
    );
  return <span className="badge">Ended</span>;
}

/** Its newest runs, what each netted after costs and why it ended. */
export function RunsTab({ ledger }: { ledger: UseQueryResult<Ledger> }) {
  const columns: Column<LedgerRun>[] = [
    {
      key: "started",
      head: "Started",
      align: "left",
      cell: (r) => stamp(r.started_at),
      sub: (r) => triggerLabel(r.trigger),
    },
    { key: "status", head: "Status", align: "left", cell: statusOf },
    {
      key: "ended",
      head: "Ended",
      align: "left",
      cell: (r) => (r.ended_at ? stamp(r.ended_at) : <span className="missing">{MISSING}</span>),
      sub: (r) => reasonLabel(r.stop_reason) ?? r.stop_detail,
    },
    { key: "fills", head: "Fills", cell: (r) => r.fills.length },
    { key: "gross", head: "Gross", cell: (r) => <Signed value={r.gross_pnl} /> },
    { key: "charges", head: "Charges", cell: (r) => rupees(r.charges) },
    {
      key: "net",
      head: "Net P&L",
      cell: (r) => <Signed value={r.net_pnl} />,
      sub: (r) => (r.after_costs || r.status !== "ended" ? null : "not counted"),
    },
  ];
  return (
    <div className="tile" data-flush="true">
      <div className="tile-head">
        <h2>
          Runs <span className="count">({ledger.data?.total_runs ?? 0})</span>
        </h2>
        <span className="flex-1" />
        {ledger.data && ledger.data.total_runs > ledger.data.runs.length && (
          <span className="note">the newest {ledger.data.runs.length}</span>
        )}
      </div>
      {ledger.isPending ? (
        <TableSkeleton label="Loading runs" />
      ) : ledger.isError ? (
        <TableEmpty>{`Runs didn't load: ${ledger.error.message}`}</TableEmpty>
      ) : ledger.data.runs.length === 0 ? (
        <TableEmpty>No runs yet.</TableEmpty>
      ) : (
        <DataTable
          label="Runs"
          columns={columns}
          rows={ledger.data.runs}
          rowKey={(r) => r.run_id}
        />
      )}
    </div>
  );
}
