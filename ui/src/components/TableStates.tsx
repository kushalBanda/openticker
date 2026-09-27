/** Rows loading inside a flush tile. */
export function TableSkeleton({ label, rows = 2 }: { label: string; rows?: number }) {
  return (
    <div role="status" aria-busy="true" aria-label={label}>
      {Array.from({ length: rows }, (_, n) => n).map((i) => (
        <div key={i} className="flex items-center gap-6 px-6" style={{ height: 44 }}>
          <span className="skeleton" style={{ width: 60 }} />
          <span className="skeleton" style={{ width: 140 }} />
          <span className="flex-1" />
          <span className="skeleton" style={{ width: 80 }} />
        </div>
      ))}
    </div>
  );
}

/** What an empty flush tile says instead of a table. */
export function TableEmpty({ children }: { children: string }) {
  return (
    <p className="note" style={{ margin: 0, padding: "12px 24px 20px" }}>
      {children}
    </p>
  );
}
