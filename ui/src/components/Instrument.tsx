import { type InstrumentType, instrumentName } from "../lib/format";

/** An instrument as Kite writes it, with its exchange tag. */
export function Instrument({
  symbol,
  exchange,
  type,
  expiry,
  strike,
}: {
  symbol: string;
  exchange: string;
  type?: InstrumentType;
  expiry?: string | null;
  strike?: number | null;
}) {
  const { name, tag } = instrumentName(symbol, exchange, type, expiry, strike);
  return (
    <span className="instrument" title={`${exchange}:${symbol}`}>
      {name}
      {tag && <span className="ex-tag">{tag}</span>}
    </span>
  );
}
