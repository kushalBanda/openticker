import type { ReactNode } from "react";
import { Link } from "react-router";
import { type Manager, useBrainNote } from "../../api/queries";

type ManagerPlan = NonNullable<Manager["plan"]>;

import { istMinute } from "../../lib/format";

/** A day's plan, as the manager set it, with the lessons it relied on. */
export function Plan({
  plan,
  title,
  empty,
  children,
}: {
  plan: ManagerPlan | null;
  title: string;
  empty: string;
  children?: ReactNode;
}) {
  return (
    <div className="tile" data-flush="true">
      <div className="tile-head">
        <h2>{title}</h2>
        <span className="flex-1" />
        {plan && <span className="note">{istMinute(new Date(plan.at))}</span>}
      </div>
      <div style={{ padding: "0 24px 20px" }}>
        {!plan ? (
          <p className="note" style={{ margin: 0 }}>
            {empty}
          </p>
        ) : (
          <>
            <p style={{ margin: "0 0 12px", maxWidth: "70ch" }}>{plan.text}</p>
            {plan.lesson_ids.length > 0 && (
              <>
                <div className="label">Lessons it relied on</div>
                <ul className="mgr-lessons">
                  {plan.lesson_ids.map((id) => (
                    <Lesson key={id} id={id} />
                  ))}
                </ul>
              </>
            )}
          </>
        )}
      </div>
      {children}
    </div>
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
