import { Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router";
import {
  type Script,
  useOrders,
  useScripts,
  useStartScript,
  useStopScript,
} from "../../api/queries";
import { type Column, DataTable } from "../../components/DataTable";
import { Page } from "../../components/Page";
import { TableSkeleton } from "../../components/TableStates";
import { MISSING, qty } from "../../lib/format";
import {
  atLimit,
  lastRunText,
  memoryText,
  NEW_SCRIPT_PROMPT,
  runtime,
  type ScriptState,
  scheduleText,
  scriptState,
  stateBadge,
} from "../../lib/scripts";
import { useActions } from "../../shell/actions";
import { useLive, useServerNow } from "../../stream/StreamProvider";

export type Asked = Record<string, "start" | "stop">;

/**
 * Starts and stops sent from this page, until the daemon has carried them
 * out (about a second) or ten seconds have passed.
 */
export function useAsked(scripts: Script[] | undefined) {
  const [asked, setAsked] = useState<Asked>({});
  useEffect(() => {
    if (!scripts) return;
    setAsked((current) => {
      const next = { ...current };
      for (const [id, kind] of Object.entries(current)) {
        const script = scripts.find((s) => s.script_id === id);
        if (!script || script.running === (kind === "start")) delete next[id];
      }
      return Object.keys(next).length === Object.keys(current).length ? current : next;
    });
  }, [scripts]);
  useEffect(() => {
    if (Object.keys(asked).length === 0) return;
    const timer = setTimeout(() => setAsked({}), 10_000);
    return () => clearTimeout(timer);
  }, [asked]);
  return [
    asked,
    (id: string, kind: "start" | "stop") => setAsked((a) => ({ ...a, [id]: kind })),
  ] as const;
}

export function ScriptBadge({ state }: { state: ScriptState }) {
  const badge = stateBadge(state);
  return (
    <span className="badge" data-tone={badge.tone} data-testid="script-state">
      {badge.label}
    </span>
  );
}

/** Ticks every second while something runs, for runtimes. */
export function useTick(on: boolean): Date {
  const serverNow = useServerNow();
  const [now, setNow] = useState(serverNow);
  useEffect(() => {
    setNow(serverNow());
    if (!on) return;
    const timer = setInterval(() => setNow(serverNow()), 1_000);
    return () => clearInterval(timer);
  }, [on, serverNow]);
  return now;
}

/** Start or stop, from a row or the script's page. */
export function useScriptControl(onAsked: (id: string, kind: "start" | "stop") => void) {
  const start = useStartScript();
  const stop = useStopScript();
  const { notify } = useActions();
  const act = async (script: Script, kind: "start" | "stop") => {
    try {
      if (kind === "start") await start.mutateAsync(script.script_id);
      else await stop.mutateAsync(script.script_id);
      onAsked(script.script_id, kind);
      notify(
        kind === "start"
          ? `Starting ${script.name}: it runs within a second.`
          : `Stopping ${script.name}: killed if it hasn't ended in 5 seconds.`,
      );
    } catch (error) {
      notify(error instanceof Error ? error.message : String(error));
    }
  };
  return { act, busy: start.isPending || stop.isPending };
}

export function Scripts() {
  const { status } = useLive();
  const list = useScripts();
  const orders = useOrders(status?.broker);
  const navigate = useNavigate();
  const { notify } = useActions();
  const scripts = list.data?.scripts;
  const limits = list.data?.limits ?? undefined;
  const [asked, ask] = useAsked(scripts);
  const { act, busy } = useScriptControl(ask);
  const now = useTick(scripts?.some((s) => s.running) ?? false);

  const ordersToday = (id: string) =>
    orders.data?.orders.filter((o) => o.triggered_by === `script:${id}`).length;

  const columns: Column<Script>[] = [
    {
      key: "script",
      head: "Script",
      align: "left",
      cell: (s) => (
        <Link to={`/scripts/${s.script_id}`} className="row-link">
          {s.name}
        </Link>
      ),
      sub: (s) => <code className="code">{s.script_id}</code>,
    },
    {
      key: "state",
      head: "State",
      align: "left",
      cell: (s) => <ScriptBadge state={scriptState(s, asked[s.script_id])} />,
    },
    {
      key: "schedule",
      head: "Schedule",
      align: "left",
      cell: (s) => scheduleText(s.schedule) ?? <span className="muted">only when started</span>,
    },
    {
      key: "last",
      head: "Last run",
      align: "left",
      cell: (s) => lastRunText(s.last_run, now) ?? <span className="muted">never</span>,
    },
    {
      key: "runtime",
      head: "Runtime",
      cell: (s) =>
        s.last_run ? runtime(s.last_run, now) : <span className="missing">{MISSING}</span>,
    },
    {
      key: "memory",
      head: "Peak memory",
      cell: (s) => {
        const peak = s.last_run?.peak_memory_mb;
        const text = memoryText(peak, limits?.memory_mb);
        if (text === null) return <span className="missing">{MISSING}</span>;
        return (
          <span className={atLimit(peak, limits?.memory_mb) ? "down" : undefined}>{text}</span>
        );
      },
    },
    {
      key: "orders",
      head: "Orders today",
      cell: (s) => {
        const count = ordersToday(s.script_id);
        return count === undefined ? <span className="missing">{MISSING}</span> : qty(count);
      },
    },
  ];

  return (
    <Page
      title="Scripts"
      count={scripts?.length}
      actions={
        <button
          type="button"
          className="btn"
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(NEW_SCRIPT_PROMPT);
              notify("Copied. Paste it into Claude Code or Codex and say what the script does.");
            } catch {
              notify(`Ask your agent: ${NEW_SCRIPT_PROMPT}`);
            }
          }}
        >
          <Sparkles size={15} aria-hidden />
          Ask Claude to write one
        </button>
      }
    >
      <p className="note" style={{ margin: "-20px 0 24px" }}>
        Your own Python, run by OpenTicker with its own key
        {limits
          ? `, ${qty(limits.memory_mb)} MB of memory and ${qty(limits.cpu_seconds / 60)} CPU minutes a run`
          : ""}
        . Paper orders only.
      </p>
      <div className="tile" data-flush="true">
        {list.isPending ? (
          <TableSkeleton label="Loading scripts" rows={3} />
        ) : list.isError ? (
          <div className="empty" role="alert">
            <h2>Scripts didn't load</h2>
            <p className="note">{list.error.message}</p>
            <button type="button" className="btn" onClick={() => list.refetch()}>
              Try again
            </button>
          </div>
        ) : scripts?.length === 0 ? (
          <div className="empty">
            <h2>No scripts yet</h2>
            <p className="note">
              Your agent writes and uploads them: ask Claude Code or Codex for a script that trails
              a stop, scans for gaps, or anything else in Python.
            </p>
          </div>
        ) : (
          <DataTable
            label="Scripts"
            columns={columns}
            rows={scripts ?? []}
            rowKey={(s) => s.script_id}
            onSelect={(id) => navigate(`/scripts/${id}`)}
            actions={(s) => {
              const state = scriptState(s, asked[s.script_id]);
              if (state === "starting" || state === "stopping") return null;
              return s.running ? (
                <button
                  type="button"
                  className="btn"
                  data-size="sm"
                  disabled={busy}
                  onClick={() => act(s, "stop")}
                >
                  Stop
                </button>
              ) : (
                <button
                  type="button"
                  className="btn"
                  data-variant="primary"
                  data-size="sm"
                  disabled={busy}
                  onClick={() => act(s, "start")}
                >
                  Start
                </button>
              );
            }}
          />
        )}
      </div>
      <p className="note" style={{ marginTop: 16 }}>
        Scripts are written and changed by your agent. Here you start, stop and schedule them, and
        read what they print.
      </p>
    </Page>
  );
}
