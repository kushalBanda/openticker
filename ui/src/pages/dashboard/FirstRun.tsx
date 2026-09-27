import { Check } from "lucide-react";
import { Link } from "react-router";
import type { Schemas } from "../../api/client";
import { useSyncInstruments } from "../../api/queries";
import { CopyLine } from "../../components/CopyLine";
import { qty, rupees } from "../../lib/format";
import { useActions } from "../../shell/actions";
import { brokerTitle } from "../settings/BrokerSection";

const CLAUDE = "claude mcp add openticker -- uv run openticker-mcp";
const CODEX = "codex mcp add openticker -- uv run openticker-mcp";

type Setup = Schemas["SetupResult"];

function Step({
  n,
  done,
  now,
  title,
  children,
  action,
}: {
  n: number;
  done: boolean;
  now: boolean;
  title: string;
  children: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <li className="step" data-state={done ? "done" : now ? "now" : "pending"}>
      <span className="step-n" aria-hidden>
        {done ? <Check size={14} /> : n}
      </span>
      <div className="grow min-w-0">
        <div className="step-title">
          {title}
          {done && <span className="sr-only"> (done)</span>}
        </div>
        <div className="note">{children}</div>
      </div>
      {action}
    </li>
  );
}

/**
 * The Dashboard before the first paper fill (DESIGN.md Hero, Setup
 * Checklist): what OpenTicker is in one sentence, and the four steps, each
 * turning done from what the server sees.
 */
export function FirstRun({
  setup,
  funds,
}: {
  setup: Setup;
  funds: Schemas["FundsResult"] | undefined;
}) {
  const sync = useSyncInstruments();
  const { notify } = useActions();
  const broker = brokerTitle(setup.broker);
  const steps = [
    setup.broker_connected,
    setup.instrument_count > 0,
    setup.agent_seen !== null,
    setup.first_fill_at !== null,
  ];
  const current = steps.indexOf(false);

  return (
    <>
      <section className="hero" aria-labelledby="hero-title">
        <span className="badge">Paper trading · NSE · BSE · NFO</span>
        <h1 id="hero-title">Your agent trades. You watch.</h1>
        <p>
          OpenTicker is running on this laptop. Four steps and Claude or Codex can place paper
          orders you can follow here, live.
        </p>
        <div className="hero-actions">
          {setup.broker_connected ? (
            <a className="btn" data-variant="primary" data-size="lg" href="#setup">
              See what's left
            </a>
          ) : (
            <Link className="btn" data-variant="primary" data-size="lg" to="/settings">
              Connect {broker}
            </Link>
          )}
          <a className="btn" data-variant="outline" data-size="lg" href="#setup">
            See the four steps
          </a>
        </div>
        <div className="hero-command">
          <CopyLine text={CLAUDE} label="Copy the Claude Code command" />
        </div>
      </section>

      <div className="first-run-grid">
        <section className="tile" id="setup" aria-labelledby="setup-title">
          <h2 className="tile-title" id="setup-title">
            Get started
          </h2>
          <ol className="checklist">
            <Step
              n={1}
              done={steps[0] === true}
              now={current === 0}
              title={`Connect ${broker}`}
              action={
                !steps[0] && (
                  <Link className="btn" data-variant="primary" data-size="sm" to="/settings">
                    Connect
                  </Link>
                )
              }
            >
              Prices come from your {broker === "Zerodha" ? "Kite" : broker} account. Orders stay in
              the paper account; nothing reaches your broker.
            </Step>
            <Step
              n={2}
              done={steps[1] === true}
              now={current === 1}
              title="Sync instruments"
              action={
                !steps[1] && (
                  <button
                    type="button"
                    className="btn"
                    data-size="sm"
                    disabled={!setup.broker_connected || sync.isPending}
                    onClick={() =>
                      sync.mutate(setup.broker, {
                        onSuccess: (done) =>
                          notify(`${qty(done.instrument_count)} instruments synced`),
                        onError: (e) => notify(`Sync failed: ${e.message}`),
                      })
                    }
                  >
                    {sync.isPending ? "Syncing…" : "Sync now"}
                  </button>
                )
              }
            >
              {steps[1]
                ? `${qty(setup.instrument_count)} contracts listed.`
                : "Downloads today's contracts (about 90,000) so symbols can be searched. Takes around 20 seconds."}
            </Step>
            <Step n={3} done={steps[2] === true} now={current === 2} title="Connect an agent">
              {setup.agent_seen
                ? `${setup.agent_seen} has called OpenTicker.`
                : "Done when OpenTicker sees its first call."}
              {!steps[2] && (
                <div className="step-commands">
                  <CopyLine text={CLAUDE} label="Copy the Claude Code command" />
                  <CopyLine text={CODEX} label="Copy the Codex command" />
                  <span>
                    Doing research? Open the <code>labs/</code> folder in Claude Code or Codex: it's
                    already set up.
                  </span>
                </div>
              )}
            </Step>
            <Step
              n={4}
              done={steps[3] === true}
              now={current === 3}
              title="Place a first paper order"
            >
              Ask your agent to "buy 1 share of RELIANCE", or press ⌘K and place one yourself.
            </Step>
          </ol>
        </section>
        <section className="tile" aria-labelledby="paper-title">
          <h2 className="tile-title" id="paper-title">
            Paper account
          </h2>
          <div className="kv settings-kv">
            <span className="muted">Capital</span>
            <span className="tabular">{rupees(funds?.total_capital)}</span>
            <span className="muted">Available</span>
            <span className="tabular">{rupees(funds?.available_cash)}</span>
            <span className="muted">Used margin</span>
            <span className="tabular">{rupees(funds?.used_margin)}</span>
          </div>
          <p className="note settings-note">
            Every fill pays the bid or ask plus Indian charges, so paper P&L is close to what the
            same trades would make live.
          </p>
        </section>
      </div>
    </>
  );
}
