import { Navigate, useNavigate, useParams } from "react-router";
import {
  useClearManagerOverride,
  useManager,
  useSetManager,
  useSetManagerNumbers,
  useStrategies,
  useWakeManager,
} from "../../api/queries";
import { type Column, DataTable } from "../../components/DataTable";
import { Page } from "../../components/Page";
import { loaded, StatCard } from "../../components/StatCard";
import { failureOf, TableEmpty, TableFailed, TableSkeleton } from "../../components/TableStates";
import { direction, MISSING, rupees } from "../../lib/format";
import {
  asStop,
  disagreement,
  endedToday,
  istDay,
  lineLabel,
  type ManagerLine,
  market,
  nextLook,
  setByLabel,
  tableOrder,
} from "../../lib/manager";
import { useActions } from "../../shell/actions";
import { useServerNow } from "../../stream/StreamProvider";
import { Amount } from "./Amount";
import { DayTape } from "./DayTape";
import { Decisions } from "./Decisions";
import { HowItRuns } from "./HowItRuns";
import { PastDay } from "./PastDay";
import { Plan } from "./Plan";
import { Split } from "./Split";

/** The desk manager's page (ADR 41): what it decided, and every number it set. */
export function Manager() {
  const manager = useManager();
  const data = manager.data;
  const switchManager = useSetManager();
  const wake = useWakeManager();
  const { notify } = useActions();
  const serverNow = useServerNow();
  const today = istDay(serverNow());
  const navigate = useNavigate();
  // A past day reads back as it closed (ADR 43); today is the live page.
  const { day } = useParams();
  if (day === today) return <Navigate to="/manager" replace />;
  const past = day ?? null;
  return (
    <Page
      title="Manager"
      badges={
        data && (
          <span className="badge" data-tone={data.enabled ? "accent" : undefined}>
            {data.enabled ? "On" : "Off"}
          </span>
        )
      }
      actions={
        past ? (
          <button type="button" className="btn" onClick={() => navigate("/manager")}>
            Back to today
          </button>
        ) : (
          data && (
            <>
              {data.enabled && (
                <button
                  type="button"
                  className="btn"
                  data-variant="primary"
                  disabled={wake.isPending || data.wakes_today >= data.wakes_per_day}
                  title={
                    data.wakes_today >= data.wakes_per_day
                      ? "It used its wakes for today"
                      : "It looks at the desk now; counts against its wakes a day"
                  }
                  onClick={() =>
                    wake
                      .mutateAsync()
                      .then(() => notify("The manager is looking now."))
                      .catch((error: unknown) =>
                        notify(error instanceof Error ? error.message : String(error)),
                      )
                  }
                >
                  Look now
                </button>
              )}
              <button
                type="button"
                className="btn"
                data-variant={data.enabled ? undefined : "primary"}
                disabled={switchManager.isPending}
                onClick={() =>
                  switchManager
                    .mutateAsync({ enabled: !data.enabled })
                    .then((m) =>
                      notify(
                        m.enabled
                          ? "Manager on: it plans each trading day before the open."
                          : "Manager off: it won't wake again. Nothing it started was stopped.",
                      ),
                    )
                    .catch((error: unknown) =>
                      notify(error instanceof Error ? error.message : String(error)),
                    )
                }
              >
                {data.enabled ? "Turn off" : "Turn on"}
              </button>
            </>
          )
        )
      }
    >
      <DayTape selected={past ?? today} today={today} />
      {past ? <PastDay day={past} /> : <TodayBody today={today} />}
    </Page>
  );
}

/** Today's page: live, and every number in it can be changed. */
function TodayBody({ today }: { today: string }) {
  const manager = useManager();
  const data = manager.data;
  const serverNow = useServerNow();
  return (
    <>
      {data?.enabled && data.stalled && (
        <p className="error-line mgr-stalled" role="status">
          {data.stalled === "capped"
            ? `It used its ${data.wakes_per_day} wakes today and won't wake again until tomorrow's plan.`
            : "Its turns keep failing. It tries again every 30 minutes; its thread below says why."}
        </p>
      )}
      <div className="stats">
        <StatCard
          label="Today"
          value={loaded(manager, (m) => rupees(m.desk_today?.net, { sign: true }))}
          tone={direction(data?.desk_today?.net)}
          note={data?.desk_today ? <Split figure={data.desk_today} /> : "after charges"}
        />
        <StatCard
          label="Given to strategies"
          value={loaded(manager, (m) => rupees(m.given, { decimals: 0 }))}
          note={data && `of ${rupees(data.account, { decimals: 0 })}`}
        />
        <StatCard
          label="Next look"
          value={loaded(
            manager,
            (m) => nextLook(m.enabled, m.next_wake_at, m.next_wake_reason, serverNow()).when,
          )}
          note={
            data &&
            nextLook(data.enabled, data.next_wake_at, data.next_wake_reason, serverNow()).why
          }
        />
        <StatCard
          label="Looks today"
          value={loaded(manager, (m) => m.wakes_today)}
          note={data && `of ${data.wakes_per_day} a day`}
        />
      </div>
      <Lines manager={manager} today={today} />
      {data && (
        <div className="mgr-row">
          <Decisions threadId={data.thread_id} />
          <div className="mgr-side">
            <HowItRuns manager={data} />
            <Plan
              plan={data.plan?.day === today ? data.plan : null}
              title="Today's plan"
              empty={
                data.enabled
                  ? "No plan yet today. It sets one before the open."
                  : "Turn the manager on, and it plans each trading day before the open."
              }
            />
          </div>
        </div>
      )}
    </>
  );
}

function Money({ value, crossed }: { value: number | null | undefined; crossed?: boolean }) {
  if (value == null) return <span className="missing">{MISSING}</span>;
  return (
    <span className={crossed ? "down" : direction(value)}>{rupees(value, { sign: true })}</span>
  );
}

function Lines({ manager, today }: { manager: ReturnType<typeof useManager>; today: string }) {
  const failure = failureOf(manager);
  const strategies = useStrategies();
  const ends = new Map(
    (strategies.data?.strategies ?? []).map((s) => [`strategy:${s.strategy_id}`, s.last_run_end]),
  );
  const ended = (l: ManagerLine) => endedToday(ends.get(l.key), today);
  const setNumbers = useSetManagerNumbers();
  const handBack = useClearManagerOverride();
  const { notify } = useActions();
  const save = async (line: ManagerLine, capital: number | null, stop: number | null) => {
    try {
      await setNumbers.mutateAsync([{ key: line.key, capital, stop, reason: "" }]);
    } catch (error) {
      notify(error instanceof Error ? error.message : String(error));
      throw error;
    }
  };
  const columns: Column<ManagerLine>[] = [
    {
      key: "what",
      head: "Strategy",
      align: "left",
      cell: (l) => <span className="inst">{lineLabel(l)}</span>,
      sub: (l) => {
        const end = ended(l);
        const why = disagreement(l);
        if (l.key === "desk") return why ?? "Includes what's still open";
        if (!end) return why;
        return (
          <>
            <span className={end.fault ? "mgr-fault" : undefined}>{end.text}</span>
            {why && <> · {why}</>}
          </>
        );
      },
    },
    {
      key: "capital",
      head: "Capital",
      align: "right",
      cell: (l) =>
        l.key === "desk" ? (
          rupees(l.capital, { decimals: 0 })
        ) : (
          <Amount
            value={l.capital}
            label={`${lineLabel(l)}'s capital`}
            normalize={Math.abs}
            onSave={(capital) => save(l, capital, l.stop)}
          />
        ),
    },
    {
      key: "stop",
      head: "Stop it at",
      align: "right",
      cell: (l) => (
        <Amount
          value={l.stop}
          label={`${lineLabel(l)}'s stop`}
          normalize={asStop}
          onSave={(stop) => save(l, l.capital, stop)}
        />
      ),
    },
    {
      key: "market",
      head: "Market",
      align: "right",
      cell: (l) => <Money value={l.today && market(l.today)} />,
    },
    {
      key: "charges",
      head: "Charges",
      align: "right",
      cell: (l) => <Money value={l.today && -l.today.charges} />,
    },
    {
      key: "today",
      head: "Today",
      align: "right",
      cell: (l) => <Money value={l.today?.net} crossed={l.crossed} />,
      sub: (l) => (l.crossed ? "past its stop" : null),
    },
    {
      key: "by",
      head: "Set by",
      align: "left",
      cell: (l) => (
        <span className="badge" data-tone={l.set_by === "you" ? "accent" : undefined}>
          {setByLabel(l.set_by)}
        </span>
      ),
    },
  ];
  return (
    <div className="tile" data-flush="true">
      <div className="tile-head">
        <h2>Its numbers</h2>
        <span className="flex-1" />
        <span className="note">
          Click a number to change it. Yours stand until you hand them back.
        </span>
      </div>
      {failure ? (
        <TableFailed what="The manager" failure={failure} />
      ) : !manager.data ? (
        <TableSkeleton label="Loading the manager's numbers" />
      ) : manager.data.lines.length === 0 ? (
        <TableEmpty>
          No numbers yet. Once on, the manager sets each strategy's capital and stop before the
          open.
        </TableEmpty>
      ) : (
        <div className="mgr-lines">
          <DataTable
            label="The manager's numbers"
            columns={columns}
            rows={tableOrder(manager.data.lines)}
            rowKey={(l) => l.key}
            actions={(l) =>
              l.set_by === "you" ? (
                <button
                  type="button"
                  className="btn"
                  data-variant="ghost"
                  data-size="sm"
                  disabled={handBack.isPending}
                  onClick={() =>
                    handBack
                      .mutateAsync(l.key)
                      .then(() => notify(`${lineLabel(l)} is the manager's again.`))
                      .catch((error: unknown) =>
                        notify(error instanceof Error ? error.message : String(error)),
                      )
                  }
                >
                  Hand back
                </button>
              ) : null
            }
          />
        </div>
      )}
      <p className="note mgr-lines-note">
        Market is P&L at the prices filled, before charges; Today counts trades closed today,
        whenever the run started. Its stops act when it looks; each strategy's own stop loss acts at
        once.
      </p>
    </div>
  );
}
