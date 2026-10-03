import { useState } from "react";
import type { Holder, Position } from "../../api/queries";
import {
  useChargesPreview,
  useClosePosition,
  useCloseStrategyLegs,
  useQuote,
  useStopStrategy,
} from "../../api/queries";
import { Dialog } from "../../components/Dialog";
import { instrumentName, price, qty, rupees, sourceLabel } from "../../lib/format";

type Choice =
  | { kind: "all"; key: "all" }
  | { kind: "leg"; key: string; holder: Holder & { strategy_id: string } }
  | { kind: "stop"; key: string; holder: Holder & { strategy_id: string } };

function isStrategy(holder: Holder): holder is Holder & { strategy_id: string } {
  return holder.strategy_id !== null;
}

function strategyName(holder: Holder): string {
  return holder.name ?? "A deleted strategy";
}

function restLabel(holder: Holder): string {
  return holder.source === "you" ? "you" : sourceLabel(holder.source);
}

/** Long 150: 75 held by NIFTY futures trend (running), 75 placed by you. */
function Split({ position }: { position: Position }) {
  const side = position.quantity > 0 ? "Long" : "Short";
  return (
    <p className="note" style={{ margin: 0 }}>
      {position.shared && "Shared: the strategies' legs don't fit inside this position. "}
      {side} {qty(Math.abs(position.quantity))}
      {position.held_by.length > 0 && ": "}
      {position.held_by.map((holder, i) => (
        <span key={holder.strategy_id ?? "rest"}>
          {i > 0 && ", "}
          {qty(Math.abs(holder.quantity))}{" "}
          {isStrategy(holder) ? (
            <>
              held by <b>{strategyName(holder)}</b> (running)
            </>
          ) : (
            <>placed by {restLabel(holder)}</>
          )}
        </span>
      ))}
      .
    </p>
  );
}

function choicesFor(position: Position): Choice[] {
  const strategies = position.held_by.filter(isStrategy);
  return [
    ...strategies.map((holder) => ({
      kind: "leg" as const,
      key: `leg:${holder.strategy_id}`,
      holder,
    })),
    { kind: "all" as const, key: "all" as const },
    ...strategies.map((holder) => ({
      kind: "stop" as const,
      key: `stop:${holder.strategy_id}`,
      holder,
    })),
  ];
}

function Explain({ choice, position }: { choice: Choice; position: Position }) {
  const strategies = position.held_by.filter(isStrategy);
  const rest = position.held_by.find((holder) => !isStrategy(holder));
  const one = strategies.length === 1;
  switch (choice.kind) {
    case "leg":
      return (
        <>
          <b>
            Close {one ? "the strategy's" : `${strategyName(choice.holder)}'s`}{" "}
            {qty(Math.abs(choice.holder.quantity))}
          </b>
          <div className="note">The strategy records the exit and keeps running.</div>
        </>
      );
    case "all":
      return (
        <>
          <b>Close all {qty(Math.abs(position.quantity))}</b>
          <div className="note">
            One market order.
            {strategies.length > 0 && " Strategies keep running and find their legs already flat."}
          </div>
        </>
      );
    case "stop":
      return (
        <>
          <b>Stop {one ? "the strategy" : strategyName(choice.holder)}</b>
          <div className="note">
            Exits every leg it holds and stops it.
            {rest &&
              ` The ${qty(Math.abs(rest.quantity))} placed by ${restLabel(rest)} stays open.`}
          </div>
        </>
      );
  }
}

/**
 * Closing a position (ADR 35): the whole of it, or, when strategies hold
 * part, just a strategy's legs or the strategy itself. One market order at
 * the bid (selling) or the ask (buying back).
 */
export function CloseDialog({
  open,
  position,
  broker,
  marketOpen,
  onClose,
  onDone,
}: {
  open: boolean;
  position: Position;
  broker: string;
  marketOpen: boolean;
  onClose: () => void;
  onDone: (message: string) => void;
}) {
  const choices = choicesFor(position);
  const [picked, setPicked] = useState<string>(
    position.shared ? "all" : (choices[0]?.key ?? "all"),
  );
  const choice = choices.find((c) => c.key === picked) ?? { kind: "all", key: "all" };
  const [error, setError] = useState<string | null>(null);

  const side = position.quantity > 0 ? "SELL" : "BUY";
  const quantity = Math.abs(choice.kind === "all" ? position.quantity : choice.holder.quantity);
  const quote = useQuote(broker, position.exchange, position.symbol);
  const at = side === "SELL" ? quote.data?.bid : quote.data?.ask;
  const estimate = at ?? quote.data?.last_price ?? position.last_price;
  const charges = useChargesPreview(
    estimate
      ? {
          symbol: position.symbol,
          exchange: position.exchange,
          side,
          quantity,
          price: estimate,
          product: position.product,
        }
      : null,
  );

  const close = useClosePosition();
  const closeLegs = useCloseStrategyLegs();
  const stop = useStopStrategy();
  const busy = close.isPending || closeLegs.isPending || stop.isPending;
  const { name } = instrumentName(
    position.symbol,
    position.exchange,
    position.instrument_type,
    position.expiry,
    position.strike,
  );

  const submit = async () => {
    setError(null);
    try {
      if (choice.kind === "all") {
        const result = await close.mutateAsync({
          broker,
          symbol: position.symbol,
          exchange: position.exchange,
          product: position.product,
        });
        if (result.status !== "FILLED") {
          setError(result.reason ?? `Not closed: ${result.status}`);
          return;
        }
        onDone(
          `Closed ${name}: ${side === "SELL" ? "sold" : "bought"} ${qty(result.quantity)} at ${price(result.fill_price)}.`,
        );
      } else if (choice.kind === "leg") {
        await closeLegs.mutateAsync({
          strategyId: choice.holder.strategy_id,
          legIds: choice.holder.leg_ids,
        });
        onDone(`${strategyName(choice.holder)} is closing its ${qty(quantity)} ${name}.`);
      } else {
        await stop.mutateAsync(choice.holder.strategy_id);
        onDone(`${strategyName(choice.holder)} is stopping: it exits its legs within a second.`);
      }
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    }
  };

  const verb = side === "SELL" ? "Sell" : "Buy";
  const label = !marketOpen
    ? "Market closed"
    : choice.kind === "stop"
      ? "Stop strategy"
      : `${verb} ${qty(quantity)} at market`;

  return (
    <Dialog open={open} onClose={onClose} title={`Close ${name}`}>
      <Split position={position} />
      {choices.length > 1 && (
        <div className="flex flex-col gap-2" role="radiogroup" aria-label="What to close">
          {choices.map((c) => (
            <label key={c.key} className="choice">
              <input
                type="radio"
                name="close"
                checked={c.key === picked}
                onChange={() => setPicked(c.key)}
              />
              <div>
                <Explain choice={c} position={position} />
              </div>
            </label>
          ))}
        </div>
      )}
      <div className="kv">
        <span className="muted">Estimated at {side === "SELL" ? "bid" : "ask"}</span>
        <span>{price(estimate)}</span>
        <span className="muted">Charges (est.)</span>
        <span>{charges.data ? rupees(charges.data.total) : "—"}</span>
      </div>
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
          type="button"
          className="btn"
          data-variant={choice.kind === "stop" ? "solid" : side === "SELL" ? "sell" : "buy"}
          disabled={!marketOpen || busy}
          onClick={submit}
        >
          {busy ? "Closing…" : label}
        </button>
      </div>
    </Dialog>
  );
}
