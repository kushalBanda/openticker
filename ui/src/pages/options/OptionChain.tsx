import { Command } from "cmdk";
import { ChevronDown, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router";
import {
  type Chain,
  type ChainQuote,
  useInstrumentSearch,
  useOptionChain,
  usePayoff,
} from "../../api/queries";
import { Dialog } from "../../components/Dialog";
import { Page } from "../../components/Page";
import { Segmented } from "../../components/Segmented";
import { StatCard } from "../../components/StatCard";
import { TableSkeleton } from "../../components/TableStates";
import {
  addPick,
  inTheMoney,
  type Leg,
  type Pick,
  putCallRatio,
  saveBasket,
  savedBasket,
  units,
} from "../../lib/basket";
import {
  change,
  dayMonth,
  direction,
  instrumentName,
  MISSING,
  price,
  qty,
  rupees,
} from "../../lib/format";
import type { Exchange, Side } from "../../lib/orders";
import type { InstrumentKey } from "../../stream/connection";
import { usePrice } from "../../stream/prices";
import { useLive } from "../../stream/StreamProvider";
import { Basket } from "./Basket";
import { type ByStrike, OiChart, PayoffChart, SmileChart } from "./charts";

// The underlyings with listed options OpenTicker knows by name (ADR 4);
// any stock with options can be searched for.
const INDICES: { symbol: string; exchange: Exchange }[] = [
  { symbol: "NIFTY 50", exchange: "NSE" },
  { symbol: "NIFTY BANK", exchange: "NSE" },
  { symbol: "NIFTY FIN SERVICE", exchange: "NSE" },
  { symbol: "NIFTY MID SELECT", exchange: "NSE" },
  { symbol: "NIFTY NEXT 50", exchange: "NSE" },
  { symbol: "SENSEX", exchange: "BSE" },
  { symbol: "BANKEX", exchange: "BSE" },
];
const LAST_KEY = "options.underlying";
const STRIKES = [10, 20, 30] as const;
const SHOWN_EXPIRIES = 4;

function lastUnderlying(): { symbol: string; exchange: Exchange } {
  try {
    const [exchange, symbol] = (localStorage.getItem(LAST_KEY) ?? "").split(":");
    if (exchange && symbol) return { exchange: exchange as Exchange, symbol };
  } catch {
    // storage blocked: the default
  }
  return { symbol: "NIFTY 50", exchange: "NSE" };
}

const lakh = (oi: number | null | undefined) => (oi == null ? MISSING : (oi / 1e5).toFixed(2));
const fixed = (v: number | null | undefined, digits: number) =>
  v == null ? MISSING : v.toFixed(digits);

/** The contract's pick from the chain: sell at the bid, buy at the ask. */
function pickOf(
  quote: { symbol: string; bid?: number | null; ask?: number | null },
  side: Side,
  kind: Leg["kind"],
  strike: number | null,
  expiry: string,
  lotSize: number,
  exchange: Exchange,
): Pick | null {
  const at = side === "SELL" ? quote.bid : quote.ask;
  if (at == null) return null;
  return { symbol: quote.symbol, exchange, side, price: at, lotSize, kind, strike, expiry };
}

function PickButtons({
  quote,
  name,
  make,
  onPick,
}: {
  quote: { bid?: number | null; ask?: number | null };
  name: string;
  make: (side: Side) => Pick | null;
  onPick: (pick: Pick) => void;
}) {
  const one = (side: Side) => {
    const at = side === "SELL" ? quote.bid : quote.ask;
    const pick = make(side);
    return (
      <button
        type="button"
        className="pick"
        data-side={side}
        disabled={pick === null}
        onClick={() => pick && onPick(pick)}
        aria-label={`${side === "SELL" ? "Sell" : "Buy"} ${name} at ${price(at)}`}
        title={side === "SELL" ? "Sell at bid" : "Buy at ask"}
      >
        {price(at)}
      </button>
    );
  };
  return (
    <span className="picks">
      {one("SELL")}
      {one("BUY")}
    </span>
  );
}

function UnderlyingDialog({
  open,
  onClose,
  onChoose,
}: {
  open: boolean;
  onClose: () => void;
  onChoose: (symbol: string, exchange: Exchange) => void;
}) {
  const [query, setQuery] = useState("");
  const [settled, setSettled] = useState("");
  useEffect(() => {
    const timer = setTimeout(() => setSettled(query), 120);
    return () => clearTimeout(timer);
  }, [query]);
  useEffect(() => {
    if (!open) setQuery("");
  }, [open]);
  const search = useInstrumentSearch(settled);
  const wanted = query.trim().toUpperCase();
  const indices = INDICES.filter((i) => i.symbol.includes(wanted));
  const stocks = wanted
    ? (search.data?.instruments ?? []).filter(
        (i) => i.instrument_type === "EQ" && (i.exchange === "NSE" || i.exchange === "BSE"),
      )
    : [];
  return (
    <Dialog open={open} onClose={onClose} title="Choose underlying" width={480}>
      <Command label="Search underlyings" shouldFilter={false} loop className="picker">
        <div className="palette-input picker-input">
          <Search aria-hidden />
          <Command.Input
            data-autofocus
            value={query}
            onValueChange={setQuery}
            placeholder="An index, or a stock: RELIANCE"
          />
        </div>
        <Command.List>
          {indices.length > 0 && (
            <Command.Group heading="Indices">
              {indices.map((i) => (
                <Command.Item
                  key={`${i.exchange}:${i.symbol}`}
                  value={`${i.exchange}:${i.symbol}`}
                  onSelect={() => onChoose(i.symbol, i.exchange)}
                >
                  <b>{i.symbol}</b>
                  <span className="muted">{i.exchange}</span>
                </Command.Item>
              ))}
            </Command.Group>
          )}
          {stocks.length > 0 && (
            <Command.Group heading="Stocks">
              {stocks.map((i) => (
                <Command.Item
                  key={`${i.exchange}:${i.symbol}`}
                  value={`${i.exchange}:${i.symbol}`}
                  onSelect={() => onChoose(i.symbol, i.exchange as Exchange)}
                >
                  <b>{i.symbol}</b>
                  <span className="muted">{i.exchange}</span>
                </Command.Item>
              ))}
            </Command.Group>
          )}
          {wanted && !search.isFetching && indices.length === 0 && stocks.length === 0 && (
            <Command.Empty>Nothing matches “{query.trim()}”.</Command.Empty>
          )}
        </Command.List>
      </Command>
    </Dialog>
  );
}

function ChainTable({
  chain,
  spot,
  exchange,
  onPick,
  basket,
}: {
  chain: Chain;
  spot: number;
  exchange: Exchange;
  onPick: (pick: Pick) => void;
  basket: Leg[];
}) {
  const lotSize = chain.lot_size ?? 1;
  const inBasket = new Map(basket.map((l) => [l.symbol, l]));
  const side = (quote: ChainQuote | null | undefined, kind: "CE" | "PE", strike: number) => {
    if (!quote) {
      return Array.from({ length: 5 }, (_, n) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: fixed empty cells
        <td key={n} className="missing">
          {MISSING}
        </td>
      ));
    }
    const { name } = instrumentName(quote.symbol, exchange, kind, chain.expiry, strike);
    const held = inBasket.get(quote.symbol);
    const make = (s: Side) => pickOf(quote, s, kind, strike, chain.expiry, lotSize, exchange);
    const cells = [
      <td key="oi">{lakh(quote.open_interest)}</td>,
      <td key="iv">{fixed(quote.implied_volatility, 1)}</td>,
      <td key="delta">{fixed(quote.delta, 2)}</td>,
      <td key="ltp" className="ltp">
        {price(quote.last_price)}
      </td>,
      <td key="book" className="book" data-held={held ? held.side : undefined}>
        <PickButtons quote={quote} name={name} make={make} onPick={onPick} />
      </td>,
    ];
    return kind === "CE" ? cells : cells.reverse();
  };
  // A server older than the page sends no futures: none, not a crash.
  const futures = chain.futures ?? [];
  return (
    <table className="chain" aria-label="Option chain">
      <thead>
        <tr className="chain-sides">
          <th colSpan={5} scope="colgroup">
            Calls
          </th>
          <th />
          <th colSpan={5} scope="colgroup">
            Puts
          </th>
        </tr>
        <tr>
          <th scope="col">OI (lakh)</th>
          <th scope="col">IV</th>
          <th scope="col">Delta</th>
          <th scope="col">LTP</th>
          <th scope="col">Bid · Ask</th>
          <th scope="col" className="strike">
            Strike
          </th>
          <th scope="col">Bid · Ask</th>
          <th scope="col">LTP</th>
          <th scope="col">Delta</th>
          <th scope="col">IV</th>
          <th scope="col">OI (lakh)</th>
        </tr>
      </thead>
      <tbody>
        {futures.length > 0 && (
          <tr className="futures-row">
            <td colSpan={11}>
              <span className="label">Futures</span>
              {futures.map((f) => {
                const { name } = instrumentName(f.symbol, exchange, "FUT", f.expiry);
                return (
                  <span key={f.symbol} className="future" data-testid="future">
                    <span className="tabular">
                      {name} {price(f.last_price)}
                    </span>
                    <PickButtons
                      quote={f}
                      name={name}
                      make={(s) => pickOf(f, s, "FUT", null, f.expiry, f.lot_size, exchange)}
                      onPick={onPick}
                    />
                  </span>
                );
              })}
            </td>
          </tr>
        )}
        {chain.rows.map((row) => {
          const atm = row.strike === chain.atm_strike;
          return (
            <tr
              key={row.strike}
              data-atm={atm || undefined}
              data-call-itm={inTheMoney("CE", row.strike, spot) || undefined}
              data-put-itm={inTheMoney("PE", row.strike, spot) || undefined}
            >
              {side(row.call, "CE", row.strike)}
              <td className="strike">{qty(row.strike)}</td>
              {side(row.put, "PE", row.strike)}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function PayoffCard({
  broker,
  legs,
  spot,
}: {
  broker: string | undefined;
  legs: Leg[];
  spot: number;
}) {
  const payoff = usePayoff(
    broker,
    legs.map((l) => ({
      symbol: l.symbol,
      exchange: l.exchange,
      side: l.side,
      quantity: units(l),
      price: l.price,
    })),
  );
  const data = legs.length ? payoff.data : undefined;
  return (
    <section className="tile payoff-tile" aria-labelledby="payoff-title">
      <div className="tile-head">
        <h2 id="payoff-title">Payoff</h2>
        <span className="flex-1" />
        <span className="note legend">
          <span className="key-expiry" /> at expiry <span className="key-today" /> today
        </span>
      </div>
      {legs.length === 0 ? (
        <div className="chart-note">
          Pick a bid to sell or an ask to buy. The basket's payoff shows here before you place it.
        </div>
      ) : payoff.isError ? (
        <div className="chart-note" role="alert">
          {payoff.error.message}
        </div>
      ) : !data ? (
        <div className="skeleton" style={{ width: "100%", height: 250 }} />
      ) : (
        <>
          <PayoffChart payoff={data} spot={spot || data.underlying_price} />
          <div className="kv payoff-figures" data-testid="payoff-figures">
            <span className="muted">Max profit</span>
            <span className="up" data-testid="max-profit">
              {data.max_profit === null ? "Unlimited" : rupees(data.max_profit, { sign: true })}
            </span>
            <span className="muted">Max loss</span>
            <span className="down" data-testid="max-loss">
              {data.max_loss === null ? "Unlimited" : rupees(data.max_loss, { sign: true })}
            </span>
            <span className="muted">Breakevens</span>
            <span data-testid="breakevens">
              {data.breakevens.length ? data.breakevens.map((b) => qty(b)).join(" · ") : "None"}
            </span>
            <span className="muted">Net delta</span>
            <span title="Rupees per point of the underlying, today">
              {data.net_delta === null ? MISSING : data.net_delta.toFixed(2)}
            </span>
          </div>
          <p className="note">
            Preview only. Today's curve uses Black-76 with each leg's IV from its last price.
          </p>
        </>
      )}
    </section>
  );
}

/**
 * The option chain (DESIGN.md Option chain, ADR 38): one expiry of an
 * underlying live, its bids and asks picked into a basket, the basket's payoff,
 * margin and charges shown before it is placed as paper orders, buys first.
 */
export function OptionChain() {
  const params = useParams();
  const navigate = useNavigate();
  const fallback = useMemo(lastUnderlying, []);
  const underlying = params.underlying ?? fallback.symbol;
  const exchange = ((params.exchange ?? fallback.exchange).toUpperCase() as Exchange) || "NSE";
  const key = `${exchange}:${underlying}`;
  const { status } = useLive();
  const broker = status?.broker;
  const [expiry, setExpiry] = useState<string | undefined>(undefined);
  const [strikes, setStrikes] = useState<number>(10);
  const [choosing, setChoosing] = useState(false);
  const [legs, setLegs] = useState<Leg[]>(() => savedBasket(key));

  useEffect(() => {
    setLegs(savedBasket(key));
    setExpiry(undefined);
    try {
      localStorage.setItem(LAST_KEY, key);
    } catch {
      // storage blocked: this visit only
    }
  }, [key]);
  useEffect(() => saveBasket(key, legs), [key, legs]);

  const chain = useOptionChain(broker, exchange, underlying, expiry, strikes);
  const tick = usePrice(key as InstrumentKey);
  const data = chain.data?.underlying === underlying ? chain.data : undefined;
  const spot = tick?.last_price ?? data?.underlying_price ?? 0;
  const atmRow = data?.rows.find((r) => r.strike === data.atm_strike);
  const atmIv = [atmRow?.call?.implied_volatility, atmRow?.put?.implied_volatility].filter(
    (v): v is number => v != null,
  );
  const pcr = data ? putCallRatio(data.rows) : null;
  const expiries = data?.available_expiries ?? [];
  const current = data?.expiry;
  const byStrike = (pick: (q: ChainQuote) => number | null): ByStrike[] =>
    (data?.rows ?? []).map((r) => ({
      strike: r.strike,
      call: r.call ? pick(r.call) : null,
      put: r.put ? pick(r.put) : null,
    }));
  const name = INDICES.some((i) => i.symbol === underlying)
    ? underlying
    : `${underlying} ${exchange === "NSE" ? "" : exchange}`.trim();

  const choose = (symbol: string, at: Exchange) => {
    setChoosing(false);
    navigate(`/options/${at}/${encodeURIComponent(symbol)}`);
  };
  const pick = (p: Pick) => setLegs((before) => addPick(before, p));
  const dte = data?.days_to_expiry;

  return (
    <Page title="Option chain">
      <div className="toolbar chain-toolbar">
        <button
          type="button"
          className="btn underlying-btn"
          data-variant="outline"
          onClick={() => setChoosing(true)}
          aria-label={`Underlying: ${name}. Change`}
        >
          {name}
          <ChevronDown size={15} aria-hidden />
        </button>
        {expiries.length > 0 && current && (
          <Segmented<string>
            label="Expiry"
            value={expiries.slice(0, SHOWN_EXPIRIES).includes(current) ? current : ""}
            onChange={setExpiry}
            segments={expiries
              .slice(0, SHOWN_EXPIRIES)
              .map((e) => ({ value: e, label: dayMonth(e) }))}
          />
        )}
        {expiries.length > SHOWN_EXPIRIES && (
          <select
            className="select"
            aria-label="Later expiries"
            value={expiries.slice(0, SHOWN_EXPIRIES).includes(current ?? "") ? "" : current}
            onChange={(e) => e.target.value && setExpiry(e.target.value)}
          >
            <option value="">More…</option>
            {expiries.slice(SHOWN_EXPIRIES).map((e) => (
              <option key={e} value={e}>
                {dayMonth(e)} {e.slice(0, 4)}
              </option>
            ))}
          </select>
        )}
        <span className="flex-1" />
        <Segmented<string>
          label="Strikes either side"
          value={String(strikes)}
          onChange={(v) => setStrikes(Number(v))}
          segments={STRIKES.map((n) => ({ value: String(n), label: `±${n}` }))}
        />
      </div>

      <UnderlyingDialog open={choosing} onClose={() => setChoosing(false)} onChoose={choose} />

      {chain.isError && !data ? (
        <div className="tile empty">
          <h2>No option chain for {name}</h2>
          <p className="note">{chain.error.message}</p>
        </div>
      ) : (
        <>
          <div className="stats chain-stats">
            <StatCard
              label="Spot"
              testId="spot"
              value={spot ? <span className="tabular">{price(spot)}</span> : MISSING}
              note={
                <span className={direction(tick?.change) ?? ""}>
                  {tick?.change != null ? change(tick.change, tick.change_pct) : "Live"}
                </span>
              }
            />
            <StatCard
              label="Forward"
              value={data ? price(data.forward_price) : MISSING}
              note="From put-call parity at the money"
            />
            <StatCard
              label="ATM"
              value={data ? qty(data.atm_strike) : MISSING}
              note={
                atmIv.length
                  ? `IV ${(atmIv.reduce((a, b) => a + b, 0) / atmIv.length).toFixed(1)}%`
                  : "No IV"
              }
            />
            <StatCard
              label="Days to expiry"
              value={dte == null ? MISSING : dte < 1 ? "<1" : Math.floor(dte)}
              note={current ? `${dayMonth(current)}, 15:30` : undefined}
            />
            <StatCard
              label="PCR (OI)"
              value={pcr === null ? MISSING : pcr.toFixed(2)}
              note={data?.lot_size ? `Lot ${qty(data.lot_size)}` : undefined}
            />
          </div>

          <section className="tile chain-tile" data-flush="true">
            {data ? (
              <ChainTable
                chain={data}
                spot={spot}
                exchange={data.exchange === "BSE" ? "BFO" : "NFO"}
                onPick={pick}
                basket={legs}
              />
            ) : (
              <TableSkeleton label="Loading the option chain" />
            )}
          </section>

          <div className="chain-charts">
            <PayoffCard broker={broker} legs={legs} spot={spot} />
            <section className="tile" aria-labelledby="smile-title">
              <div className="tile-head">
                <h2 id="smile-title">IV smile</h2>
                <span className="flex-1" />
                <span className="note legend">
                  <span className="key-calls" /> calls <span className="key-puts" /> puts
                </span>
              </div>
              <SmileChart
                rows={byStrike((q) => q.implied_volatility)}
                atm={data?.atm_strike ?? 0}
              />
            </section>
            <section className="tile" aria-labelledby="oi-title">
              <div className="tile-head">
                <h2 id="oi-title">OI by strike</h2>
                <span className="flex-1" />
                <span className="note legend">
                  <span className="key-calls" /> calls <span className="key-puts" /> puts
                </span>
              </div>
              <OiChart rows={byStrike((q) => q.open_interest)} atm={data?.atm_strike ?? 0} />
            </section>
          </div>
        </>
      )}

      {legs.length > 0 && (
        <Basket
          broker={broker}
          underlying={underlying}
          legs={legs}
          onChange={setLegs}
          marketOpen={status?.market_open ?? false}
        />
      )}
    </Page>
  );
}
