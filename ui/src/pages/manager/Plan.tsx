import type { ReactNode } from "react";
import { Link } from "react-router";
import { useBrainNote } from "../../api/queries";
import { direction, istMinute, rupees } from "../../lib/format";
import {
  type DayFigure,
  deskRoom,
  type ManagerLine,
  type ManagerPlan,
  type PlanItem,
  planGroups,
  planItemHref,
  planItemLabel,
} from "../../lib/manager";

/**
 * A day's plan, as the manager set it (ADR 45): the headline, each one's
 * call grouped, what it watches, and the lessons it relied on. Today's plan
 * also gets `lines` and `desk`, so each item shows its line and money now
 * and the desk its room before the stop. A plan set before items is its
 * text alone.
 */
export function Plan({
  plan,
  title,
  empty,
  lines = null,
  desk = null,
  children,
}: {
  plan: ManagerPlan | null;
  title: string;
  empty: string;
  lines?: ManagerLine[] | null;
  desk?: DayFigure | null;
  children?: ReactNode;
}) {
  const structured = plan != null && (plan.items.length > 0 || plan.watch.length > 0);
  const groups = plan ? planGroups(plan.items, lines) : [];
  const deskStop = lines?.find((l) => l.key === "desk")?.stop;
  return (
    <div className="tile" data-flush="true">
      <div className="tile-head">
        <h2>{title}</h2>
        <span className="flex-1" />
        {plan && <span className="note">{istMinute(new Date(plan.at))}</span>}
      </div>
      <div className="mgr-plan">
        {!plan ? (
          <p className="note" style={{ margin: 0 }}>
            {empty}
          </p>
        ) : (
          <>
            <p className={structured ? "mgr-plan-headline" : "mgr-plan-prose"}>{plan.text}</p>
            {lines && <DeskRoom net={desk?.net} stop={deskStop} />}
            {structured && (
              <>
                {!groups.some((g) => g.call === "runs") && (
                  <section className="mgr-plan-group">
                    <h3 className="label">Runs</h3>
                    <p className="note mgr-plan-none">Nothing enters today</p>
                  </section>
                )}
                {groups.map((group) => (
                  <section key={group.call} className="mgr-plan-group" data-call={group.call}>
                    <h3 className="label">
                      {group.title} <span className="mgr-plan-count">{group.items.length}</span>
                    </h3>
                    <ul>
                      {group.items.map(({ item, line }) => (
                        <Item key={item.key} item={item} line={line} live={lines != null} />
                      ))}
                    </ul>
                  </section>
                ))}
              </>
            )}
            {plan.watch.length > 0 && (
              <section className="mgr-plan-group">
                <h3 className="label">Watching</h3>
                <ul className="mgr-plan-watch">
                  {plan.watch.map((thing) => (
                    <li key={thing} className="mgr-plan-watch-item">
                      {thing}
                    </li>
                  ))}
                </ul>
              </section>
            )}
            {plan.lesson_ids.length > 0 && (
              <section className="mgr-plan-group">
                <h3 className="label">Lessons it relied on</h3>
                <ul className="mgr-lessons">
                  {plan.lesson_ids.map((id) => (
                    <Lesson key={id} id={id} />
                  ))}
                </ul>
              </section>
            )}
          </>
        )}
      </div>
      {children}
    </div>
  );
}

/** The desk's net today against its stop, and what's left before it's crossed. */
function DeskRoom({
  net,
  stop,
}: {
  net: number | null | undefined;
  stop: number | null | undefined;
}) {
  const room = deskRoom(net, stop);
  if (!room || net == null || stop == null) return null;
  const pct = Math.round(room.used * 100);
  return (
    <div className="mgr-plan-desk">
      <div className="mgr-plan-desk-head">
        <span>
          Desk today <b className={direction(net)}>{rupees(net, { sign: true, decimals: 0 })}</b>
        </span>
        <span className="note">
          {room.left > 0
            ? `${rupees(room.left, { decimals: 0 })} left before its stop of ${rupees(stop, { decimals: 0 })}`
            : `At its stop of ${rupees(stop, { decimals: 0 })}`}
        </span>
      </div>
      <div
        className="mgr-plan-meter"
        aria-hidden="true"
        data-tone={room.used >= 0.75 ? "down" : room.used >= 0.4 ? "warn" : undefined}
      >
        <span style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function Item({ item, line, live }: { item: PlanItem; line: ManagerLine | null; live: boolean }) {
  const href = planItemHref(item.key);
  const label = planItemLabel(item);
  const net = line?.today?.net;
  return (
    <li className="mgr-plan-item">
      <span className="mgr-plan-name">
        {href ? (
          <Link className="mgr-plan-link" to={href}>
            {label}
          </Link>
        ) : (
          label
        )}
      </span>
      {live && (
        <span className="mgr-plan-meta">
          {line?.stop != null ? (
            <span data-crossed={line.crossed || undefined}>
              stop {rupees(line.stop, { decimals: 0 })}
            </span>
          ) : (
            item.call !== "sits_out" && <span className="mgr-plan-nostop">no stop</span>
          )}
          {net != null && net !== 0 && (
            <b className={direction(net)}>{rupees(net, { sign: true, decimals: 0 })}</b>
          )}
        </span>
      )}
      <span className="mgr-plan-why">{item.why}</span>
    </li>
  );
}

function Lesson({ id }: { id: string }) {
  const note = useBrainNote(id);
  return (
    <li>
      <Link to={`/brain/lessons/${id}`}>{note.data?.title ?? id}</Link>
    </li>
  );
}
