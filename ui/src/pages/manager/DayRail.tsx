import type { CSSProperties } from "react";
import { effortLabel } from "../../lib/agents";
import { RAIL, type RailLook, railPct } from "../../lib/manager";

type Vars = CSSProperties & Record<`--${string}`, string | number>;

const money = (usd: number | null) => (usd == null ? null : `$${usd.toFixed(2)}`);

/**
 * The session as a rail (ADR 42): each of a day's looks where it happened,
 * filled for a decisive look, a ring for a check-in, and dashed before it
 * was on. The watched stretch draws in once; not under reduced motion.
 */
export function DayRail({
  looks,
  offUntil,
  name,
  label = "Today's looks on the session",
  empty = "No looks yet today",
}: {
  looks: RailLook[];
  offUntil: number | null;
  name: (model: string) => string;
  label?: string;
  empty?: string;
}) {
  const from = offUntil ?? looks[0]?.pct ?? null;
  return (
    <figure className="mgr-run-day" aria-label={label}>
      <div className="mgr-run-rail">
        {offUntil != null && (
          <span className="mgr-run-off" style={{ "--to": `${offUntil}%` } as Vars} />
        )}
        {from != null && (
          <span className="mgr-run-track" style={{ "--from": `${from}%` } as Vars} />
        )}
        <span className="mgr-run-tick" style={{ "--at": `${railPct(RAIL.open)}%` } as Vars} />
        <span className="mgr-run-tick" style={{ "--at": `${railPct(RAIL.close)}%` } as Vars} />
        {looks.map((look, i) => {
          const used = [
            look.model ? name(look.model) : null,
            look.effort ? effortLabel(look.effort) : null,
            money(look.cost),
          ].filter(Boolean);
          return (
            <button
              key={look.id}
              type="button"
              className="mgr-run-look"
              data-tier={look.tier}
              // The tip opens toward the middle, so one near either end stays in the tile.
              data-side={look.pct < 50 ? "start" : "end"}
              style={{ "--at": `${look.pct}%`, "--i": i } as Vars}
              aria-label={[`${look.at}, ${look.label.toLowerCase()}`, ...used].join(", ")}
            >
              <span className="mgr-run-tip" aria-hidden>
                <b>
                  {look.at} {look.label}
                </b>
                {used.length > 0 && <span>{used.join(" · ")}</span>}
              </span>
            </button>
          );
        })}
      </div>
      <figcaption className="mgr-run-scale">
        {/* Off at the open: the stretch it never saw says so where the open would be. */}
        <span>{offUntil != null && looks[0] ? `Off until ${looks[0].at}` : "09:15 open"}</span>
        {looks.length === 0 && <span>{empty}</span>}
        <span>15:30 close</span>
      </figcaption>
    </figure>
  );
}
