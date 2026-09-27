import { Command } from "cmdk";
import { ArrowDownRight, ArrowUpRight, Search } from "lucide-react";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router";
import { type Instrument, useInstrumentSearch } from "../api/queries";
import { direction, instrumentName, price, qty, signed } from "../lib/format";
import { duration, ease, spring } from "../lib/motion";
import type { OrderDraft, Side } from "../lib/orders";
import type { InstrumentKey } from "../stream/connection";
import { usePrices } from "../stream/prices";
import { PAGES, SETTINGS } from "./nav";

const keyOf = (i: Instrument) => `${i.exchange}:${i.symbol}` as InstrumentKey;
const nameOf = (i: Instrument) =>
  instrumentName(i.symbol, i.exchange, i.instrument_type, i.expiry, i.strike).name;

/** A new order for an instrument: one lot, intraday, a limit at the last price. */
export function draftFor(instrument: Instrument, side: Side): OrderDraft {
  return {
    symbol: instrument.symbol,
    exchange: instrument.exchange,
    side,
    quantity: instrument.lot_size,
    product: "MIS",
    orderType: "LIMIT",
  };
}

function useDebounced(value: string, ms: number): string {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);
  return settled;
}

/**
 * ⌘K: find an instrument and buy or sell it, or go to a page (DESIGN.md,
 * cmdk). Symbols come from the local instrument master, prices from the stream.
 */
export function CommandPalette({
  open,
  onClose,
  onOrder,
}: {
  open: boolean;
  onClose: () => void;
  onOrder: (draft: OrderDraft) => void;
}) {
  return createPortal(
    <AnimatePresence>{open && <Palette onClose={onClose} onOrder={onOrder} />}</AnimatePresence>,
    document.body,
  );
}

function Palette({
  onClose,
  onOrder,
}: {
  onClose: () => void;
  onOrder: (draft: OrderDraft) => void;
}) {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [highlighted, setHighlighted] = useState("");
  const [symbol, setSymbol] = useState("");
  const settled = useDebounced(query, 120);
  const search = useInstrumentSearch(settled);
  const found = (query.trim() ? search.data?.instruments : undefined) ?? [];
  const keys = useMemo(() => found.map(keyOf), [found]);
  const ticks = usePrices(keys);

  // The symbol the actions are for: the one last highlighted, else the first.
  const target = found.find((i) => `symbol ${keyOf(i)}` === symbol) ?? found[0];
  const wanted = query.trim().toLowerCase();
  const pages = [...PAGES, SETTINGS].filter(
    (page) => wanted === "" || page.label.toLowerCase().includes(wanted),
  );

  const order = (instrument: Instrument, side: Side) => {
    onClose();
    onOrder(draftFor(instrument, side));
  };

  return (
    <m.div
      className="scrim palette-scrim"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0, transition: { duration: duration.fast } }}
      onPointerDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <m.div
        className="palette"
        role="dialog"
        aria-modal="true"
        aria-label="Search"
        initial={{ opacity: 0, scale: 0.98, y: -6 }}
        animate={{ opacity: 1, scale: 1, y: 0, transition: spring.soft }}
        exit={{ opacity: 0, scale: 0.98, transition: { duration: duration.fast, ease: ease.in } }}
      >
        <Command
          label="Search instruments and pages"
          shouldFilter={false}
          loop
          value={highlighted}
          onValueChange={(value) => {
            setHighlighted(value);
            if (value.startsWith("symbol ")) setSymbol(value);
          }}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.preventDefault();
              onClose();
            }
          }}
        >
          <div className="palette-input">
            <Search aria-hidden />
            <Command.Input
              autoFocus
              value={query}
              onValueChange={setQuery}
              placeholder="Search RELIANCE, NIFTY 24800 CE, or a page"
            />
            <span className="kbd">esc</span>
          </div>
          <Command.List>
            {query.trim() && !search.isFetching && found.length === 0 && pages.length === 0 && (
              <Command.Empty>
                Nothing matches “{query.trim()}”. If it's new, sync instruments in Settings.
              </Command.Empty>
            )}
            {found.length > 0 && (
              <Command.Group heading="Symbols">
                {found.map((instrument, i) => {
                  const tick = ticks[i];
                  return (
                    <Command.Item
                      key={keyOf(instrument)}
                      value={`symbol ${keyOf(instrument)}`}
                      onSelect={() => order(instrument, "BUY")}
                    >
                      <b>{nameOf(instrument)}</b>
                      <span className="muted">
                        {instrument.exchange}
                        {instrument.lot_size > 1 && ` · lot ${qty(instrument.lot_size)}`}
                      </span>
                      <span className="flex-1" />
                      <span className="price">{tick ? price(tick.last_price) : ""}</span>
                      {tick?.change_pct != null && (
                        <span className={`price ${direction(tick.change_pct) ?? ""}`}>
                          {signed(tick.change_pct)}%
                        </span>
                      )}
                    </Command.Item>
                  );
                })}
              </Command.Group>
            )}
            {target && (
              <Command.Group heading="Actions">
                <Command.Item value="buy" onSelect={() => order(target, "BUY")}>
                  <ArrowUpRight aria-hidden />
                  Buy {nameOf(target)}…
                </Command.Item>
                <Command.Item value="sell" onSelect={() => order(target, "SELL")}>
                  <ArrowDownRight aria-hidden />
                  Sell {nameOf(target)}…
                </Command.Item>
              </Command.Group>
            )}
            {pages.length > 0 && (
              <Command.Group heading="Pages">
                {pages.map((page) => (
                  <Command.Item
                    key={page.path}
                    value={`page ${page.path}`}
                    onSelect={() => {
                      onClose();
                      navigate(page.path);
                    }}
                  >
                    <page.icon aria-hidden />
                    {page.label}
                  </Command.Item>
                ))}
              </Command.Group>
            )}
          </Command.List>
        </Command>
      </m.div>
    </m.div>
  );
}
