import { Command } from "cmdk";
import { Check, Ellipsis, Plus, Search, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  type Instrument as Found,
  type Quote,
  useCreateWatchlist,
  useDeleteWatchlist,
  useInstrumentSearch,
  useQuotes,
  useRenameWatchlist,
  useWatch,
  useWatchlists,
  type Watchlist,
  type WatchlistItem,
} from "../../api/queries";
import { CopyLine } from "../../components/CopyLine";
import { type Column, DataTable } from "../../components/DataTable";
import { Dialog } from "../../components/Dialog";
import { HoldButton } from "../../components/HoldButton";
import { Instrument, useOpenSymbol } from "../../components/Instrument";
import { LivePrice } from "../../components/LivePrice";
import { Page } from "../../components/Page";
import { Segmented } from "../../components/Segmented";
import { TableEmpty, TableSkeleton } from "../../components/TableStates";
import {
  change,
  direction,
  type InstrumentType,
  instrumentName,
  price,
  qty,
} from "../../lib/format";
import type { Exchange, Side } from "../../lib/orders";
import { type Moved, moved, pickList, savedListId, saveListId, step } from "../../lib/watchlists";
import { useActions } from "../../shell/actions";
import { useSideKeys } from "../../shell/keys";
import { typing } from "../../shell/Sidebar";
import type { InstrumentKey, Tick } from "../../stream/connection";
import { usePrices } from "../../stream/prices";
import { useLive } from "../../stream/StreamProvider";

interface Row {
  item: WatchlistItem;
  key: InstrumentKey;
  tick: Tick | undefined;
  quote: Quote | undefined;
  moved: Moved;
}

const keyOf = (i: { exchange: string; symbol: string }) =>
  `${i.exchange}:${i.symbol}` as InstrumentKey;

const ASK_AGENT = "Make a watchlist called Banks with HDFCBANK, ICICIBANK and SBIN";

/**
 * Named lists of instruments, live (DESIGN.md Tables; ADR 36): the last
 * price flashing on each tick, the change as Kite merges it, and the quote's
 * bid, ask, day's range and volume. B / S on a row opens a paper order.
 * Agents read and change the same lists; their changes show as they happen.
 */
export function WatchlistPage() {
  const { status } = useLive();
  const broker = status?.broker;
  const openSymbol = useOpenSymbol();
  const { order, notify } = useActions();
  const lists = useWatchlists();
  const watch = useWatch();
  const [wanted, setWanted] = useState(savedListId);
  const [selected, setSelected] = useState<string | null>(null);
  const [dialog, setDialog] = useState<"new" | "edit" | "add" | null>(null);

  const all = lists.data?.watchlists ?? [];
  const current = pickList(all, wanted);
  const items = current?.items ?? [];
  const refs = useMemo(
    () => items.map((i) => ({ symbol: i.symbol, exchange: i.exchange })),
    [items],
  );
  const quotes = useQuotes(broker, refs);
  const keys = useMemo(() => items.map(keyOf), [items]);
  const ticks = usePrices(keys);
  const byKey = useMemo(
    () => new Map((quotes.data?.quotes ?? []).map((q) => [keyOf(q), q])),
    [quotes.data],
  );
  const rows: Row[] = items.map((item, n) => {
    const key = keys[n] as InstrumentKey;
    const quote = byKey.get(key);
    return { item, key, tick: ticks[n], quote, moved: moved(ticks[n], quote) };
  });

  const choose = (id: string) => {
    setWanted(id);
    saveListId(id);
    setSelected(null);
  };

  const tradeable = (item: WatchlistItem) => item.instrument_type !== "INDEX";
  const open = (item: WatchlistItem, side: Side) =>
    order({
      symbol: item.symbol,
      exchange: item.exchange as Exchange,
      side,
      quantity: item.lot_size ?? 1,
      product: "MIS",
      orderType: "LIMIT",
    });
  const chosen = rows.find((row) => row.key === selected)?.item;
  useSideKeys((side) => {
    if (chosen && tradeable(chosen)) open(chosen, side);
  });
  useRowKeys(
    rows.map((r) => r.key),
    selected,
    setSelected,
    (key) => {
      const [exchange = "", symbol = ""] = key.split(/:(.*)/s);
      openSymbol(exchange, symbol);
    },
  );

  const remove = async (item: WatchlistItem) => {
    if (!current) return;
    try {
      await watch.mutateAsync({
        id: current.watchlist_id,
        instruments: [{ symbol: item.symbol, exchange: item.exchange }],
        add: false,
      });
      notify(`${nameOf(item)} removed from ${current.name}`);
    } catch (error) {
      notify(error instanceof Error ? error.message : String(error));
    }
  };

  const columns: Column<Row>[] = [
    {
      key: "instrument",
      head: "Instrument",
      align: "left",
      className: "wl-instrument",
      cell: (row) => (
        <Instrument
          symbol={row.item.symbol}
          exchange={row.item.exchange}
          type={(row.item.instrument_type ?? undefined) as InstrumentType | undefined}
          expiry={row.item.expiry}
          strike={row.item.strike}
        />
      ),
    },
    {
      key: "ltp",
      head: "LTP",
      cell: (row) => (
        <LivePrice value={row.moved.last} tick={row.tick} watching={status?.market_open ?? false} />
      ),
    },
    {
      key: "change",
      head: "Chg.",
      cell: (row) => (
        <span className={direction(row.moved.change) ?? "missing"}>
          {change(row.moved.change, row.moved.pct)}
        </span>
      ),
    },
    { key: "bid", head: "Bid", cell: (row) => figure(row.quote?.bid) },
    { key: "ask", head: "Ask", cell: (row) => figure(row.quote?.ask) },
    { key: "high", head: "High", cell: (row) => figure(row.quote?.high) },
    { key: "low", head: "Low", cell: (row) => figure(row.quote?.low) },
    {
      key: "volume",
      head: "Volume",
      cell: (row) => {
        const volume = row.quote?.volume;
        return volume ? qty(volume) : <span className="missing">—</span>;
      },
    },
  ];

  const loading = lists.isPending;
  return (
    <Page
      title="Watchlist"
      actions={
        current && (
          <>
            <button
              type="button"
              className="btn"
              data-variant="primary"
              onClick={() => setDialog("add")}
            >
              <Plus size={16} aria-hidden />
              Add instrument
            </button>
            <button
              type="button"
              className="btn icon"
              data-variant="ghost"
              aria-label={`Rename or delete ${current.name}`}
              onClick={() => setDialog("edit")}
            >
              <Ellipsis size={16} aria-hidden />
            </button>
          </>
        )
      }
    >
      {lists.isError ? (
        <div className="tile empty" role="alert">
          <h2>Watchlists didn't load</h2>
          <p className="note">{lists.error.message}</p>
          <button type="button" className="btn" onClick={() => lists.refetch()}>
            Try again
          </button>
        </div>
      ) : loading ? (
        <div className="tile" data-flush="true">
          <TableSkeleton label="Loading watchlists" rows={4} />
        </div>
      ) : !current ? (
        <div className="tile empty">
          <h2>No watchlists yet</h2>
          <p className="note">
            Keep the instruments you follow in named lists, priced live. Your agent can read and
            change them too.
          </p>
          <div className="empty-actions">
            <button
              type="button"
              className="btn"
              data-variant="primary"
              onClick={() => setDialog("new")}
            >
              New list
            </button>
          </div>
          <div className="empty-prompt">
            <CopyLine text={ASK_AGENT} label="Copy the request for your agent" />
          </div>
        </div>
      ) : (
        <>
          <div className="toolbar wl-tabs">
            <Segmented<string>
              label="Watchlists"
              value={current.watchlist_id}
              onChange={choose}
              segments={all.map((list) => ({
                value: list.watchlist_id,
                label: list.name,
                count: list.items.length,
              }))}
            />
            <button
              type="button"
              className="btn"
              data-variant="ghost"
              data-size="sm"
              onClick={() => setDialog("new")}
            >
              <Plus size={14} aria-hidden />
              New list
            </button>
          </div>
          <section className="tile" data-flush="true" aria-label={current.name}>
            {rows.length === 0 ? (
              <TableEmpty>
                {`Nothing on ${current.name} yet. Add an instrument, or ask your agent to.`}
              </TableEmpty>
            ) : (
              <DataTable
                label={current.name}
                columns={columns}
                rows={rows}
                rowKey={(row) => row.key}
                selected={selected ?? ""}
                onSelect={(key) => {
                  const row = rows.find((r) => r.key === key);
                  if (row) openSymbol(row.item.exchange, row.item.symbol);
                }}
                actions={(row) => (
                  <>
                    {tradeable(row.item) && (
                      <>
                        <button
                          type="button"
                          className="btn icon"
                          data-variant="buy"
                          data-size="sm"
                          aria-label={`Buy ${nameOf(row.item)}`}
                          onClick={() => open(row.item, "BUY")}
                        >
                          B
                        </button>
                        <button
                          type="button"
                          className="btn icon"
                          data-variant="sell"
                          data-size="sm"
                          aria-label={`Sell ${nameOf(row.item)}`}
                          onClick={() => open(row.item, "SELL")}
                        >
                          S
                        </button>
                      </>
                    )}
                    <button
                      type="button"
                      className="btn icon"
                      data-variant="ghost"
                      data-size="sm"
                      aria-label={`Remove ${nameOf(row.item)} from ${current.name}`}
                      onClick={() => remove(row.item)}
                    >
                      <X size={14} aria-hidden />
                    </button>
                  </>
                )}
              />
            )}
          </section>
          <p className="note" style={{ marginTop: 16 }}>
            Click a row to open the instrument. <span className="kbd">↑</span>{" "}
            <span className="kbd">↓</span> select one; <span className="kbd">B</span> /{" "}
            <span className="kbd">S</span> opens a paper order for it. Lists are saved on this
            machine, and your agent can read and change them too.
          </p>
        </>
      )}

      <NameDialog
        open={dialog === "new"}
        onClose={() => setDialog(null)}
        onMade={(made) => {
          choose(made.watchlist_id);
          notify(`Watchlist ${made.name} made`);
        }}
      />
      {current && (
        <>
          <EditDialog
            key={current.watchlist_id}
            open={dialog === "edit"}
            list={current}
            onClose={() => setDialog(null)}
            onDone={notify}
          />
          <AddDialog
            open={dialog === "add"}
            list={current}
            onClose={() => setDialog(null)}
            onDone={notify}
          />
        </>
      )}
    </Page>
  );
}

const figure = (value: number | null | undefined) =>
  value == null ? <span className="missing">—</span> : price(value);

const nameOf = (item: {
  symbol: string;
  exchange: string;
  instrument_type?: string | null;
  expiry?: string | null;
  strike?: number | null;
}) =>
  instrumentName(
    item.symbol,
    item.exchange,
    (item.instrument_type ?? undefined) as InstrumentType | undefined,
    item.expiry,
    item.strike,
  ).name;

/** ↑ and ↓ move the selected row; Enter opens it. */
function useRowKeys(
  keys: string[],
  selected: string | null,
  select: (key: string | null) => void,
  openRow: (key: string) => void,
) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey || typing(event.target)) return;
      if (document.querySelector('[role="dialog"]')) return;
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        select(step(keys, selected, event.key === "ArrowDown" ? 1 : -1));
      } else if (event.key === "Enter" && selected && keys.includes(selected)) {
        if (event.target instanceof HTMLElement && event.target.closest("a, button")) return;
        event.preventDefault();
        openRow(selected);
      } else if (event.key === "Escape") {
        select(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [keys, selected, select, openRow]);
}

function NameDialog({
  open,
  onClose,
  onMade,
}: {
  open: boolean;
  onClose: () => void;
  onMade: (list: Watchlist) => void;
}) {
  const create = useCreateWatchlist();
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setError(null);
    try {
      const made = await create.mutateAsync(name);
      setName("");
      onClose();
      onMade(made);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <Dialog open={open} onClose={onClose} title="New watchlist">
      <form
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <label className="field">
          <span className="label">Name</span>
          <input
            className="input"
            data-autofocus
            value={name}
            maxLength={40}
            placeholder="Banks"
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        {error && (
          <div className="error-line" role="alert">
            {error}
          </div>
        )}
        <div className="flex items-center gap-2">
          <span className="flex-1" />
          <button type="button" className="btn" data-variant="ghost" onClick={onClose}>
            Cancel
          </button>
          <button
            type="submit"
            className="btn"
            data-variant="primary"
            disabled={!name.trim() || create.isPending}
          >
            Make list
          </button>
        </div>
      </form>
    </Dialog>
  );
}

function EditDialog({
  open,
  list,
  onClose,
  onDone,
}: {
  open: boolean;
  list: Watchlist;
  onClose: () => void;
  onDone: (message: string) => void;
}) {
  const rename = useRenameWatchlist();
  const remove = useDeleteWatchlist();
  const [name, setName] = useState(list.name);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) setName(list.name);
  }, [open, list.name]);

  const submit = async () => {
    setError(null);
    try {
      await rename.mutateAsync({ id: list.watchlist_id, name });
      onClose();
      onDone(`Renamed ${name.trim()}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <Dialog open={open} onClose={onClose} title={list.name}>
      <form
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <label className="field">
          <span className="label">Name</span>
          <input
            className="input"
            data-autofocus
            value={name}
            maxLength={40}
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        {error && (
          <div className="error-line" role="alert">
            {error}
          </div>
        )}
        <div className="flex items-center gap-2">
          <HoldButton
            label="Hold to delete list"
            onConfirm={async () => {
              try {
                await remove.mutateAsync(list.watchlist_id);
                onClose();
                onDone(`Watchlist ${list.name} deleted`);
              } catch (e) {
                setError(e instanceof Error ? e.message : String(e));
              }
            }}
          />
          <span className="flex-1" />
          <button type="button" className="btn" data-variant="ghost" onClick={onClose}>
            Cancel
          </button>
          <button
            type="submit"
            className="btn"
            data-variant="primary"
            disabled={!name.trim() || name.trim() === list.name || rename.isPending}
          >
            Rename
          </button>
        </div>
      </form>
    </Dialog>
  );
}

/** Search the instrument list and add to this watchlist; stays open to add more. */
function AddDialog({
  open,
  list,
  onClose,
  onDone,
}: {
  open: boolean;
  list: Watchlist;
  onClose: () => void;
  onDone: (message: string) => void;
}) {
  const watch = useWatch();
  const [query, setQuery] = useState("");
  const [settled, setSettled] = useState("");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(query), 120);
    return () => clearTimeout(timer);
  }, [query]);
  useEffect(() => {
    if (!open) {
      setQuery("");
      setError(null);
    }
  }, [open]);
  const search = useInstrumentSearch(settled);
  const found = (query.trim() ? search.data?.instruments : undefined) ?? [];
  const held = new Set(list.items.map(keyOf));

  const add = async (instrument: Found) => {
    setError(null);
    if (held.has(keyOf(instrument))) return;
    try {
      await watch.mutateAsync({
        id: list.watchlist_id,
        instruments: [{ symbol: instrument.symbol, exchange: instrument.exchange }],
        add: true,
      });
      onDone(`${nameOf(instrumentOf(instrument))} added to ${list.name}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={`Add to ${list.name}`}
      aside={<span className="muted">{list.items.length} of 50</span>}
      width={520}
    >
      <Command label="Search instruments" shouldFilter={false} loop className="picker">
        <div className="palette-input picker-input">
          <Search aria-hidden />
          <Command.Input
            data-autofocus
            value={query}
            onValueChange={setQuery}
            placeholder="Search RELIANCE, NIFTY OCT FUT, NIFTY 24800 CE"
          />
        </div>
        <Command.List>
          {query.trim() && !search.isFetching && found.length === 0 && (
            <Command.Empty>
              Nothing matches “{query.trim()}”. If it's new, sync instruments in Settings.
            </Command.Empty>
          )}
          {found.map((instrument) => {
            const on = held.has(keyOf(instrument));
            return (
              <Command.Item
                key={keyOf(instrument)}
                value={keyOf(instrument)}
                onSelect={() => void add(instrument)}
                aria-disabled={on}
              >
                <b>{nameOf(instrumentOf(instrument))}</b>
                <span className="muted">{instrument.exchange}</span>
                <span className="flex-1" />
                {on ? (
                  <span className="muted inline-flex items-center gap-1">
                    <Check size={14} aria-hidden /> On {list.name}
                  </span>
                ) : (
                  <span className="muted">Add</span>
                )}
              </Command.Item>
            );
          })}
        </Command.List>
      </Command>
      {error && (
        <div className="error-line" role="alert">
          {error}
        </div>
      )}
      <div className="flex items-center gap-2">
        <span className="note">Enter adds the highlighted one.</span>
        <span className="flex-1" />
        <button type="button" className="btn" data-variant="ghost" onClick={onClose}>
          Done
        </button>
      </div>
    </Dialog>
  );
}

const instrumentOf = (found: Found) => ({
  symbol: found.symbol,
  exchange: found.exchange,
  instrument_type: found.instrument_type,
  expiry: found.expiry,
  strike: found.strike,
});
