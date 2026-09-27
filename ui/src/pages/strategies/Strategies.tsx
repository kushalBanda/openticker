import { Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router";
import { useReleaseStrategy, useStartStrategy, useStrategies } from "../../api/queries";
import { type Column, DataTable } from "../../components/DataTable";
import { Page } from "../../components/Page";
import { Segmented } from "../../components/Segmented";
import { StatCard } from "../../components/StatCard";
import { TableEmpty, TableSkeleton } from "../../components/TableStates";
import { direction, MISSING, qty, rupees, signed } from "../../lib/format";
import {
  ago,
  type KindFilter,
  matches,
  NEW_STRATEGY_PROMPT,
  quickAction,
  type SegmentFilter,
  type StateFilter,
  type Strategy,
  stateBadge,
  stateNote,
  trades,
  verdictBadge,
  when,
} from "../../lib/strategies";
import { useActions } from "../../shell/actions";
import { useLive } from "../../stream/StreamProvider";
import { useTodayPnl } from "./live";
import { StopDialog } from "./StopDialog";

/** The clock the page's relative times read; ticks once a minute. */
export function useMinute(): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 60_000);
    return () => clearInterval(timer);
  }, []);
  return now;
}

function Money({ value, currency }: { value: number | null; currency?: boolean }) {
  if (value === null) return <span className="missing">{MISSING}</span>;
  return (
    <span className={direction(value)}>
      {currency ? rupees(value, { sign: true }) : signed(value)}
    </span>
  );
}

export function StateBadge({ strategy }: { strategy: Strategy }) {
  const badge = stateBadge(strategy.state);
  return (
    <span className="badge" data-tone={badge.tone}>
      {badge.label}
    </span>
  );
}

function Review({ strategy, now }: { strategy: Strategy; now: Date }) {
  const review = strategy.last_review;
  if (!review) return <span className="muted">never</span>;
  const badge = verdictBadge(review.verdict);
  return (
    <span className="inline-flex items-center gap-2">
      {badge ? (
        <span className="badge" data-tone={badge.tone}>
          {badge.label}
        </span>
      ) : (
        <span className="badge">Answered</span>
      )}
      <span className="muted">{ago(review.ended_at, now)}</span>
    </span>
  );
}

export function Strategies() {
  const { status } = useLive();
  const broker = status?.broker;
  const { notify } = useActions();
  const list = useStrategies();
  const start = useStartStrategy();
  const release = useReleaseStrategy();
  const now = useMinute();
  const navigate = useNavigate();
  const [kind, setKind] = useState<KindFilter>("all");
  const [segment, setSegment] = useState<SegmentFilter>("all");
  const [state, setState] = useState<StateFilter>("all");
  const [stopping, setStopping] = useState<Strategy | null>(null);

  const all = list.data?.strategies ?? [];
  const today = useTodayPnl(all);
  const rows = all.filter((s) => matches(s, kind, segment, state));

  const running = all.filter((s) => s.state === "running" || s.state === "listening").length;
  const scheduled = all.filter((s) => s.state === "scheduled");
  const soonest = scheduled
    .map((s) => s.next_entry)
    .filter((at): at is string => at !== null)
    .sort()[0];
  const todayTotal = all.reduce<number | null>((sum, s) => {
    const value = today.get(s.strategy_id) ?? null;
    return sum === null || value === null ? null : sum + value;
  }, 0);
  const allTime = all.reduce((sum, s) => sum + s.net_pnl, 0);
  const runs = all.reduce((sum, s) => sum + s.runs, 0);

  const act = async (strategy: Strategy, action: "start" | "release") => {
    try {
      if (action === "start") {
        if (!broker) return;
        await start.mutateAsync({ strategyId: strategy.strategy_id, broker });
        notify(`Starting ${strategy.name}: it enters within a second.`);
      } else {
        await release.mutateAsync(strategy.strategy_id);
        notify(`Released ${strategy.name}'s kill switch.`);
      }
    } catch (error) {
      notify(error instanceof Error ? error.message : String(error));
    }
  };

  const columns: Column<Strategy>[] = [
    {
      key: "strategy",
      head: "Strategy",
      align: "left",
      cell: (s) => (
        <Link to={`/strategies/${s.strategy_id}`} className="row-link">
          {s.name}
        </Link>
      ),
      sub: (s) => (
        <span className="inline-flex items-center gap-1.5">
          {s.kind === "options" ? "Options" : "Signal"} ·
          {s.segments.map((seg) => (
            <span key={seg} className="badge">
              {seg}
            </span>
          ))}
          {trades(s)}
        </span>
      ),
    },
    {
      key: "state",
      head: "State",
      align: "left",
      cell: (s) => <StateBadge strategy={s} />,
      sub: (s) => stateNote(s, now) ?? MISSING,
    },
    {
      key: "today",
      head: "Today",
      cell: (s) => {
        const value = today.get(s.strategy_id) ?? null;
        return value === 0 && !s.active_run ? (
          <span className="missing">{MISSING}</span>
        ) : (
          <Money value={value} />
        );
      },
    },
    {
      key: "all",
      head: "All time",
      cell: (s) =>
        s.judged_runs ? <Money value={s.net_pnl} /> : <span className="missing">{MISSING}</span>,
    },
    { key: "runs", head: "Runs", cell: (s) => qty(s.runs) },
    {
      key: "review",
      head: "Last review",
      align: "left",
      cell: (s) => <Review strategy={s} now={now} />,
    },
  ];

  return (
    <Page
      title="Strategies"
      count={list.data ? all.length : undefined}
      actions={
        <button
          type="button"
          className="btn"
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(NEW_STRATEGY_PROMPT);
              notify("Copied. Paste it into Claude Code or Codex and say what to trade.");
            } catch {
              notify(`Ask your agent: ${NEW_STRATEGY_PROMPT}`);
            }
          }}
        >
          <Sparkles size={15} aria-hidden />
          Ask Claude to write one
        </button>
      }
    >
      <div className="stats">
        <StatCard
          label="Running"
          value={list.data ? running : <span className="skeleton" style={{ width: 40 }} />}
          note={list.data ? `${all.length - running} not running` : undefined}
        />
        <StatCard
          label="Scheduled"
          value={list.data ? scheduled.length : <span className="skeleton" style={{ width: 40 }} />}
          note={soonest ? `next ${when(soonest, now)}` : list.data ? "none" : undefined}
        />
        <StatCard
          label="P&L today"
          testId="strategies-today"
          value={
            list.data ? (
              <Money value={todayTotal} currency />
            ) : (
              <span className="skeleton" style={{ width: 120 }} />
            )
          }
          note="after charges, open legs live"
        />
        <StatCard
          label="All time, after costs"
          value={
            list.data ? (
              <Money value={allTime} currency />
            ) : (
              <span className="skeleton" style={{ width: 120 }} />
            )
          }
          note={list.data ? `${qty(runs)} runs` : undefined}
        />
      </div>

      <div className="toolbar">
        <Segmented<KindFilter>
          label="Kind"
          value={kind}
          onChange={setKind}
          segments={[
            { value: "all", label: "All kinds" },
            { value: "options", label: "Options" },
            { value: "signal", label: "Signal" },
          ]}
        />
        <Segmented<SegmentFilter>
          label="Segment"
          value={segment}
          onChange={setSegment}
          segments={[
            { value: "all", label: "Any segment" },
            { value: "EQ", label: "EQ" },
            { value: "FUT", label: "FUT" },
            { value: "OPT", label: "OPT" },
          ]}
        />
        <span className="flex-1" />
        <Segmented<StateFilter>
          label="State"
          value={state}
          onChange={setState}
          segments={[
            { value: "all", label: "Any state" },
            { value: "running", label: "Running" },
            { value: "scheduled", label: "Scheduled" },
            { value: "stopped", label: "Stopped" },
            { value: "killed", label: "Killed" },
          ]}
        />
      </div>

      <div className="tile" data-flush="true">
        {list.isPending ? (
          <TableSkeleton label="Loading strategies" rows={3} />
        ) : list.isError ? (
          <div className="empty" role="alert">
            <h2>Strategies didn't load</h2>
            <p className="note">{list.error.message}</p>
            <button type="button" className="btn" onClick={() => list.refetch()}>
              Try again
            </button>
          </div>
        ) : all.length === 0 ? (
          <div className="empty">
            <h2>No strategies yet</h2>
            <p className="note">
              Your agent writes them: ask Claude Code or Codex for an options strategy or one driven
              by TradingView alerts.
            </p>
          </div>
        ) : rows.length === 0 ? (
          <TableEmpty>No strategy matches these filters.</TableEmpty>
        ) : (
          <DataTable
            label="Strategies"
            columns={columns}
            rows={rows}
            rowKey={(s) => s.strategy_id}
            selected={stopping?.strategy_id}
            onSelect={(id) => navigate(`/strategies/${id}`)}
            actions={(s) => {
              const action = quickAction(s);
              if (action === "stop")
                return (
                  <button
                    type="button"
                    className="btn"
                    data-size="sm"
                    onClick={() => setStopping(s)}
                  >
                    Stop
                  </button>
                );
              if (action === "start")
                return (
                  <button
                    type="button"
                    className="btn"
                    data-variant="primary"
                    data-size="sm"
                    disabled={!broker || start.isPending}
                    onClick={() => act(s, "start")}
                  >
                    Start
                  </button>
                );
              if (action === "release")
                return (
                  <button
                    type="button"
                    className="btn"
                    data-size="sm"
                    disabled={release.isPending}
                    onClick={() => act(s, "release")}
                  >
                    Release
                  </button>
                );
              return null;
            }}
          />
        )}
      </div>
      <p className="note" style={{ marginTop: 16 }}>
        Strategies are written and changed by your agent. Here you start, stop, schedule and kill
        them. Today counts runs started today and the open run, after charges.
      </p>

      <StopDialog
        strategy={stopping}
        onClose={() => setStopping(null)}
        onDone={(message) => {
          setStopping(null);
          notify(message);
        }}
      />
    </Page>
  );
}
