import { useState } from "react";
import { type ApiKey, useApiKeys, useCreateKey, useRevokeKey } from "../../api/queries";
import { CopyLine } from "../../components/CopyLine";
import { type Column, DataTable } from "../../components/DataTable";
import { HoldButton } from "../../components/HoldButton";
import { TableEmpty } from "../../components/TableStates";
import { istDate } from "../../lib/format";
import { useActions } from "../../shell/actions";

const failed = (error: unknown) => (error instanceof Error ? error.message : String(error));

function scopeOf(key: ApiKey): { text: string; tone?: string } {
  if (!key.managed) return { text: "Full" };
  return { text: key.scope.startsWith("script:") ? "Script" : "Review", tone: "outline" };
}

/**
 * REST keys (ADR 17). A new key is shown once, here; only its hash is kept.
 * A running script's or review job's key is OpenTicker's: it goes when the
 * run or job ends.
 */
export function KeysSection() {
  const keys = useApiKeys();
  const create = useCreateKey();
  const revoke = useRevokeKey();
  const { notify } = useActions();
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [created, setCreated] = useState<{ name: string; secret: string } | null>(null);

  const columns: Column<ApiKey>[] = [
    {
      key: "name",
      head: "Name",
      align: "left",
      cell: (k) => <span className="font-medium">{k.name}</span>,
      sub: (k) => <span className="code">{k.prefix}…</span>,
    },
    {
      key: "scope",
      head: "Scope",
      align: "left",
      cell: (k) => {
        const scope = scopeOf(k);
        return (
          <span className="badge" data-tone={scope.tone}>
            {scope.text}
          </span>
        );
      },
    },
    {
      key: "created",
      head: "Created",
      align: "left",
      cell: (k) => <span className="muted tabular">{istDate(k.created_at, { time: true })}</span>,
    },
    {
      key: "revoke",
      head: <span className="sr-only">Revoke</span>,
      cell: (k) =>
        k.managed ? (
          <span className="note">Managed by OpenTicker</span>
        ) : (
          <HoldButton
            size="sm"
            label="Hold to revoke"
            onConfirm={async () => {
              try {
                await revoke.mutateAsync(k.name);
                notify(`Key ${k.name} revoked. Anything using it now gets 401.`);
              } catch (e) {
                notify(`Not revoked: ${failed(e)}`);
              }
            }}
          />
        ),
    },
  ];

  const rows = keys.data?.keys ?? [];

  return (
    <section className="tile" data-flush="true" id="keys" aria-labelledby="keys-title">
      <div className="tile-head">
        <h2 id="keys-title">API keys</h2>
        <span className="flex-1" />
        {!adding && (
          <button
            type="button"
            className="btn"
            onClick={() => {
              setAdding(true);
              setCreated(null);
            }}
          >
            Create key
          </button>
        )}
      </div>
      {adding && (
        <form
          className="settings-row settings-pad"
          onSubmit={(event) => {
            event.preventDefault();
            create.mutate(name.trim(), {
              onSuccess: (done) => {
                setCreated({ name: done.key.name, secret: done.secret });
                setAdding(false);
                setName("");
              },
            });
          }}
        >
          <input
            className="input"
            aria-label="Key name"
            placeholder="Name, like tradingview-bridge"
            value={name}
            // biome-ignore lint/a11y/noAutofocus: the one field the button opened
            autoFocus
            onChange={(event) => setName(event.target.value)}
          />
          <button
            type="submit"
            className="btn"
            data-variant="primary"
            disabled={!name.trim() || create.isPending}
          >
            Create
          </button>
          <button
            type="button"
            className="btn"
            data-variant="ghost"
            onClick={() => {
              setAdding(false);
              create.reset();
            }}
          >
            Cancel
          </button>
        </form>
      )}
      {create.isError && (
        <div className="error-line settings-pad" role="alert">
          {create.error.message}
        </div>
      )}
      {created && (
        <div className="settings-pad settings-created" data-testid="new-key">
          <p className="note">
            Key <b>{created.name}</b> created. Copy it now: it is shown this once. Send it in the{" "}
            <code>X-API-Key</code> header.
          </p>
          <CopyLine text={created.secret} label="Copy the key" />
        </div>
      )}
      {keys.isError ? (
        <div className="error-line settings-pad" role="alert">
          {keys.error.message}
        </div>
      ) : rows.length === 0 && keys.isSuccess ? (
        <TableEmpty>
          No keys yet. The web app doesn't need one; REST clients and TradingView bridges do.
        </TableEmpty>
      ) : (
        <DataTable label="API keys" columns={columns} rows={rows} rowKey={(k) => k.name} />
      )}
    </section>
  );
}
