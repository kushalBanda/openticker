import { useEffect, useState } from "react";
import { useSearchParams } from "react-router";
import {
  useBrokerLogin,
  useBrokerSession,
  useConnectBroker,
  useDisconnectBroker,
  useInstrumentStatus,
  useSyncInstruments,
} from "../../api/queries";
import { CopyLine } from "../../components/CopyLine";
import { istDate, qty } from "../../lib/format";
import { useActions } from "../../shell/actions";

export const brokerTitle = (broker: string) =>
  broker === "zerodha" ? "Zerodha" : broker.charAt(0).toUpperCase() + broker.slice(1);
const LOGIN_PAGE: Record<string, string> = { zerodha: "Kite" };
const EXCHANGES = ["NSE", "BSE", "NFO", "BFO", "MCX"];

const failed = (error: unknown) => (error instanceof Error ? error.message : String(error));

/**
 * Log in to the broker (ADR 33): its login page comes back to this server's
 * callback, which stores the session and returns here with `?connected=`.
 * Pasting the request token is the way when the redirect goes elsewhere.
 */
export function BrokerSection({ broker }: { broker: string }) {
  const session = useBrokerSession(broker);
  const login = useBrokerLogin();
  const connect = useConnectBroker();
  const disconnect = useDisconnectBroker();
  const { notify } = useActions();
  const [params, setParams] = useSearchParams();
  const [token, setToken] = useState("");
  const title = brokerTitle(broker);
  const page = LOGIN_PAGE[broker] ?? title;

  // Back from the broker's login page: say how it went, once.
  useEffect(() => {
    const connected = params.get("connected");
    const error = params.get("connect_error");
    if (connected === null && error === null) return;
    notify(connected ? `${brokerTitle(connected)} connected` : `Not connected: ${error}`);
    setParams({}, { replace: true });
  }, [params, setParams, notify]);

  const data = session.data;
  const expired = data?.stored && !data.connected;
  const badge = !data
    ? null
    : data.connected
      ? { tone: "accent", text: "Connected" }
      : expired
        ? { tone: "warn", text: "Session expired" }
        : { tone: undefined, text: "Not connected" };

  return (
    <section className="tile" id="broker" aria-labelledby="broker-title">
      <div className="settings-head">
        <h2 id="broker-title">{title}</h2>
        {badge && (
          <span className="badge" data-tone={badge.tone}>
            {badge.text}
          </span>
        )}
        <span className="flex-1" />
        <button
          type="button"
          className="btn"
          data-variant={data?.connected ? undefined : "primary"}
          disabled={!data?.configured || login.isPending}
          onClick={() => login.mutate(broker, { onError: (e) => notify(failed(e)) })}
        >
          {data && !data.configured
            ? `${title} app keys not set`
            : data?.connected
              ? `Log in to ${page} again`
              : `Log in to ${page}`}
        </button>
      </div>
      {session.isError && (
        <div className="error-line" role="alert">
          {session.error.message}
        </div>
      )}
      {data && (
        <div className="kv settings-kv">
          <span className="muted">Last login</span>
          <span>
            {data.connected_at ? `${istDate(data.connected_at, { time: true })} IST` : "—"}
          </span>
          <span className="muted">{expired ? "Expired" : "Session ends"}</span>
          <span>
            {data.expires_at ? `${istDate(data.expires_at, { time: true })} IST` : "—"}
            {broker === "zerodha" && data.stored && (
              <span className="muted"> · Kite logs everyone out daily</span>
            )}
          </span>
          <span className="muted">Redirect URL for your {page} app</span>
          <CopyLine text={data.redirect_url} label="Copy the redirect URL" />
        </div>
      )}
      {!data?.configured && data && (
        <p className="note settings-note">
          Set <code>KITE_API_KEY</code> and <code>KITE_API_SECRET</code> in <code>.env</code>, then
          restart <code>openticker-serve</code>.
        </p>
      )}
      <details className="settings-details">
        <summary className="note">Redirect not working? Paste the request token instead</summary>
        <form
          className="settings-row"
          onSubmit={(event) => {
            event.preventDefault();
            connect.mutate(
              { broker, request_token: token.trim() },
              {
                onSuccess: () => {
                  setToken("");
                  notify(`${title} connected`);
                },
                onError: (e) => notify(`Not connected: ${failed(e)}`),
              },
            );
          }}
        >
          <input
            className="input"
            aria-label="Request token"
            placeholder="request_token from the URL after login"
            value={token}
            onChange={(event) => setToken(event.target.value)}
          />
          <button type="submit" className="btn" disabled={!token.trim() || connect.isPending}>
            Connect
          </button>
        </form>
      </details>
      {data?.stored && (
        <div className="settings-row">
          <span className="flex-1" />
          <button
            type="button"
            className="btn"
            data-variant="ghost"
            disabled={disconnect.isPending}
            onClick={() =>
              disconnect.mutate(broker, {
                onSuccess: () => notify(`${title} disconnected. Live prices stopped.`),
                onError: (e) => notify(failed(e)),
              })
            }
          >
            Disconnect
          </button>
        </div>
      )}
    </section>
  );
}

export function InstrumentsSection({ broker, connected }: { broker: string; connected: boolean }) {
  const status = useInstrumentStatus();
  const sync = useSyncInstruments();
  const { notify } = useActions();
  const counts = status.data?.counts ?? {};
  const shown = EXCHANGES.filter((exchange) => counts[exchange] !== undefined);

  return (
    <section className="tile" id="instruments" aria-labelledby="instruments-title">
      <div className="settings-head">
        <h2 id="instruments-title">Instruments</h2>
        <span className="flex-1" />
        <button
          type="button"
          className="btn"
          disabled={!connected || sync.isPending}
          onClick={() =>
            sync.mutate(broker, {
              onSuccess: (done) => notify(`${qty(done.instrument_count)} instruments synced`),
              onError: (e) => notify(`Sync failed: ${failed(e)}`),
            })
          }
        >
          {sync.isPending ? "Syncing…" : connected ? "Sync now" : "Connect to sync"}
        </button>
      </div>
      <div className="kv settings-kv">
        <span className="muted">Last sync</span>
        <span>
          {status.data?.synced_at
            ? `${istDate(status.data.synced_at, { time: true })} IST`
            : "Never"}
        </span>
        <span className="muted">{shown.length ? shown.join(" · ") : "Contracts"}</span>
        <span className="tabular">
          {shown.length ? shown.map((exchange) => qty(counts[exchange])).join(" · ") : "None yet"}
        </span>
      </div>
      <p className="note settings-note">Contracts change with every expiry: sync once a day.</p>
    </section>
  );
}
