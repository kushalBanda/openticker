import { useMemo } from "react";
import { legPnl, type RunLeg, type Strategy } from "../../lib/strategies";
import type { InstrumentKey, Tick } from "../../stream/connection";
import { usePrices } from "../../stream/prices";

export interface LiveLeg {
  leg: RunLeg;
  key: InstrumentKey;
  tick: Tick | undefined;
  ltp: number | null;
  pnl: number | null;
}

const keyOf = (leg: RunLeg) => `${leg.exchange}:${leg.symbol}` as InstrumentKey;

/** Open runs' legs, each marked to its latest tick. */
export function useLiveLegs(legs: RunLeg[]): LiveLeg[] {
  const keys = useMemo(() => legs.map(keyOf), [legs]);
  const ticks = usePrices(keys);
  return legs.map((leg, i) => {
    const tick = ticks[i];
    const ltp = tick?.last_price ?? null;
    return { leg, key: keys[i] as InstrumentKey, tick, ltp, pnl: legPnl(leg, ltp) };
  });
}

/**
 * Today's net for each strategy: the server's realized less charges, plus its
 * open legs marked live. Null while an open leg has no price.
 */
export function useTodayPnl(strategies: Strategy[]): Map<string, number | null> {
  const legs = useMemo(
    () =>
      strategies.flatMap((s) =>
        (s.active_run?.legs ?? []).filter(
          (leg) => leg.status === "open" || leg.status === "closing",
        ),
      ),
    [strategies],
  );
  const live = useLiveLegs(legs);
  const open = new Map<string, number | null>();
  let i = 0;
  for (const strategy of strategies) {
    let sum: number | null = strategy.today_pnl;
    for (const leg of strategy.active_run?.legs ?? []) {
      if (leg.status !== "open" && leg.status !== "closing") continue;
      const marked = live[i++]?.pnl ?? null;
      // A closing leg's realized is already in today_pnl once it closes; while open it isn't.
      sum = sum === null || marked === null ? null : sum + marked;
    }
    open.set(strategy.strategy_id, sum);
  }
  return open;
}
