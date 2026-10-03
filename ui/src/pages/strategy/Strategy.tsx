import { useState } from "react";
import { Link, useParams } from "react-router";
import { ApiError } from "../../api/client";
import {
  useKillStrategy,
  useLedger,
  useReleaseStrategy,
  useReviews,
  useScheduleStrategy,
  useSignals,
  useStartStrategy,
  useStrategies,
  useStrategy,
} from "../../api/queries";
import { HoldButton } from "../../components/HoldButton";
import { Page } from "../../components/Page";
import { Segmented } from "../../components/Segmented";
import { loaded, StatCard } from "../../components/StatCard";
import { failureOf, TableFailed } from "../../components/TableStates";
import { direction, MISSING, rupees } from "../../lib/format";
import {
  isToday,
  type OptionsDefinition,
  type Strategy as Summary,
  weekdaysText,
  winRate,
} from "../../lib/strategies";
import { useActions } from "../../shell/actions";
import { useLive } from "../../stream/StreamProvider";
import { useLiveLegs } from "../strategies/live";
import { StopDialog } from "../strategies/StopDialog";
import { StateBadge, useMinute } from "../strategies/Strategies";
import { LedgerTab } from "./LedgerTab";
import { Overview } from "./Overview";
import { ReviewsTab } from "./ReviewsTab";
import { RunsTab } from "./RunsTab";
import { SignalsTab } from "./SignalsTab";

type Tab = "overview" | "runs" | "ledger" | "signals" | "reviews";

function Money({ value }: { value: number | null }) {
  if (value === null) return <span className="missing">{MISSING}</span>;
  return <span className={direction(value)}>{rupees(value, { sign: true })}</span>;
}

/** The open run's P&L before charges: closed legs realized, open ones live. */
function useOpenPnl(summary: Summary | undefined): number | null {
  const legs = useLiveLegs(summary?.active_run?.legs ?? []);
  if (!summary?.active_run) return null;
  let sum = 0;
  for (const leg of legs) {
    if (leg.pnl === null) return null;
    sum += leg.pnl;
  }
  return sum;
}

/**
 * One strategy (grilling decision 15b): the same frame for every kind, with
 * its state and controls, stat tiles, and tabs. Only the Definition card and
 * the tiles that describe a kind's rules differ.
 */
export function Strategy() {
  const { id = "" } = useParams();
  const { status } = useLive();
  const broker = status?.broker;
  const marketOpen = status?.market_open ?? false;
  const { notify } = useActions();
  const now = useMinute();
  const list = useStrategies();
  const detail = useStrategy(id);
  const summary = list.data?.strategies.find((s) => s.strategy_id === id);
  const signal = summary?.kind === "signal" || detail.data?.kind === "signal";
  const ledger = useLedger(id);
  const signals = useSignals(id, signal);
  const reviews = useReviews(id);
  const [tab, setTab] = useState<Tab>("overview");
  const [stopping, setStopping] = useState(false);
  const openPnl = useOpenPnl(summary);

  const start = useStartStrategy();
  const kill = useKillStrategy();
  const release = useReleaseStrategy();
  const schedule = useScheduleStrategy();

  const run = async (label: string, work: () => Promise<unknown>) => {
    try {
      await work();
      notify(label);
    } catch (error) {
      notify(error instanceof Error ? error.message : String(error));
    }
  };

  const gone =
    list.isSuccess &&
    !summary &&
    (detail.isSuccess || (detail.error instanceof ApiError && detail.error.status === 404));
  const failed =
    summary || detail.data || gone ? undefined : (failureOf(list) ?? failureOf(detail));
  if (failed) {
    return (
      <Page title="Strategy" back={{ to: "/strategies", label: "Strategies" }}>
        <div className="tile">
          <TableFailed what="This strategy" failure={failed} />
        </div>
      </Page>
    );
  }
  if (gone) {
    return (
      <Page title="Strategy not found" back={{ to: "/strategies", label: "Strategies" }}>
        <div className="tile empty">
          <h2>No strategy with id {id}</h2>
          <p className="note">
            It may have been deleted by your agent. <Link to="/strategies">All strategies ›</Link>
          </p>
        </div>
      </Page>
    );
  }

  const definition = detail.data?.definition;
  const name = summary?.name ?? detail.data?.name ?? "";
  const totals = ledger.data?.totals;
  const openRun = ledger.data?.runs.find((r) => r.status !== "ended");
  const killed = summary?.state === "killed";
  const busy = summary?.pending === "kill" || summary?.pending === "stop";
  const canStart =
    summary?.kind === "options" &&
    !killed &&
    !summary.active_run &&
    summary.pending !== "start" &&
    (summary.state === "stopped" || summary.state === "scheduled");
  const entersOnSchedule =
    summary?.kind === "options" &&
    Boolean((definition as OptionsDefinition | undefined)?.entry_time);
  const callsToday = (signals.data?.calls ?? []).filter((c) => isToday(c.received_at, now));

  return (
    <Page
      title={name || "Strategy"}
      back={{ to: "/strategies", label: "Strategies" }}
      badges={
        summary && (
          <span className="inline-flex items-center gap-2">
            <span className="badge">{summary.kind === "options" ? "Options" : "Signal"}</span>
            <StateBadge strategy={summary} />
            {summary.pending && (
              <span className="note">
                {
                  {
                    kill: "closing legs…",
                    stop: "stopping…",
                    start: "starting…",
                    close_leg: "closing a leg…",
                    signal: "",
                  }[summary.pending]
                }
              </span>
            )}
          </span>
        )
      }
      actions={
        summary && (
          <span className="inline-flex items-center gap-2">
            {entersOnSchedule && !killed && (
              <button
                type="button"
                className="btn"
                disabled={schedule.isPending || (!summary.scheduled && !broker)}
                onClick={() =>
                  run(
                    summary.scheduled
                      ? `${name} no longer enters on its schedule.`
                      : `${name} enters on its schedule from now on.`,
                    () =>
                      schedule.mutateAsync({
                        strategyId: id,
                        broker: summary.scheduled ? null : (broker ?? null),
                      }),
                  )
                }
              >
                {summary.scheduled ? "Unschedule" : "Schedule"}
              </button>
            )}
            {canStart && (
              <button
                type="button"
                className="btn"
                data-variant="primary"
                disabled={!broker || !marketOpen || start.isPending}
                onClick={() =>
                  run(`Starting ${name}: it enters within a second.`, () =>
                    start.mutateAsync({ strategyId: id, broker: broker ?? "" }),
                  )
                }
              >
                {marketOpen ? "Start" : "Market closed"}
              </button>
            )}
            {summary.active_run && !killed && (
              <button
                type="button"
                className="btn"
                disabled={busy}
                onClick={() => setStopping(true)}
              >
                Stop
              </button>
            )}
            {killed ? (
              <button
                type="button"
                className="btn"
                disabled={release.isPending || summary.pending === "kill"}
                title={summary.pending === "kill" ? "Its legs are still closing" : undefined}
                onClick={() =>
                  run(`Released ${name}'s kill switch.`, () => release.mutateAsync(id))
                }
              >
                Release
              </button>
            ) : (
              <HoldButton
                label="Hold to kill"
                onConfirm={() =>
                  run(`Killed ${name}: locked, and its legs close at the market.`, () =>
                    kill.mutateAsync(id),
                  )
                }
              />
            )}
          </span>
        )
      }
    >
      <p className="note" style={{ margin: "-20px 0 24px" }}>
        {summary
          ? `${summary.kind === "options" ? "Options on" : "Alerts trade"} ${summary.underlying} · `
          : ""}
        <code className="code">{id}</code>
      </p>

      <div className="stats">
        <StatCard
          label="Open"
          testId="open-run"
          value={loaded(list, () => <Money value={summary?.active_run ? openPnl : null} />)}
          note={
            summary?.active_run
              ? `${rupees(openRun?.charges ?? 0)} charges so far`
              : summary
                ? "no open run"
                : undefined
          }
        />
        <StatCard
          label="All time, after costs"
          value={loaded(ledger, ({ totals: t }) =>
            t.runs ? <Money value={t.net_pnl} /> : <span className="missing">{MISSING}</span>,
          )}
          note={
            totals
              ? [`${ledger.data?.total_runs ?? 0} runs`, winRate(totals.wins, totals.runs)]
                  .filter(Boolean)
                  .join(" · ")
              : undefined
          }
        />
        {signal ? (
          <>
            <StatCard
              label="Alerts today"
              value={loaded(signals, () => callsToday.length, 40)}
              note={
                signals.data
                  ? `${callsToday.filter((c) => c.result !== "accepted").length} not acted on`
                  : undefined
              }
            />
            <StatCard
              label="Daily loss limit"
              value={
                definition?.daily_loss_limit != null ? (
                  <span style={{ fontSize: 18 }}>{rupees(definition.daily_loss_limit)}</span>
                ) : (
                  <span className="missing">none</span>
                )
              }
              note={
                definition?.daily_loss_limit != null && summary
                  ? `${rupees(Math.max(0, -summary.today_pnl))} used today`
                  : undefined
              }
            />
          </>
        ) : (
          <>
            <StatCard
              label="Max drawdown"
              value={loaded(ledger, ({ totals: t }) => (
                <Money value={t.runs ? -t.max_drawdown : null} />
              ))}
              note="net, run by run"
            />
            <StatCard
              label="Schedule"
              value={
                <span style={{ fontSize: 18 }}>
                  {definition?.entry_time
                    ? `${weekdaysText((definition as OptionsDefinition).weekdays)} ${definition.entry_time.slice(0, 5)}`
                    : "On command"}
                </span>
              }
              note={
                definition
                  ? [
                      definition.exit_time
                        ? `square off ${definition.exit_time.slice(0, 5)}`
                        : null,
                      entersOnSchedule ? (summary?.scheduled ? "on" : "off") : null,
                    ]
                      .filter(Boolean)
                      .join(" · ")
                  : undefined
              }
            />
          </>
        )}
      </div>

      <div className="toolbar">
        <Segmented<Tab>
          label="Sections"
          value={tab}
          onChange={setTab}
          segments={[
            { value: "overview", label: "Overview" },
            { value: "runs", label: "Runs", count: ledger.data?.total_runs },
            { value: "ledger", label: "Ledger" },
            ...(signal
              ? [{ value: "signals" as const, label: "Signals", count: signals.data?.calls.length }]
              : []),
            { value: "reviews", label: "Reviews", count: reviews.data?.jobs.length },
          ]}
        />
      </div>

      {tab === "overview" && (
        <Overview
          id={id}
          summary={summary}
          definition={definition}
          ledger={ledger.data}
          signals={signal ? signals.data : undefined}
          reviews={reviews.data?.jobs}
          marketOpen={marketOpen}
          broker={broker}
          reviewSchedule={detail.data?.review_schedule}
        />
      )}
      {tab === "runs" && <RunsTab ledger={ledger} />}
      {tab === "ledger" && <LedgerTab ledger={ledger} />}
      {tab === "signals" && signal && <SignalsTab signals={signals} />}
      {tab === "reviews" && (
        <ReviewsTab id={id} reviews={reviews} schedule={detail.data?.review_schedule} />
      )}

      <StopDialog
        strategy={stopping && summary ? summary : null}
        onClose={() => setStopping(false)}
        onDone={(message) => {
          setStopping(false);
          notify(message);
        }}
      />
    </Page>
  );
}
