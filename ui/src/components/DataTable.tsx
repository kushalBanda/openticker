import { Fragment, type ReactNode } from "react";

export interface Column<T> {
  key: string;
  head: ReactNode;
  align?: "left" | "right";
  cell: (row: T) => ReactNode;
  /** A second line under the cell, in note type (DESIGN.md, two-line cells). */
  sub?: (row: T) => ReactNode;
  /** Prose that may wrap; numbers never do. */
  wrap?: boolean;
}

/**
 * A table inside a flush tile (DESIGN.md Tables). Row actions take no
 * column: they show in a glass pill at the end of the instrument cell (the
 * first, or `actionsAt`) on hover, focus or selection, as Kite puts B / S
 * beside the instrument, so they never cover a number. `detail` adds a
 * full-width line under a row: a rejection's reason.
 */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  actions,
  actionsAt,
  detail,
  selected,
  onSelect,
  dense,
  total,
  label,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  actions?: (row: T) => ReactNode;
  /** The column whose cell holds the actions pill; the first by default. */
  actionsAt?: string;
  detail?: (row: T) => ReactNode;
  selected?: string;
  onSelect?: (key: string) => void;
  dense?: boolean;
  /** The total row's cells after its label, lined up from the second column. */
  total?: ReactNode;
  label: string;
}) {
  return (
    <table className="table" data-dense={dense ?? false} aria-label={label}>
      <thead>
        <tr>
          {columns.map((column) => (
            <th key={column.key} scope="col" data-align={column.align ?? "right"}>
              {column.head}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => {
          const key = rowKey(row);
          const more = detail?.(row);
          const pillAt = actionsAt ?? columns[0]?.key;
          return (
            <Fragment key={key}>
              <tr
                aria-selected={selected === undefined ? undefined : selected === key}
                data-clickable={onSelect ? true : undefined}
                onClick={onSelect ? () => onSelect(key) : undefined}
              >
                {columns.map((column) => {
                  const pill = actions && column.key === pillAt;
                  return (
                    <td
                      key={column.key}
                      data-align={column.align ?? "right"}
                      data-wrap={column.wrap}
                      className={pill ? "has-actions" : undefined}
                    >
                      {column.cell(row)}
                      {column.sub && <div className="sub">{column.sub(row)}</div>}
                      {pill && (
                        // A click on an action is the action's, not the row's.
                        // biome-ignore lint/a11y/noStaticElementInteractions: only stops the row's click
                        // biome-ignore lint/a11y/useKeyWithClickEvents: the buttons inside take keys
                        <div className="row-actions" onClick={(event) => event.stopPropagation()}>
                          {actions(row)}
                        </div>
                      )}
                    </td>
                  );
                })}
              </tr>
              {more && (
                <tr className="detail">
                  <td colSpan={columns.length}>{more}</td>
                </tr>
              )}
            </Fragment>
          );
        })}
        {total}
      </tbody>
    </table>
  );
}
