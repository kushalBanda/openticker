import type { UseQueryResult } from "@tanstack/react-query";
import type { Schemas } from "../../api/client";
import { type Column, DataTable } from "../../components/DataTable";
import { TableEmpty, TableSkeleton } from "../../components/TableStates";
import { istClock, istDate, MISSING } from "../../lib/format";
import { AlertResult } from "./Overview";

type Signals = Schemas["StrategySignalsResult"];
type Call = Signals["calls"][number];

const stamp = (at: string) => `${istDate(at)} ${istClock(new Date(at))}`;

/** Every alert that reached its URL, and what it did (ADR 24). */
export function SignalsTab({ signals }: { signals: UseQueryResult<Signals> }) {
  const columns: Column<Call>[] = [
    { key: "at", head: "Received", align: "left", cell: (c) => stamp(c.received_at) },
    {
      key: "result",
      head: "Result",
      align: "left",
      cell: (c) => <AlertResult result={c.result} />,
    },
    { key: "what", head: "What it did", align: "left", wrap: true, cell: (c) => c.message },
    {
      key: "from",
      head: "From",
      align: "left",
      cell: (c) => c.alert_format ?? <span className="missing">{MISSING}</span>,
      sub: (c) => c.client_ip,
    },
  ];
  return (
    <div className="tile" data-flush="true">
      <div className="tile-head">
        <h2>Alerts</h2>
      </div>
      {signals.isPending ? (
        <TableSkeleton label="Loading alerts" />
      ) : signals.isError ? (
        <TableEmpty>{`Alerts didn't load: ${signals.error.message}`}</TableEmpty>
      ) : signals.data.calls.length === 0 ? (
        <TableEmpty>No alerts have arrived yet.</TableEmpty>
      ) : (
        <DataTable
          label="Alerts"
          columns={columns}
          rows={signals.data.calls}
          rowKey={(c) => `${c.received_at}:${c.message}`}
        />
      )}
    </div>
  );
}
