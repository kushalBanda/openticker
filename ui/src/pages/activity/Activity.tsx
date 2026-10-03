import { useState } from "react";
import { Link } from "react-router";
import { type AuditEntry, useActivity, useStrategies } from "../../api/queries";
import { type Column, DataTable } from "../../components/DataTable";
import { Page } from "../../components/Page";
import { Segmented } from "../../components/Segmented";
import { TableEmpty, TableSkeleton } from "../../components/TableStates";
import {
  byLabel,
  describe,
  fromDate,
  KINDS,
  type KindFilter,
  type Range,
  strategyOf,
  type WhoFilter,
} from "../../lib/events";
import { istClock, istDate } from "../../lib/format";
import { useServerNow } from "../../stream/StreamProvider";

/**
 * Everything that happened, who did it, in order (decision 17): the audit
 * log, filtered by kind and by who. New events arrive on the stream and
 * refetch it, so it is live without polling.
 */
export function Activity() {
  const serverNow = useServerNow();
  const [range, setRange] = useState<Range>("today");
  const [kind, setKind] = useState<KindFilter>("all");
  const [who, setWho] = useState<WhoFilter>("anyone");
  const strategies = useStrategies();
  const names = new Map(
    (strategies.data?.strategies ?? []).map((s) => [s.strategy_id, s.name] as const),
  );
  const now = serverNow();
  const activity = useActivity({
    eventTypes: kind === "all" ? [] : KINDS[kind],
    source: who === "anyone" ? null : who,
    fromDate: fromDate(range, now),
  });
  const rows = activity.data?.pages.flatMap((page) => page.entries) ?? [];
  const today = istDate(now);

  const columns: Column<AuditEntry>[] = [
    {
      key: "time",
      head: "Time",
      align: "left",
      cell: (e) => {
        const at = new Date(e.occurred_at);
        return (
          <span className="muted tabular-nums">
            {istDate(at) === today ? istClock(at) : `${istDate(at)} ${istClock(at)}`}
          </span>
        );
      },
    },
    {
      key: "kind",
      head: "Kind",
      align: "left",
      cell: (e) => {
        const said = describe(e, names);
        return (
          <span className="badge" data-tone={said.tone}>
            {said.kind}
          </span>
        );
      },
    },
    {
      key: "what",
      head: "What happened",
      align: "left",
      wrap: true,
      cell: (e) => describe(e, names).text,
    },
    {
      key: "by",
      head: "By",
      align: "left",
      cell: (e) => {
        const strategy = strategyOf(e);
        const by = byLabel(e, names);
        return strategy && e.source === "strategy" ? (
          <Link to={`/strategies/${strategy}`} className="row-link">
            {by}
          </Link>
        ) : (
          by
        );
      },
    },
  ];

  return (
    <Page
      title="Activity"
      actions={
        <Segmented<Range>
          label="Period"
          value={range}
          onChange={setRange}
          segments={[
            { value: "today", label: "Today" },
            { value: "7d", label: "7 days" },
            { value: "30d", label: "30 days" },
          ]}
        />
      }
    >
      <p className="note" style={{ margin: "-16px 0 24px" }}>
        Everything that happened, who did it, in order. Kept on this machine.
      </p>
      <div className="toolbar">
        <Segmented<KindFilter>
          label="Kind"
          value={kind}
          onChange={setKind}
          segments={[
            { value: "all", label: "All" },
            { value: "orders", label: "Orders" },
            { value: "strategies", label: "Strategies" },
            { value: "scripts", label: "Scripts" },
            { value: "risk", label: "Risk" },
            { value: "broker", label: "Broker" },
            { value: "agents", label: "Agents" },
          ]}
        />
        <span className="flex-1" />
        <Segmented<WhoFilter>
          label="Who"
          value={who}
          onChange={setWho}
          segments={[
            { value: "anyone", label: "Anyone" },
            { value: "you", label: "You" },
            { value: "claude-code", label: "Claude" },
            { value: "codex", label: "Codex" },
            { value: "strategy", label: "Strategies" },
            { value: "script", label: "Scripts" },
            { value: "alert", label: "Alerts" },
          ]}
        />
      </div>

      <div className="tile" data-flush="true">
        {activity.isPending ? (
          <TableSkeleton label="Loading activity" rows={6} />
        ) : activity.isError ? (
          <div className="empty" role="alert">
            <h2>Activity didn't load</h2>
            <p className="note">{activity.error.message}</p>
            <button type="button" className="btn" onClick={() => activity.refetch()}>
              Try again
            </button>
          </div>
        ) : rows.length === 0 ? (
          <TableEmpty>
            {kind === "all" && who === "anyone"
              ? range === "today"
                ? "Nothing yet today. Orders, fills, strategies and reviews show up here as they happen."
                : "Nothing in this period."
              : "Nothing matches these filters."}
          </TableEmpty>
        ) : (
          <DataTable
            label="Activity"
            columns={columns}
            rows={rows}
            rowKey={(e) => String(e.id)}
            dense
          />
        )}
      </div>
      {activity.hasNextPage && (
        <div className="flex justify-center" style={{ marginTop: 16 }}>
          <button
            type="button"
            className="btn"
            disabled={activity.isFetchingNextPage}
            onClick={() => activity.fetchNextPage()}
          >
            {activity.isFetchingNextPage ? "Loading…" : "Older"}
          </button>
        </div>
      )}
    </Page>
  );
}
