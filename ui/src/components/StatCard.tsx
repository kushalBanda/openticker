import type { ReactNode } from "react";

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
