import { direction, rupees } from "../../lib/format";
import type { DayFigure } from "../../lib/manager";

/** A day of the desk's, market apart from charges (ADR 42). */
export function Split({ figure }: { figure: DayFigure }) {
  const row = (label: string, value: number) => (
    <>
      <dt>{label}</dt>
      <dd className={direction(value)}>{rupees(value, { sign: true })}</dd>
    </>
  );
  return (
    <dl className="mgr-split">
      {row("Market, closed trades", figure.gross)}
      {row("Market, still open", figure.open ?? 0)}
      {row("Charges and taxes", -figure.charges)}
    </dl>
  );
}
