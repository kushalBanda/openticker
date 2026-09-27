import { Link } from "react-router";
import { type InstrumentType, instrumentName } from "../lib/format";

/** An instrument's page: /symbols/NFO/NIFTY27OCT26FUT. */
export const symbolPath = (exchange: string, symbol: string) =>
  `/symbols/${exchange}/${encodeURIComponent(symbol)}`;

/** An instrument as Kite writes it, with its exchange tag; a link to its page. */
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
    <Link to={symbolPath(exchange, symbol)} className="instrument" title={`${exchange}:${symbol}`}>
      {name}
      {tag && <span className="ex-tag">{tag}</span>}
    </Link>
  );
}
