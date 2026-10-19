import { type ReactNode, useId } from "react";
import { Link } from "react-router";

/**
 * A tile's head row (DESIGN.md Page structure): its title with Kite's count,
 * a note beside it, and on the right its actions or a `›` link to the page
 * it summarises. `divider` starts a second section inside the same tile.
 */
export function TileHead({
  title,
  id,
  count,
  note,
  actions,
  more,
  divider,
}: {
  title: ReactNode;
  id?: string;
  /** Kite's way: Open orders (2). */
  count?: number;
  /** Muted, right after the title: "newest first". */
  note?: ReactNode;
  /** On the right: a button, a segmented control, a timestamp. */
  actions?: ReactNode;
  /** A link to the full page: { to: "/positions", label: "All positions" }. */
  more?: { to: string; label: string };
  divider?: boolean;
}) {
  return (
    <div className="tile-head" data-divider={divider || undefined}>
      <h2 id={id}>
        {title}
        {count !== undefined && <span className="count"> ({count})</span>}
      </h2>
      {note && <span className="note">{note}</span>}
      <span className="flex-1" />
      {actions}
      {more && (
        <Link to={more.to} className="more-link">
          {more.label} ›
        </Link>
      )}
    </div>
  );
}

/**
 * A tile (DESIGN.md Elevation): a `surface` box the ground separates, no
 * border, no shadow. With a title it is a labelled region with a head row;
 * `flush` drops the padding for a table or list that reaches the edges.
 */
export function Tile({
  title,
  count,
  note,
  actions,
  more,
  flush,
  id,
  className,
  testId,
  label,
  children,
}: {
  title?: ReactNode;
  count?: number;
  note?: ReactNode;
  actions?: ReactNode;
  more?: { to: string; label: string };
  flush?: boolean;
  /** An anchor to scroll to: /settings#keys. */
  id?: string;
  className?: string;
  testId?: string;
  /** The region's name when it has no title. */
  label?: string;
  children?: ReactNode;
}) {
  const head = useId();
  return (
    <section
      id={id}
      className={className ? `tile ${className}` : "tile"}
      data-flush={flush || undefined}
      data-testid={testId}
      aria-labelledby={title !== undefined ? head : undefined}
      aria-label={title === undefined ? label : undefined}
    >
      {title !== undefined && (
        <TileHead id={head} title={title} count={count} note={note} actions={actions} more={more} />
      )}
      {children}
    </section>
  );
}

/**
 * A tile with nothing to show yet, or a page whose data didn't load: a
 * heading that says so, one line on why or what next, and the way on.
 */
export function EmptyTile({
  title,
  children,
  action,
  alert,
  inset,
}: {
  title: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
  /** A failure, read out at once. */
  alert?: boolean;
  /** Inside a tile already: the box is the tile's, only the words are this. */
  inset?: boolean;
}) {
  return (
    <div className={inset ? "empty" : "tile empty"} role={alert ? "alert" : undefined}>
      <h2>{title}</h2>
      {children && <p className="note">{children}</p>}
      {action && <div className="empty-actions">{action}</div>}
    </div>
  );
}

/** A page's data that didn't load: what, the server's reason, and Try again. */
export function FailedTile({
  what,
  error,
  retry,
  title,
  inset,
}: {
  what: string;
  error: Error;
  retry?: () => unknown;
  /** A heading other than "<what> didn't load". */
  title?: ReactNode;
  inset?: boolean;
}) {
  return (
    <EmptyTile
      alert
      inset={inset}
      title={title ?? `${what} didn't load`}
      action={
        retry && (
          <button type="button" className="btn" onClick={() => void retry()}>
            Try again
          </button>
        )
      }
    >
      {error.message}
    </EmptyTile>
  );
}
