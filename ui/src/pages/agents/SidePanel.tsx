import { useState } from "react";
import { Link } from "react-router";
import { type AgentThread, type ChatChange, useScripts, useStrategies } from "../../api/queries";
import { direction, rupees } from "../../lib/format";
import { lastRunText, stateBadge as scriptBadge, scriptState } from "../../lib/scripts";
import { stateBadge, verdictBadge } from "../../lib/strategies";
import { tokens } from "../../lib/threads";
import { useServerNow } from "../../stream/StreamProvider";
import { ChangeRows } from "./Changes";
import { Printed } from "./Thread";

type Tab = "subject" | "changes" | "log";

/** What a chat is about, by its folder: a strategy (or its review), a script, a day. */
function subjectTab(thread: AgentThread): string | null {
  if (!thread.subject) return null;
  if (thread.folder === "strategy" || thread.folder === "review") return "Strategy";
  if (thread.folder === "script") return "Script";
  if (thread.folder === "debrief") return "Day";
  return null;
}

/**
 * Beside a chat (⌥⌘B), the Codex app's side panel for a trading desk (ADR 40):
 * what the chat is about, live; everything its agent changed; what it printed.
 */
export function SidePanel({
  thread,
  changes,
  loading,
}: {
  thread: AgentThread;
  changes: readonly ChatChange[];
  loading: boolean;
}) {
  const subject = subjectTab(thread);
  const [tab, setTab] = useState<Tab>("changes");
  const shown = tab === "subject" && !subject ? "changes" : tab;
  const tabs: { id: Tab; label: string }[] = [
    ...(subject ? [{ id: "subject" as const, label: subject }] : []),
    { id: "changes", label: "Changes" },
    { id: "log", label: "Log" },
  ];
  const last = thread.turns.at(-1)?.job;
  return (
    <aside className="aw-side" aria-label="Side panel">
      <div className="aw-tabs" role="tablist" aria-label="Side panel">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            id={`aw-tab-${t.id}`}
            aria-selected={shown === t.id}
            aria-controls="aw-side-body"
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div
        className="aw-side-body"
        id="aw-side-body"
        role="tabpanel"
        aria-labelledby={`aw-tab-${shown}`}
      >
        {shown === "subject" && <Subject thread={thread} />}
        {shown === "changes" && (
          <>
            <section className="aw-side-sec">
              <h3>What this chat changed</h3>
              <p className="note">
                Orders, strategies, watchlists, scripts and notes its agent touched, from the audit
                log. Paper only.
              </p>
            </section>
            {loading ? (
              <p className="note" aria-busy="true">
                Loading changes
              </p>
            ) : changes.length === 0 ? (
              <p className="note">Nothing on your desk changed from this chat yet.</p>
            ) : (
              <ul className="aw-side-list">
                <ChangeRows entries={changes} showTime />
              </ul>
            )}
            <Spent thread={thread} />
          </>
        )}
        {shown === "log" &&
          (last ? (
            <Printed jobId={last.job_id} />
          ) : (
            <p className="note">Nothing ran in this chat yet.</p>
          ))}
      </div>
    </aside>
  );
}

function Subject({ thread }: { thread: AgentThread }) {
  if (thread.folder === "script") return <ScriptFacts id={thread.subject ?? ""} />;
  if (thread.folder === "debrief") {
    return (
      <section className="aw-side-sec">
        <h3>{thread.subject_name ?? thread.subject}</h3>
        <p className="note">The day's trades, P&L, lessons and debrief are on its page.</p>
        <Link className="link" to={`/brain/days/${thread.subject}`}>
          Open the day
        </Link>
      </section>
    );
  }
  return <StrategyFacts id={thread.subject ?? ""} />;
}

function StrategyFacts({ id }: { id: string }) {
  const list = useStrategies();
  if (list.isPending)
    return (
      <p className="note" aria-busy="true">
        Loading the strategy
      </p>
    );
  if (list.isError) {
    return (
      <p className="note" role="alert">
        The strategy didn't load: {list.error.message}
      </p>
    );
  }
  const s = list.data.strategies.find((one) => one.strategy_id === id);
  if (!s) return <p className="note">This strategy was deleted. Its chats stay here.</p>;
  const state = stateBadge(s.state);
  const verdict = verdictBadge(s.last_review?.verdict);
  return (
    <section className="aw-side-sec">
      <h3>{s.name}</h3>
      <dl className="aw-kv">
        <dt>State</dt>
        <dd>
          <span className="badge" data-tone={state.tone}>
            {state.label}
          </span>
        </dd>
        <dt>Today, after charges</dt>
        <dd className={direction(s.today_pnl)}>{rupees(s.today_pnl, { sign: true })}</dd>
        <dt>All time, after charges</dt>
        <dd className={direction(s.net_pnl)}>{rupees(s.net_pnl, { sign: true })}</dd>
        <dt>Runs</dt>
        <dd>{s.runs}</dd>
        <dt>Latest review</dt>
        <dd>{verdict ? verdict.label : "None yet"}</dd>
      </dl>
      <Link className="link" to={`/strategies/${s.strategy_id}`}>
        Open the strategy
      </Link>
    </section>
  );
}

function ScriptFacts({ id }: { id: string }) {
  const list = useScripts();
  const now = useServerNow();
  if (list.isPending)
    return (
      <p className="note" aria-busy="true">
        Loading the script
      </p>
    );
  if (list.isError) {
    return (
      <p className="note" role="alert">
        The script didn't load: {list.error.message}
      </p>
    );
  }
  const script = list.data.scripts.find((one) => one.script_id === id);
  if (!script) return <p className="note">This script was deleted. Its chats stay here.</p>;
  const state = scriptBadge(scriptState(script));
  return (
    <section className="aw-side-sec">
      <h3>{script.name}</h3>
      <dl className="aw-kv">
        <dt>State</dt>
        <dd>
          <span className="badge" data-tone={state.tone}>
            {state.label}
          </span>
        </dd>
        <dt>Last run</dt>
        <dd>{lastRunText(script.last_run, now()) ?? "Never run"}</dd>
      </dl>
      <Link className="link" to={`/scripts/${script.script_id}`}>
        Open the script
      </Link>
    </section>
  );
}

/** What the chat has cost so far: its turns, tokens and spend. */
function Spent({ thread }: { thread: AgentThread }) {
  const jobs = thread.turns.map((t) => t.job);
  const used = jobs.reduce((n, j) => n + (j.input_tokens ?? 0) + (j.output_tokens ?? 0), 0);
  const priced = jobs.filter((j) => j.cost_usd != null);
  const cost = priced.reduce((n, j) => n + (j.cost_usd ?? 0), 0);
  return (
    <section className="aw-side-sec">
      <h3>Spent in this chat</h3>
      <dl className="aw-kv">
        <dt>Turns</dt>
        <dd>{jobs.length}</dd>
        <dt>Tokens</dt>
        <dd>{used > 0 ? tokens(used) : "Not reported"}</dd>
        <dt>Cost</dt>
        <dd>{priced.length > 0 ? `$${cost.toFixed(2)}` : "Not reported"}</dd>
      </dl>
    </section>
  );
}
