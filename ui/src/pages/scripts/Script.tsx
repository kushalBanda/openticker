import { lazy, Suspense, useState } from "react";
import { useParams } from "react-router";
import {
  type ScriptRun,
  useOrders,
  useScript,
  useScriptLogs,
  useScriptSource,
  useScripts,
} from "../../api/queries";
import { type Column, DataTable } from "../../components/DataTable";
import { Page } from "../../components/Page";
import { Segmented } from "../../components/Segmented";
import { Select } from "../../components/Select";
import { TableEmpty, TableSkeleton } from "../../components/TableStates";
import { MISSING, qty } from "../../lib/format";
import {
  atLimit,
  endText,
  memoryText,
  runtime,
  scheduleText,
  scriptState,
  stamp,
  startedBy,
} from "../../lib/scripts";
import { useLive } from "../../stream/StreamProvider";
import { OrderBook } from "../orders/OrderBook";
import { ScheduleDialog } from "./ScheduleDialog";
import { ScriptBadge, useAsked, useScriptControl, useTick } from "./Scripts";

// CodeMirror loads with the first script page, not with the app.
const CodeView = lazy(() =>
  import("../../components/CodeView").then((m) => ({ default: m.CodeView })),
);

type Tab = "logs" | "source" | "runs" | "orders";

function CodeBox({ children }: { children: React.ReactNode }) {
  return (
    <div className="tile code-tile">
      <Suspense fallback={<div className="skeleton" style={{ height: "100%" }} />}>
        {children}
      </Suspense>
    </div>
  );
}

/**
 * One hosted script (ADR 25): its state and controls, and what it printed,
 * followed live while it runs.
 */
export function Script() {
  const { id = "" } = useParams();
  const { status } = useLive();
  const detail = useScript(id);
  const list = useScripts();
  const orders = useOrders(status?.broker);
  const script = detail.data?.script;
  const runs = detail.data?.runs ?? [];
  const limits = list.data?.limits ?? undefined;
  const [asked, ask] = useAsked(script ? [script] : undefined);
  const { act, busy } = useScriptControl(ask);
  const [tab, setTab] = useState<Tab>("logs");
  const [picked, setPicked] = useState<string | null>(null);
  const [scheduling, setScheduling] = useState(false);
  const now = useTick(script?.running ?? false);

  const run: ScriptRun | undefined = runs.find((r) => r.run_id === picked) ?? runs[0];
  const live = run !== undefined && run.ended_at === null;
  const logs = useScriptLogs(id, run?.run_id, live && tab === "logs");
  const source = useScriptSource(id, script?.sha256, tab === "source");
  const mine = (orders.data?.orders ?? []).filter((o) => o.triggered_by === `script:${id}`);
  const state = script ? scriptState(script, asked[id]) : null;

  if (detail.isError) {
    return (
      <Page title="Script" back={{ to: "/scripts", label: "Scripts" }}>
        <div className="tile empty" role="alert">
          <h2>No script {id}</h2>
          <p className="note">{detail.error.message}</p>
        </div>
      </Page>
    );
  }

  const runColumns: Column<ScriptRun>[] = [
    {
      key: "started",
      head: "Started",
      align: "left",
      cell: (r) => stamp(r.started_at, now),
      sub: (r) => `by ${startedBy(r.trigger)}`,
    },
    {
      key: "ended",
      head: "Ended",
      align: "left",
      cell: (r) =>
        r.ended_at ? (
          <span className={r.stop_reason === "exited" ? undefined : "muted"}>{endText(r)}</span>
        ) : (
          <span className="badge" data-tone="accent">
            {r.status === "stopping" ? "Stopping" : "Running"}
          </span>
        ),
      sub: (r) => r.stop_detail ?? undefined,
      wrap: true,
    },
    { key: "runtime", head: "Runtime", cell: (r) => runtime(r, now) },
    {
      key: "memory",
      head: "Peak memory",
      cell: (r) => {
        const text = memoryText(r.peak_memory_mb, limits?.memory_mb);
        if (text === null) return <span className="missing">{MISSING}</span>;
        return (
          <span className={atLimit(r.peak_memory_mb, limits?.memory_mb) ? "down" : undefined}>
            {text}
          </span>
        );
      },
    },
  ];

  return (
    <Page
      title={script?.name ?? "Script"}
      back={{ to: "/scripts", label: "Scripts" }}
      badges={state && <ScriptBadge state={state} />}
      actions={
        script && (
          <span className="flex items-center gap-2">
            <button
              type="button"
              className="btn"
              data-variant="ghost"
              onClick={() => setScheduling(true)}
            >
              Schedule…
            </button>
            {script.running ? (
              <button
                type="button"
                className="btn"
                disabled={busy || state === "stopping"}
                onClick={() => act(script, "stop")}
              >
                Stop
              </button>
            ) : (
              <button
                type="button"
                className="btn"
                data-variant="primary"
                disabled={busy || state === "starting"}
                onClick={() => act(script, "start")}
              >
                Start
              </button>
            )}
          </span>
        )
      }
    >
      <p className="note" style={{ margin: "-20px 0 24px" }}>
        {script
          ? [
              scheduleText(script.schedule) ?? "Runs only when started",
              limits &&
                `limits ${qty(limits.memory_mb)} MB, ${qty(limits.cpu_seconds / 60)} CPU minutes a run`,
            ]
              .filter(Boolean)
              .join(" · ")
          : ""}{" "}
        · <code className="code">{id}</code>
      </p>

      <div className="toolbar">
        <Segmented<Tab>
          label="Sections"
          value={tab}
          onChange={setTab}
          segments={[
            { value: "logs", label: "Logs" },
            { value: "source", label: "Source" },
            { value: "runs", label: "Runs", count: runs.length },
            { value: "orders", label: "Orders", count: orders.data ? mine.length : undefined },
          ]}
        />
        <span className="flex-1" />
        {tab === "logs" && runs.length > 1 && (
          <Select<string>
            label="Run"
            value={run?.run_id ?? ""}
            onChange={setPicked}
            options={runs.map((r) => ({
              value: r.run_id,
              label: stamp(r.started_at, now),
              hint: r.ended_at ? endText(r) : "running",
            }))}
          />
        )}
      </div>

      {tab === "logs" &&
        (detail.isPending ? (
          <div className="tile code-tile skeleton" />
        ) : !run ? (
          <div className="tile empty">
            <h2>Not run yet</h2>
            <p className="note">Start it, and what it prints shows here as it prints it.</p>
          </div>
        ) : (
          <>
            <CodeBox>
              <CodeView
                language="log"
                label={`Log of ${script?.name ?? "the script"}`}
                follow={live}
                text={(logs.data?.lines ?? []).join("\n")}
              />
            </CodeBox>
            <p className="note" style={{ marginTop: 8 }} aria-live="polite">
              {live ? (
                <>
                  <span className="live-dot" aria-hidden /> Following: started{" "}
                  {stamp(run.started_at, now)} by {startedBy(run.trigger)}, running{" "}
                  {runtime(run, now)}.
                </>
              ) : (
                `Started ${stamp(run.started_at, now)} by ${startedBy(run.trigger)}; ended after ${runtime(run, now)}: ${run.stop_detail ?? endText(run)}.`
              )}
              {logs.data?.truncated ? " Earlier lines left out: the last 1,000 show." : ""}
            </p>
          </>
        ))}

      {tab === "source" && (
        <>
          <CodeBox>
            {source.data !== undefined ? (
              <CodeView
                language="python"
                label={`Source of ${script?.name ?? "the script"}`}
                text={source.data}
              />
            ) : (
              <div className="skeleton" style={{ height: "100%" }} />
            )}
          </CodeBox>
          <p className="note" style={{ marginTop: 8 }}>
            Source is read-only here. Ask your agent to change it; a running script can't be changed
            until it stops.
          </p>
        </>
      )}

      {tab === "runs" && (
        <div className="tile" data-flush="true">
          {detail.isPending ? (
            <TableSkeleton label="Loading runs" />
          ) : runs.length === 0 ? (
            <TableEmpty>Not run yet.</TableEmpty>
          ) : (
            <DataTable
              label="Runs"
              columns={runColumns}
              rows={runs}
              rowKey={(r) => r.run_id}
              onSelect={(runId) => {
                setPicked(runId);
                setTab("logs");
              }}
            />
          )}
        </div>
      )}

      {tab === "orders" && (
        <OrderBook
          broker={status?.broker}
          orders={mine}
          all={mine}
          loading={orders.isPending}
          cancelAllShown={false}
          noneYet={`No orders from ${script?.name ?? "this script"} today.`}
        />
      )}

      {script && scheduling && (
        <ScheduleDialog script={script} open={scheduling} onClose={() => setScheduling(false)} />
      )}
    </Page>
  );
}
