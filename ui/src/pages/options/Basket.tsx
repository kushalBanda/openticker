import { Minus, Plus, X } from "lucide-react";
import { useState } from "react";
import type { Schemas } from "../../api/client";
import { useBasketCharges, useBasketMargin, usePlaceBasket } from "../../api/queries";
import { SideBadge } from "../../components/PlacedBy";
import { Segmented } from "../../components/Segmented";
import { basketTitle, type Leg, netPremium, units } from "../../lib/basket";
import { type InstrumentType, instrumentName, MISSING, qty, rupees } from "../../lib/format";
import { useActions } from "../../shell/actions";

type Product = "MIS" | "NRML";

/** Placed: filled at once or resting; the rest were refused. */
function summary(results: Schemas["PlaceOrderResult"][]): string {
  const count = (status: string) => results.filter((r) => r.status === status).length;
  const refused = results.filter((r) => r.status === "REJECTED");
  const placed = results.length - refused.length;
  const parts = [
    `${placed} paper order${placed === 1 ? "" : "s"} placed`,
    count("FILLED") ? `${count("FILLED")} filled` : "",
    count("PENDING") ? `${count("PENDING")} open` : "",
  ].filter(Boolean);
  const said = parts.length > 1 ? `${parts[0]}: ${parts.slice(1).join(", ")}` : parts[0];
  if (!refused.length) return `${said}.`;
  return `${said}. ${refused.length} refused: ${refused[0]?.reason ?? "no reason given"}`;
}

/**
 * The basket tray (DESIGN.md Option chain): each picked leg, changed in
 * place, and what the set costs before it's placed: premium, the broker's
 * margin with the hedge benefit, charges at the sandbox's rates. Placing sends
 * one basket, every buy before any sell (ADR 26).
 */
export function Basket({
  broker,
  underlying,
  legs,
  onChange,
  marketOpen,
}: {
  broker: string | undefined;
  underlying: string;
  legs: Leg[];
  onChange: (legs: Leg[]) => void;
  marketOpen: boolean;
}) {
  const [product, setProduct] = useState<Product>("NRML");
  const [refusals, setRefusals] = useState<Record<string, string>>({});
  const place = usePlaceBasket();
  const { notify } = useActions();
  const orders: Schemas["OrderInput"][] = legs.map((l) => ({
    symbol: l.symbol,
    exchange: l.exchange,
    side: l.side,
    quantity: units(l),
    product,
    order_type: "LIMIT",
    price: l.price,
  }));
  const margin = useBasketMargin(broker, orders);
  const charges = useBasketCharges(orders);
  const premium = netPremium(legs);
  const valid = legs.every((l) => l.price > 0 && l.lots > 0);
  const underlyingName = /^(.+?)\d{2}[A-Z]{3}\d{2}/.exec(legs[0]?.symbol ?? "")?.[1] ?? underlying;

  const change = (at: number, next: Partial<Leg>) =>
    onChange(legs.map((l, n) => (n === at ? { ...l, ...next } : l)));

  const submit = async () => {
    if (!broker) return;
    try {
      const result = await place.mutateAsync({ broker, orders });
      const refused: Record<string, string> = {};
      for (const r of result.orders) {
        if (r.status === "REJECTED") refused[`${r.symbol}:${r.side}`] = r.reason ?? "Refused";
      }
      setRefusals(refused);
      // Placed legs leave the tray; a refused one stays, with why.
      onChange(legs.filter((l) => refused[`${l.symbol}:${l.side}`] !== undefined));
      notify(summary(result.orders));
    } catch (error) {
      notify(error instanceof Error ? error.message : String(error));
    }
  };

  return (
    <section className="tray" aria-labelledby="basket-title" data-testid="basket">
      <div className="tray-head">
        <h2 id="basket-title">Basket</h2>
        <span className="note">
          {legs.length} leg{legs.length === 1 ? "" : "s"} · {basketTitle(underlyingName, legs)}
        </span>
        <span className="flex-1" />
        <Segmented<Product>
          label="Product"
          value={product}
          onChange={setProduct}
          segments={[
            { value: "NRML", label: "Overnight NRML" },
            { value: "MIS", label: "Intraday MIS" },
          ]}
        />
        <button
          type="button"
          className="btn"
          data-variant="ghost"
          data-size="sm"
          onClick={() => {
            setRefusals({});
            onChange([]);
          }}
        >
          Clear
        </button>
      </div>
      <table className="table" data-dense="true" aria-label="Basket">
        <thead>
          <tr>
            <th scope="col" data-align="left">
              Instrument
            </th>
            <th scope="col" data-align="left">
              Side
            </th>
            <th scope="col">Lots</th>
            <th scope="col">Qty.</th>
            <th scope="col">Price</th>
            <th scope="col" data-align="left">
              Type
            </th>
            <th scope="col">
              <span className="sr-only">Remove</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {legs.map((leg, n) => {
            const { name, tag } = instrumentName(
              leg.symbol,
              leg.exchange,
              leg.kind as InstrumentType,
              leg.expiry,
              leg.strike,
            );
            const refused = refusals[`${leg.symbol}:${leg.side}`];
            return (
              <tr key={leg.symbol} data-testid="basket-leg">
                <td data-align="left">
                  <b>{name}</b> {tag && <span className="ex-tag">{tag}</span>}
                  {refused && (
                    <div className="sub down" role="alert">
                      {refused}
                    </div>
                  )}
                </td>
                <td data-align="left">
                  <SideBadge side={leg.side} />
                </td>
                <td>
                  <span className="stepper">
                    <button
                      type="button"
                      aria-label={`One lot less of ${name}`}
                      disabled={leg.lots <= 1}
                      onClick={() => change(n, { lots: leg.lots - 1 })}
                    >
                      <Minus size={13} aria-hidden />
                    </button>
                    <span className="tabular">{leg.lots}</span>
                    <button
                      type="button"
                      aria-label={`One lot more of ${name}`}
                      onClick={() => change(n, { lots: leg.lots + 1 })}
                    >
                      <Plus size={13} aria-hidden />
                    </button>
                  </span>
                </td>
                <td className="tabular">{qty(units(leg))}</td>
                <td>
                  <input
                    className="input price-input"
                    type="number"
                    inputMode="decimal"
                    step="0.05"
                    min="0.05"
                    aria-label={`Price of ${name}`}
                    value={Number.isFinite(leg.price) ? leg.price : ""}
                    onChange={(e) => change(n, { price: e.target.valueAsNumber })}
                  />
                </td>
                <td data-align="left">Limit</td>
                <td>
                  <button
                    type="button"
                    className="btn"
                    data-variant="ghost"
                    data-size="sm"
                    aria-label={`Remove ${name}`}
                    onClick={() => onChange(legs.filter((_, k) => k !== n))}
                  >
                    <X size={14} aria-hidden />
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="tray-foot">
        <span className="note">
          Net premium{" "}
          <b className={`tabular ${premium >= 0 ? "up" : "down"}`} data-testid="net-premium">
            {rupees(Math.abs(premium))} {premium >= 0 ? "credit" : "debit"}
          </b>
        </span>
        <span className="note" title="The broker's margin for the set, as Zerodha would block it">
          Margin{" "}
          {margin.isError ? (
            <span>{MISSING}</span>
          ) : (
            <b className="tabular" data-testid="basket-margin">
              {rupees(margin.data?.total)}
            </b>
          )}
          {margin.data && margin.data.benefit > 0 && (
            <span className="badge" data-tone="up">
              hedge saves {rupees(margin.data.benefit, { decimals: 0 })}
            </span>
          )}
        </span>
        <span className="note">
          Charges (est.) <b className="tabular">{rupees(charges.data)}</b>
        </span>
        <span className="flex-1" />
        <span className="note">Buys go first</span>
        <button
          type="button"
          className="btn"
          data-variant="primary"
          disabled={!marketOpen || !valid || place.isPending || !broker}
          onClick={submit}
        >
          {marketOpen
            ? `Place ${legs.length} paper order${legs.length === 1 ? "" : "s"}`
            : "Market closed"}
        </button>
        {margin.isError && (
          <p className="note tray-error" role="alert">
            No margin from the broker: {margin.error.message}
          </p>
        )}
      </div>
    </section>
  );
}
