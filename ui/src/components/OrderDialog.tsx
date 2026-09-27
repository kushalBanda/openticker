import { useEffect, useId, useMemo, useRef, useState } from "react";
import {
  useChargesPreview,
  useListings,
  useModifyOrder,
  usePaperMargin,
  usePlaceOrder,
  useQuote,
} from "../api/queries";
import { instrumentName, price, qty, rupees } from "../lib/format";
import {
  isDerivative,
  needsPrice,
  needsTrigger,
  ORDER_TYPES,
  type OrderDraft,
  type OrderType,
  type Product,
  problems,
  productsFor,
  type Side,
} from "../lib/orders";
import type { InstrumentKey } from "../stream/connection";
import { usePrices } from "../stream/prices";
import { Dialog } from "./Dialog";
import { Segmented } from "./Segmented";

const number = (text: string): number | undefined => {
  const value = Number(text.replaceAll(",", ""));
  return text.trim() === "" || !Number.isFinite(value) ? undefined : value;
};
const text = (value: number | undefined) => (value === undefined ? "" : String(value));

function Field({
  label,
  value,
  onChange,
  disabled,
  error,
  step,
  autoFocus,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  error?: string;
  step?: number;
  autoFocus?: boolean;
}) {
  const id = useId();
  return (
    <div className="field">
      <label className="label" htmlFor={id}>
        {label}
      </label>
      <input
        id={id}
        className="input"
        inputMode="decimal"
        type="number"
        min={0}
        step={step}
        value={disabled ? "" : value}
        placeholder={disabled ? "—" : undefined}
        disabled={disabled}
        aria-invalid={error !== undefined}
        aria-describedby={error ? `${id}-error` : undefined}
        data-autofocus={autoFocus || undefined}
        onChange={(event) => onChange(event.target.value)}
      />
      {error && (
        <span id={`${id}-error`} className="field-error">
          {error}
        </span>
      )}
    </div>
  );
}

/**
 * Kite's order window, drawn Apple's way (DESIGN.md Order Dialog): the side
 * tints the head; NSE / BSE with their live prices; product; Qty., Price and
 * Trigger price; order type. The foot says what the paper account would
 * block and pay. With `orderId`, it changes that resting order instead:
 * quantity, price and trigger only.
 */
export function OrderDialog({
  open,
  draft,
  orderId,
  broker,
  marketOpen,
  onClose,
  onDone,
}: {
  open: boolean;
  draft: OrderDraft;
  orderId?: string;
  broker: string;
  marketOpen: boolean;
  onClose: () => void;
  onDone: (message: string) => void;
}) {
  const modifying = orderId !== undefined;
  const [side, setSide] = useState<Side>(draft.side);
  const [exchange, setExchange] = useState(draft.exchange);
  const [product, setProduct] = useState<Product>(draft.product);
  const [orderType, setOrderType] = useState<OrderType>(draft.orderType);
  const [quantity, setQuantity] = useState(text(draft.quantity));
  const [limit, setLimit] = useState(text(draft.price));
  const [trigger, setTrigger] = useState(text(draft.triggerPrice));
  const [tried, setTried] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const listings = useListings(draft.symbol);
  // NSE before BSE, as Kite lists them.
  const found = useMemo(
    () => [...(listings.data ?? [])].sort((a, b) => b.exchange.localeCompare(a.exchange)),
    [listings.data],
  );
  const contract = found.find((listing) => listing.exchange === exchange);
  const keys = useMemo(
    () => found.map((listing) => `${listing.exchange}:${listing.symbol}` as InstrumentKey),
    [found],
  );
  const ticks = usePrices(keys);
  const ltpOf = (at: string) => ticks[found.findIndex((listing) => listing.exchange === at)];
  const ltp = ltpOf(exchange)?.last_price;
  const quote = useQuote(broker, exchange, draft.symbol);

  // A limit starts at the last price on the tick grid, once; clearing it
  // later leaves it clear.
  const prefilled = useRef(limit !== "");
  const tick = contract?.tick_size;
  useEffect(() => {
    if (prefilled.current || ltp === undefined || !tick || !needsPrice(orderType)) return;
    prefilled.current = true;
    setLimit((Math.round(ltp / tick) * tick).toFixed(2));
  }, [ltp, tick, orderType]);

  const current: OrderDraft = {
    symbol: draft.symbol,
    exchange,
    side,
    product,
    orderType,
    quantity: number(quantity) ?? 0,
    price: needsPrice(orderType) ? number(limit) : undefined,
    triggerPrice: needsTrigger(orderType) ? number(trigger) : undefined,
  };
  const wrong = problems(current, contract);
  const fine = Object.keys(wrong).length === 0;

  // What it would fill at: the limit, the trigger (SL-M), or the book (market).
  const book = side === "BUY" ? quote.data?.ask : quote.data?.bid;
  const at =
    current.price ??
    (orderType === "SL-M" ? current.triggerPrice : undefined) ??
    book ??
    quote.data?.last_price ??
    ltp;
  const valued = fine && at !== undefined && at > 0;
  const margin = usePaperMargin(valued ? { broker, ...pick(current), price: at } : null);
  const charges = useChargesPreview(valued ? { ...pick(current), price: at } : null);

  const place = usePlaceOrder();
  const modify = useModifyOrder();
  const busy = place.isPending || modify.isPending;

  const name = contract
    ? instrumentName(
        draft.symbol,
        exchange,
        contract.instrument_type,
        contract.expiry,
        contract.strike,
      ).name
    : draft.symbol;
  const verb = side === "BUY" ? "Buy" : "Sell";
  const tone = side === "BUY" ? "up" : "down";

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setTried(true);
    setError(null);
    if (!fine || !marketOpen) return;
    try {
      if (modifying) {
        const result = await modify.mutateAsync({
          orderId,
          broker,
          quantity: current.quantity,
          price: current.price ?? null,
          trigger_price: current.triggerPrice ?? null,
        });
        if (result.status !== "PENDING") {
          setError(result.reason ?? `Not changed: the order is ${result.status.toLowerCase()}.`);
          return;
        }
        onDone(`Modified: ${describe(current, name)}.`);
        return;
      }
      const result = await place.mutateAsync({
        broker,
        symbol: current.symbol,
        exchange: current.exchange,
        side: current.side,
        quantity: current.quantity,
        product: current.product,
        order_type: current.orderType,
        price: current.price ?? null,
        trigger_price: current.triggerPrice ?? null,
      });
      if (result.status === "FILLED") {
        onDone(
          `${side === "BUY" ? "Bought" : "Sold"} ${qty(result.quantity)} ${name} at ${price(result.fill_price)}.`,
        );
      } else if (result.status === "PENDING") {
        onDone(`${describe(current, name)} is ${needsTrigger(orderType) ? "waiting" : "open"}.`);
      } else {
        setError(result.reason ?? `Not placed: ${result.status.toLowerCase()}.`);
      }
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    }
  };

  const show = (field: keyof typeof wrong, value: string) =>
    tried || value !== "" ? wrong[field] : undefined;

  return (
    <Dialog
      open={open}
      onClose={onClose}
      width={520}
      tone={tone}
      title={
        <>
          {modifying ? `Modify ${verb.toLowerCase()}` : verb} {name}{" "}
          <span className="muted" style={{ fontWeight: 500 }}>
            × {qty(current.quantity)} Qty.
          </span>
        </>
      }
      aside={
        !modifying && (
          <Segmented<Side>
            label="Buy or sell"
            side={side}
            value={side}
            onChange={setSide}
            segments={[
              { value: "BUY", label: "Buy" },
              { value: "SELL", label: "Sell" },
            ]}
          />
        )
      }
      head={
        <div className="radios" style={{ marginTop: 8 }}>
          {found.length > 1 && !modifying ? (
            <fieldset className="radios" aria-label="Exchange">
              {found.map((listing) => (
                <label key={listing.exchange}>
                  <input
                    type="radio"
                    name="exchange"
                    checked={listing.exchange === exchange}
                    onChange={() => setExchange(listing.exchange)}
                  />
                  {listing.exchange}{" "}
                  <span className="muted">{rupees(ltpOf(listing.exchange)?.last_price)}</span>
                </label>
              ))}
            </fieldset>
          ) : (
            <span className="muted">
              {exchange} {rupees(ltp)}
              {contract && isDerivative(contract) && ` · lot ${qty(contract.lot_size)}`}
            </span>
          )}
        </div>
      }
    >
      <form onSubmit={submit} noValidate>
        <div className="dialog-body">
          <fieldset className="radios" aria-label="Product" disabled={modifying}>
            {(contract ? productsFor(contract) : []).map((choice) => (
              <label key={choice.value}>
                <input
                  type="radio"
                  name="product"
                  checked={choice.value === product}
                  onChange={() => setProduct(choice.value)}
                />
                {choice.label} <span className="muted">{choice.value}</span>
              </label>
            ))}
          </fieldset>
          <div className="fields">
            <Field
              label="Qty."
              value={quantity}
              onChange={setQuantity}
              step={contract?.lot_size}
              error={show("quantity", quantity)}
              autoFocus={!needsPrice(orderType)}
            />
            <Field
              label="Price"
              value={limit}
              onChange={setLimit}
              disabled={!needsPrice(orderType)}
              step={contract?.tick_size}
              error={needsPrice(orderType) ? show("price", limit) : undefined}
              autoFocus={needsPrice(orderType)}
            />
            <Field
              label="Trigger price"
              value={trigger}
              onChange={setTrigger}
              disabled={!needsTrigger(orderType)}
              step={contract?.tick_size}
              error={needsTrigger(orderType) ? show("triggerPrice", trigger) : undefined}
            />
          </div>
          {modifying ? (
            <span className="note">
              {ORDER_TYPES.find((type) => type.value === orderType)?.label} order, {product}. Cancel
              it and place a new one to change anything else.
            </span>
          ) : (
            <div>
              <Segmented<OrderType>
                label="Order type"
                value={orderType}
                onChange={setOrderType}
                segments={ORDER_TYPES}
              />
            </div>
          )}
          {margin.data && !margin.data.fits && (
            <div className="error-line" role="alert">
              Not enough funds: needs {rupees(margin.data.required)},{" "}
              {rupees(margin.data.available)} available. Lower the quantity or close something
              first.
            </div>
          )}
          {error && (
            <div className="error-line" role="alert">
              {error}
            </div>
          )}
          {!marketOpen && (
            <div className="note-line" role="status">
              The market is closed. Orders can be placed from 09:15 IST on a trading day.
            </div>
          )}
        </div>
        <div className="dialog-foot">
          <dl className="order-cost" data-testid="order-cost">
            <div>
              <dt>Margin</dt>
              <dd>{margin.data ? rupees(margin.data.required) : "—"}</dd>
            </div>
            <div>
              <dt>Charges (est.)</dt>
              <dd>{charges.data ? rupees(charges.data.total) : "—"}</dd>
            </div>
            <div>
              <dt>Available</dt>
              <dd>{margin.data ? rupees(margin.data.available) : "—"}</dd>
            </div>
          </dl>
          <span className="flex-1" />
          <div className="dialog-actions">
            <button
              type="submit"
              className="btn"
              data-variant={side === "BUY" ? "buy" : "sell"}
              disabled={!marketOpen || busy}
            >
              {busy ? "Sending…" : modifying ? "Modify" : verb}
            </button>
            <button type="button" className="btn" data-variant="ghost" onClick={onClose}>
              Cancel
            </button>
          </div>
        </div>
      </form>
    </Dialog>
  );
}

function pick(draft: OrderDraft) {
  return {
    symbol: draft.symbol,
    exchange: draft.exchange,
    side: draft.side,
    quantity: draft.quantity,
    product: draft.product,
  };
}

/** Buy 10 RELIANCE at 2,905.00; Sell 10 RELIANCE, trigger 2,915.00 */
export function describe(draft: OrderDraft, name: string): string {
  const verb = draft.side === "BUY" ? "Buy" : "Sell";
  let said = `${verb} ${qty(draft.quantity)} ${name}`;
  if (draft.price !== undefined) said += ` at ${price(draft.price)}`;
  if (draft.triggerPrice !== undefined) said += `, trigger ${price(draft.triggerPrice)}`;
  return said;
}
