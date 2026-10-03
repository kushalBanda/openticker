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

/** A query that failed with nothing to show: why, and how to ask again. */
export interface Failure {
  error: Error;
  retry: () => void;
}

export function failureOf(query: {
  data: unknown;
  isError: boolean;
  error: Error | null;
  refetch: () => unknown;
}): Failure | undefined {
  if (!query.isError || query.data !== undefined || !query.error) return undefined;
  return { error: query.error, retry: () => void query.refetch() };
}

/** What a tile says in place of its content when that didn't load. */
export function TableFailed({ what, failure }: { what: string; failure: Failure }) {
  return (
    <p className="note table-failed" role="alert">
      {what} didn't load: {failure.error.message.replace(/\.$/, "")}.{" "}
      <button
        type="button"
        className="btn"
        data-variant="ghost"
        data-size="sm"
        onClick={failure.retry}
      >
        Try again
      </button>
    </p>
  );
}
