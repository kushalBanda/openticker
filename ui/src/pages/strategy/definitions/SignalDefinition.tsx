import { Fragment, useState } from "react";
import type { Schemas } from "../../../api/client";
import { useDisableAlertUrl, useRotateAlertUrl } from "../../../api/queries";
import { CopyLine } from "../../../components/CopyLine";
import { Dialog } from "../../../components/Dialog";
import { HoldButton } from "../../../components/HoldButton";
import {
  changePrompt,
  type Line,
  type SignalDefinition,
  signalLines,
} from "../../../lib/strategies";
import { useActions } from "../../../shell/actions";

type Signals = Schemas["StrategySignalsResult"];
type Webhook = Schemas["WebhookResult"];

export function DefinitionLines({ lines }: { lines: Line[] }) {
  return (
    <dl className="kv" style={{ marginTop: 12 }}>
      {lines.map((line) => (
        <Fragment key={line.label}>
          <dt className="muted">{line.label}</dt>
          <dd style={{ margin: 0 }}>{line.value}</dd>
        </Fragment>
      ))}
    </dl>
  );
}

/** The full URL to paste into TradingView or ChartInk: the server's public one, else this origin. */
function fullUrl(webhook: Webhook): string {
  return webhook.alert_url ?? `${window.location.origin}${webhook.alert_path}`;
}

function AlertUrl({
  id,
  signals,
  broker,
  locked,
}: {
  id: string;
  signals: Signals | undefined;
  broker: string | undefined;
  locked: boolean;
}) {
  const rotate = useRotateAlertUrl();
  const disable = useDisableAlertUrl();
  const { notify } = useActions();
  const [asking, setAsking] = useState(false);
  const [made, setMade] = useState<Webhook | null>(null);
  const [error, setError] = useState<string | null>(null);
  const webhook = signals?.webhook;
  const through = webhook?.broker ?? broker;

  const close = () => {
    setAsking(false);
    setMade(null);
    setError(null);
  };

  return (
    <>
      <h2 className="tile-title" style={{ marginTop: 20 }}>
        Alert URL
      </h2>
      {signals === undefined ? (
        <div className="skeleton" style={{ width: "100%", height: 40, marginTop: 10 }} />
      ) : webhook ? (
        <>
          <div style={{ marginTop: 10 }}>
            <div className="command-line">
              <span className="min-w-0 flex-1 truncate">
                {window.location.origin}/webhooks/strategies/••••••••
              </span>
            </div>
          </div>
          <p className="note" style={{ margin: "6px 0 12px" }}>
            Shown once when made. Rotate for a new one; the old one stops working.
            {webhook.allowed_ips.length > 0 && ` Only from ${webhook.allowed_ips.join(", ")}.`}
          </p>
        </>
      ) : (
        <p className="note" style={{ margin: "6px 0 12px" }}>
          No alert URL: alerts can't reach it. Make one and paste it into TradingView or ChartInk.
        </p>
      )}
      {signals !== undefined && (
        <div className="flex items-center gap-2">
          <button
            type="button"
            className="btn"
            data-variant={webhook ? undefined : "primary"}
            disabled={!through || locked}
            title={locked ? "Release the kill switch first" : undefined}
            onClick={() => setAsking(true)}
          >
            {webhook ? "Rotate URL" : "Make alert URL"}
          </button>
          {webhook && (
            <HoldButton
              label="Hold to disable URL"
              onConfirm={async () => {
                try {
                  await disable.mutateAsync(id);
                  notify("Alert URL disabled: alerts to it are refused.");
                } catch (e) {
                  notify(e instanceof Error ? e.message : String(e));
                }
              }}
            />
          )}
        </div>
      )}
      <Dialog
        open={asking}
        onClose={close}
        title={made ? "New alert URL" : webhook ? "Rotate the alert URL?" : "Make an alert URL?"}
        width={520}
      >
        {made ? (
          <>
            <CopyLine text={fullUrl(made)} label="Copy the alert URL" />
            <p className="note" style={{ margin: 0 }}>
              This is the only time it is shown: the token in it is the password. Paste it into your
              alert's webhook URL now.
              {!made.alert_url &&
                " It points at this computer; TradingView needs a public URL (set OPENTICKER_PUBLIC_URL to your tunnel)."}
            </p>
            <div className="flex">
              <span className="flex-1" />
              <button type="button" className="btn" data-variant="primary" onClick={close}>
                Done
              </button>
            </div>
          </>
        ) : (
          <>
            <p className="note" style={{ margin: 0 }}>
              {webhook
                ? "The current URL stops working at once; alerts still sent to it are refused. The new one is shown once."
                : "Alerts posted to it enter and exit this strategy's legs. It is shown once."}
            </p>
            {error && (
              <div className="error-line" role="alert">
                {error}
              </div>
            )}
            <div className="flex items-center gap-2">
              <span className="flex-1" />
              <button type="button" className="btn" data-variant="ghost" onClick={close}>
                Cancel
              </button>
              <button
                type="button"
                className="btn"
                data-variant="solid"
                disabled={rotate.isPending || !through}
                onClick={async () => {
                  setError(null);
                  try {
                    setMade(
                      await rotate.mutateAsync({
                        strategyId: id,
                        broker: through ?? "",
                        allowedIps: webhook?.allowed_ips ?? [],
                      }),
                    );
                  } catch (e) {
                    setError(e instanceof Error ? e.message : String(e));
                  }
                }}
              >
                {webhook ? "Rotate URL" : "Make URL"}
              </button>
            </div>
          </>
        )}
      </Dialog>
    </>
  );
}

/** A signal strategy's rules, and the URL its alerts arrive at (ADR 24). */
export function SignalDefinitionCard({
  definition,
  strategy,
  signals,
  broker,
  locked,
}: {
  definition: SignalDefinition;
  strategy: { name: string; strategy_id: string };
  signals: Signals | undefined;
  broker: string | undefined;
  locked: boolean;
}) {
  return (
    <div className="tile" data-testid="definition">
      <h2 className="tile-title">Definition</h2>
      <DefinitionLines lines={signalLines(definition)} />
      <div style={{ marginTop: 16 }}>
        <CopyLine text={changePrompt(strategy)} label="Copy the request for your agent" />
      </div>
      <p className="note" style={{ margin: "6px 0 0" }}>
        Edits happen through your agent. Copy this and tell it what to change.
      </p>
      <AlertUrl id={strategy.strategy_id} signals={signals} broker={broker} locked={locked} />
    </div>
  );
}
