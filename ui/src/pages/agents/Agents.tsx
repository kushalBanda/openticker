import { lazy, Suspense, useState } from "react";
import { Link } from "react-router";
import {
  type AgentJob,
  useAgentJobLog,
  useAgentJobs,
  useAgents,
  useReviews,
  useStopAgentJob,
  useStrategies,
  useStrategy,
} from "../../api/queries";
import { CopyLine } from "../../components/CopyLine";
import { type Column, DataTable } from "../../components/DataTable";
import { Dialog } from "../../components/Dialog";
import { Markdown } from "../../components/Markdown";
import { Page } from "../../components/Page";
import { Select } from "../../components/Select";
import { TableEmpty, TableSkeleton } from "../../components/TableStates";
import {
  CONNECT,
  clientLabel,
  harnessLabel,
  jobBadge,
  jobState,
  took,
  why,
} from "../../lib/agents";
import { MISSING, qty } from "../../lib/format";
import { stamp } from "../../lib/scripts";
import { useActions } from "../../shell/actions";
import { useServerNow } from "../../stream/StreamProvider";
import { useTick } from "../scripts/Scripts";
import {
  ReviewNow,
  ReviewScheduleButton,
  scheduleText,
  VerdictBadge,
} from "../strategy/LatestReview";

const CodeView = lazy(() =>
  import("../../components/CodeView").then((m) => ({ default: m.CodeView })),
);

function Clients() {
  const agents = useAgents();
  const serverNow = useServerNow();
  const now = serverNow();
  const clients = agents.data?.clients ?? [];
  return (
    <div className="tile">
      <h2 className="tile-title">Connected agents</h2>
      {agents.isPending ? (
        <TableSkeleton label="Loading agents" />
      ) : agents.isError ? (
        <p className="note" role="alert">
          Agents didn't load: {agents.error.message}
        </p>
      ) : clients.length === 0 ? (
        <p className="note">
          No agent has called OpenTicker yet. Add it to Claude Code or Codex, then ask it for a
          quote.
        </p>
      ) : (
        <table className="table plain" aria-label="Connected agents">
          <tbody>
            {clients.map((c) => (
              <tr key={`${c.name}:${c.transport}`} data-testid="agent-client">
                <td data-align="left">
                  <b>{clientLabel(c.name)}</b>
                  <div className="sub">
                    {c.transport}
                    {c.version ? ` · ${c.version}` : ""}
                  </div>
                </td>
                <td data-align="left">
                  last call <span className="tabular">{stamp(c.last_seen_at, now)}</span>
                  {c.last_tool && (
                    <>
                      {" "}
                      <code className="code">{c.last_tool}</code>
                    </>
                  )}
                </td>
                <td>
                  {qty(c.calls_today)} call{c.calls_today === 1 ? "" : "s"} today
                  <div className="sub">{qty(c.calls)} in all</div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="connect-lines">
        <CopyLine text={CONNECT.claude} label="Copy the Claude Code command" />
        <CopyLine text={CONNECT.codex} label="Copy the Codex command" />
      </div>
      <p className="note" style={{ margin: "8px 0 0" }}>
        Calls are counted once a minute per agent.
      </p>
    </div>
  );
}

/** Pick a strategy, then review it now or set when it is reviewed. */
function ReviewDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const strategies = useStrategies();
  const all = strategies.data?.strategies ?? [];
  const [picked, setPicked] = useState<string>("");
  const id = picked || all[0]?.strategy_id || "";
  const detail = useStrategy(id);
  const reviews = useReviews(id);
  const schedule = detail.data?.review_schedule;
  const when = scheduleText(schedule);
  const summary = all.find((s) => s.strategy_id === id);
  const serverNow = useServerNow();

  return (
    <Dialog open={open} onClose={onClose} title="Review a strategy">
      <p className="note" style={{ margin: 0 }}>
        Your coding agent reads the strategy's ledger after costs, read-only, and writes a verdict
        into its note: keep, change one thing, or retire.
      </p>
      {all.length === 0 ? (
        <p className="note">No strategies yet: there's nothing to review.</p>
      ) : (
        <>
          <div className="field">
            <span className="label" aria-hidden>
              Strategy
            </span>
            <Select<string>
              label="Strategy"
              className="select-wide"
              value={id}
              onChange={setPicked}
              options={all.map((s) => ({
                value: s.strategy_id,
                label: s.name,
                hint: s.kind === "options" ? "Options" : "Signal",
              }))}
            />
          </div>
          <p className="note" style={{ margin: 0 }}>
            {summary?.last_review ? (
              <>
                Last review <VerdictBadge verdict={summary.last_review.verdict} />{" "}
                {stamp(summary.last_review.ended_at, serverNow())}.{" "}
              </>
            ) : (
              "Not reviewed yet. "
            )}
            {when ? `Also reviewed ${when}.` : "Reviewed only when asked."}
          </p>
          <div className="flex items-center gap-2">
            <ReviewScheduleButton key={`${id}:${when ?? "none"}`} id={id} current={schedule} />
            <span className="flex-1" />
            <ReviewNow id={id} reviews={reviews.data?.jobs} variant="primary" />
          </div>
        </>
      )}
    </Dialog>
  );
}

function Reviews({ jobs }: { jobs: AgentJob[] | undefined }) {
  const agents = useAgents();
  const [open, setOpen] = useState(false);
  const settings = agents.data;
  const running = jobs?.filter((j) => j.status === "running" || j.status === "stopping").length;
  const waiting = jobs?.filter((j) => j.status === "pending").length;
  return (
    <div className="tile">
      <div className="flex items-center gap-2">
        <h2 className="tile-title">Review jobs</h2>
        <span className="flex-1" />
        <button type="button" className="btn" data-size="sm" onClick={() => setOpen(true)}>
          Review a strategy…
        </button>
      </div>
      <p className="note" style={{ margin: "10px 0 14px" }}>
        OpenTicker runs your own Claude Code or Codex to review a strategy's ledger, read-only, one
        job at a time.
      </p>
      <dl className="kv">
        <dt className="muted">Harness</dt>
        <dd>{settings ? harnessLabel(settings.harness) : MISSING}</dd>
        <dt className="muted">Running now</dt>
        <dd className="tabular">{running ?? MISSING}</dd>
        <dt className="muted">Waiting</dt>
        <dd className="tabular">{waiting ?? MISSING}</dd>
        <dt className="muted">Started today</dt>
        <dd className="tabular" data-testid="jobs-today">
          {settings ? `${settings.started_today} of ${settings.jobs_per_day}` : MISSING}
        </dd>
        <dt className="muted">Time limit</dt>
        <dd>{settings ? `${settings.timeout_minutes} min a job` : MISSING}</dd>
      </dl>
      <ReviewDialog open={open} onClose={() => setOpen(false)} />
    </div>
  );
}

// The log box fits what was printed: 19px a line, a line wrapping at about
// 84 characters in the 720px dialog, between 4 lines and the full 440px.
const logHeight = (text: string) => {
  const lines = text
    .split("\n")
    .reduce((n, line) => n + Math.max(1, Math.ceil(line.length / 84)), 0);
  return Math.min(440, Math.max(4, lines + 1) * 19 + 24);
};

/** A job's answer and the end of what it printed. */
function JobDialog({ job, onClose }: { job: AgentJob | null; onClose: () => void }) {
  const log = useAgentJobLog(job?.job_id ?? null);
  const text = log.data?.log ?? "";
  const silent = log.data !== undefined && !log.data.log;
  return (
    <Dialog open={job !== null} onClose={onClose} title="Review job" width={720}>
      {job?.summary && <Markdown text={job.summary} />}
      {job && !job.summary && job.end_detail && <p className="note">{job.end_detail}</p>}
      <div className="label job-log-label">What it printed</div>
      {silent ? (
        <p className="note">It printed nothing.</p>
      ) : (
        <div className="code-tile" style={{ height: logHeight(text) }}>
          <Suspense fallback={<div className="skeleton" style={{ height: "100%" }} />}>
            <CodeView
              language="log"
              label="What the agent printed"
              follow={job?.status !== "ended"}
              text={text}
            />
          </Suspense>
        </div>
      )}
      {log.data?.truncated && <p className="note">Older output left out.</p>}
    </Dialog>
  );
}

/**
 * Agents (DESIGN.md): the MCP clients that call OpenTicker, and the review
 * jobs it runs with the user's own coding agent (ADR 29), stopped from here.
 */
export function Agents() {
  const jobs = useAgentJobs();
  const strategies = useStrategies();
  const stop = useStopAgentJob();
  const { notify } = useActions();
  const [reading, setReading] = useState<AgentJob | null>(null);
  const list = jobs.data?.jobs;
  const now = useTick(list?.some((j) => j.status !== "ended") ?? false);
  const name = (id: string) =>
    strategies.data?.strategies.find((s) => s.strategy_id === id)?.name ?? id;

  const columns: Column<AgentJob>[] = [
    {
      key: "strategy",
      head: "Strategy",
      align: "left",
      cell: (j) => (
        <Link to={`/strategies/${j.strategy_id}`} className="row-link">
          {name(j.strategy_id)}
        </Link>
      ),
      sub: (j) => stamp(j.started_at ?? j.created_at, now),
    },
    { key: "why", head: "Why", align: "left", cell: (j) => why(j.trigger), wrap: true },
    { key: "harness", head: "Harness", align: "left", cell: (j) => harnessLabel(j.harness) },
    {
      key: "state",
      head: "State",
      align: "left",
      cell: (j) => {
        const badge = jobBadge(jobState(j));
        return (
          <span className="badge" data-tone={badge.tone} title={j.end_detail ?? undefined}>
            {badge.label}
          </span>
        );
      },
    },
    {
      key: "took",
      head: "Took",
      cell: (j) => took(j, now) ?? <span className="missing">{MISSING}</span>,
    },
    {
      key: "verdict",
      head: "Verdict",
      align: "left",
      cell: (j) =>
        j.verdict ? (
          <VerdictBadge verdict={j.verdict} />
        ) : (
          <span className="missing">{MISSING}</span>
        ),
    },
  ];

  return (
    <Page title="Agents">
      <div className="agents-grid">
        <Clients />
        <Reviews jobs={list} />
      </div>
      <div className="tile" data-flush="true">
        <div className="tile-head">
          <h2>Jobs</h2>
          <span className="note">newest first</span>
        </div>
        {jobs.isPending ? (
          <TableSkeleton label="Loading jobs" rows={3} />
        ) : jobs.isError ? (
          <TableEmpty>{`Jobs didn't load: ${jobs.error.message}`}</TableEmpty>
        ) : list?.length === 0 ? (
          <TableEmpty>
            No jobs yet. Review a strategy to have your coding agent judge its ledger after costs.
          </TableEmpty>
        ) : (
          <DataTable
            label="Agent jobs"
            columns={columns}
            rows={list ?? []}
            rowKey={(j) => j.job_id}
            onSelect={(id) => setReading(list?.find((j) => j.job_id === id) ?? null)}
            actions={(j) =>
              j.status === "pending" || j.status === "running" ? (
                <button
                  type="button"
                  className="btn"
                  data-size="sm"
                  disabled={stop.isPending}
                  onClick={async () => {
                    try {
                      const stopped = await stop.mutateAsync(j.job_id);
                      notify(
                        stopped.status === "ended"
                          ? `Review of ${name(j.strategy_id)} stopped before it started.`
                          : `Stopping the review of ${name(j.strategy_id)}.`,
                      );
                    } catch (error) {
                      notify(error instanceof Error ? error.message : String(error));
                    }
                  }}
                >
                  Stop
                </button>
              ) : null
            }
          />
        )}
      </div>
      <JobDialog job={reading} onClose={() => setReading(null)} />
    </Page>
  );
}
