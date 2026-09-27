import { useState } from "react";
import { useAccount, useCheckCharges, useResetAccount } from "../../api/queries";
import { HoldButton } from "../../components/HoldButton";
import { istDate, qty, rupees } from "../../lib/format";
import { useActions } from "../../shell/actions";

const CONFIRMATION = "RESET";
const failed = (error: unknown) => (error instanceof Error ? error.message : String(error));
const times = (n: number) => `${n % 1 === 0 ? n.toFixed(0) : n}×`;

/**
 * The paper account's settings, read-only (they come from .env), and the
 * reset (ADR 37): a full wipe, held and typed, refused by the server while a
 * strategy or script runs.
 */
export function AccountSection() {
  const account = useAccount();
  const reset = useResetAccount();
  const { notify } = useActions();
  const [typed, setTyped] = useState("");
  const [refused, setRefused] = useState<string | null>(null);
  const data = account.data;
  const leverage = data?.leverage;

  return (
    <section className="tile" id="account" aria-labelledby="account-title">
      <div className="settings-head">
        <h2 id="account-title">Paper account</h2>
      </div>
      {account.isError && (
        <div className="error-line" role="alert">
          {account.error.message}
        </div>
      )}
      <div className="kv settings-kv">
        <span className="muted">Starting capital</span>
        <span className="tabular">{rupees(data?.starting_capital)}</span>
        <span className="muted">Capital cap per position</span>
        <span className="tabular">
          {data ? (data.capital_cap === null ? "None" : rupees(data.capital_cap)) : "—"}
        </span>
        <span className="muted">Leverage</span>
        <span className="tabular">
          {leverage
            ? `MIS ${times(leverage.equity_intraday)} · CNC ${times(leverage.equity_delivery)} · FUT ${times(leverage.futures)} · options ${times(leverage.option_buy)}`
            : "—"}
        </span>
      </div>
      <p className="note settings-note">
        Set in <code>.env</code>; restart <code>openticker-serve</code> to change.
      </p>
      <div className="danger-zone" data-testid="reset-zone">
        <b>Reset paper account</b>
        <p className="note">
          Deletes every paper order, trade and position and restores the starting capital.
          Strategies and scripts must be stopped first. The activity log stays. Can't be undone.
        </p>
        <div className="settings-row">
          <input
            className="input settings-confirm"
            aria-label={`Type ${CONFIRMATION} to confirm`}
            placeholder={`Type ${CONFIRMATION}`}
            autoComplete="off"
            value={typed}
            onChange={(event) => {
              setTyped(event.target.value);
              setRefused(null);
            }}
          />
          <HoldButton
            label="Hold to reset"
            disabled={typed !== CONFIRMATION}
            onConfirm={async () => {
              try {
                const done = await reset.mutateAsync();
                setTyped("");
                setRefused(null);
                notify(
                  `Paper account reset to ${rupees(done.capital)}. ${qty(done.orders)} orders, ${qty(done.trades)} trades and ${qty(done.positions)} open positions deleted.`,
                );
              } catch (e) {
                setRefused(failed(e));
              }
            }}
          />
        </div>
        {refused && (
          <div className="error-line" role="alert">
            {refused}
          </div>
        )}
      </div>
    </section>
  );
}

export function ChargesSection({ broker, connected }: { broker: string; connected: boolean }) {
  const account = useAccount();
  const check = useCheckCharges();
  const { notify } = useActions();
  const data = account.data;
  const last = data?.last_charge_check;

  return (
    <section className="tile" id="charges" aria-labelledby="charges-title">
      <div className="settings-head">
        <h2 id="charges-title">Charges</h2>
        <span className="flex-1" />
        <button
          type="button"
          className="btn"
          disabled={!connected || check.isPending}
          onClick={() =>
            check.mutate(broker, {
              onSuccess: (done) =>
                notify(
                  done.matches
                    ? `All ${done.samples.length} sample orders match the contract note`
                    : `Some of ${done.samples.length} sample orders differ from the contract note`,
                ),
              onError: (e) => notify(`Not checked: ${failed(e)}`),
            })
          }
        >
          {check.isPending ? "Checking…" : connected ? "Check now" : "Connect to check"}
        </button>
      </div>
      <div className="kv settings-kv">
        <span className="muted">Rates</span>
        <span>{data?.charges_source ?? "—"}</span>
        <span className="muted">Rates as of</span>
        <span>{data ? istDate(data.charges_as_of, { year: true }) : "—"}</span>
        <span className="muted">Last contract-note check</span>
        <span>
          {last ? (
            <>
              {istDate(last.checked_at, { time: true })} IST ·{" "}
              {last.differing ? (
                <span className="text-warn">
                  {last.differing} of {last.checked} differ
                </span>
              ) : (
                `${last.checked} orders match`
              )}
            </>
          ) : (
            "Not yet"
          )}
        </span>
      </div>
      <p className="note settings-note">
        Every paper fill pays these. The server checks them against the broker's contract note once
        a day; nothing is placed.
      </p>
    </section>
  );
}
