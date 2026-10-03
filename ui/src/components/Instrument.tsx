import { Link, useLocation, useNavigate } from "react-router";
import { type InstrumentType, instrumentName } from "../lib/format";
import { PAGES, SETTINGS } from "../shell/nav";

/** An instrument's page: /symbols/NFO/NIFTY27OCT26FUT. */
export const symbolPath = (exchange: string, symbol: string) =>
  `/symbols/${exchange}/${encodeURIComponent(symbol)}`;

/** Where an instrument's page was opened from: its "‹ Watchlist" link. */
export interface From {
  to: string;
  label: string;
}

/** The page at `pathname`, as a way back to it. */
export function fromPage(pathname: string, search = ""): From {
  const page = [...PAGES, SETTINGS].find((p) => p.path === pathname);
  const label = page
    ? page.label
    : pathname.startsWith("/strategies/")
      ? "Strategy"
      : pathname.startsWith("/symbols/")
        ? decodeURIComponent(pathname.split("/").at(-1) ?? "Back")
        : "Back";
  return { to: pathname + search, label };
}

/** Opens an instrument's page, remembering this one as the way back. */
export function useOpenSymbol(): (exchange: string, symbol: string) => void {
  const navigate = useNavigate();
  const location = useLocation();
  return (exchange, symbol) =>
    navigate(symbolPath(exchange, symbol), {
      state: { from: fromPage(location.pathname, location.search) },
    });
}

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
  const location = useLocation();
  const { name, tag } = instrumentName(symbol, exchange, type, expiry, strike);
  return (
    <Link
      to={symbolPath(exchange, symbol)}
      state={{ from: fromPage(location.pathname, location.search) }}
      className="instrument"
      title={`${exchange}:${symbol}`}
    >
      {name}
      {tag && <span className="ex-tag">{tag}</span>}
    </Link>
  );
}
