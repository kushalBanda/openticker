import type { ReactNode } from "react";
import { MISSING } from "../lib/format";

/** A stat card: label, value, one note line (DESIGN.md Stat Card). */
export function StatCard({
  label,
  value,
  note,
  tone,
  testId,
}: {
  label: string;
  value: ReactNode;
  note?: ReactNode;
  tone?: "up" | "down";
  testId?: string;
}) {
  return (
    <div className="stat" data-testid={testId}>
      <div className="label">{label}</div>
      <div className={`value ${tone ?? ""}`}>{value}</div>
      {note && <div className="note">{note}</div>}
    </div>
  );
}

/**
 * A stat's value from its query: a skeleton while it loads, "—" once it has
 * failed (the page says why beside it), the figure when it's there.
 */
export function loaded<T>(
  query: { data: T | undefined; isError: boolean },
  show: (data: T) => ReactNode,
  width = 120,
): ReactNode {
  if (query.data !== undefined) return show(query.data);
  if (query.isError) return <span className="missing">{MISSING}</span>;
  return <span className="skeleton" style={{ width }} />;
}
